#!/usr/bin/env python3
"""Interactive, read-only, offline comparisons across independent YouTube monitor databases."""
import argparse
import html
import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
from plotly.offline import get_plotlyjs


def load_channel(item, base):
    path = Path(item['database'])
    if not path.is_absolute():
        path = base / path
    if not path.is_file():
        return None
    con = sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)
    try:
        obs = pd.read_sql_query('SELECT video_id, observed_at, title, views FROM observations ORDER BY observed_at, id', con)
        vids = pd.read_sql_query('SELECT video_id, published, upload_date FROM videos', con)
        changes = pd.read_sql_query('SELECT changed_at, video_id, change_type FROM changes', con)
    finally:
        con.close()
    if obs.empty:
        return None
    obs['time'] = pd.to_datetime(obs.observed_at, utc=True, errors='coerce')
    obs['views'] = pd.to_numeric(obs.views, errors='coerce')
    obs = obs.dropna(subset=['time', 'views']).sort_values(['video_id', 'time'])
    obs = obs.drop_duplicates(['video_id', 'time'], keep='last')
    vids['pub'] = pd.to_datetime(vids.published, utc=True, errors='coerce')
    vids['pub'] = vids.pub.fillna(pd.to_datetime(vids.upload_date, format='%Y%m%d', utc=True, errors='coerce'))
    pubs = dict(zip(vids.video_id, vids.pub))
    videos = []
    for vid, group in obs.groupby('video_id'):
        group = group.sort_values('time')
        pub = pubs.get(vid)
        videos.append({
            'id': str(vid),
            'title': str(group.title.dropna().iloc[-1]) if group.title.notna().any() else str(vid),
            'pub': None if pd.isna(pub) else int(pub.timestamp() * 1000),
            'points': [[int(t.timestamp() * 1000), int(v)] for t, v in zip(group.time, group.views)],
        })
    events = []
    for row in changes.itertuples(index=False):
        typ = str(row.change_type or '').lower()
        if 'title' not in typ and 'thumbnail' not in typ:
            continue
        timestamp = pd.to_datetime(row.changed_at, utc=True, errors='coerce')
        if pd.isna(timestamp):
            continue
        events.append({'time': int(timestamp.timestamp()*1000), 'type': 'thumbnail' if 'thumbnail' in typ else 'title'})
    return {'id': item['id'], 'name': item['name'], 'creator': item.get('creator', item['name']),
            'videos': videos, 'events': events,
            'first': min(v['points'][0][0] for v in videos),
            'last': max(v['points'][-1][0] for v in videos)}


CSS = '''
body{margin:0;background:#f4f7fb;color:#172337;font:15px system-ui,-apple-system,sans-serif}
.wrap{max-width:1180px;margin:auto;padding:28px 18px 65px}h1{font-size:29px;margin:0 0 10px}h2{font-size:20px;margin:0 0 12px}
p{line-height:1.55}.card{background:white;border-radius:11px;padding:20px;margin:18px 0;box-shadow:0 3px 14px #12223a0a}
.notice{background:#fff8e8;border-left:4px solid #d9a221;padding:14px 18px;margin:18px 0;line-height:1.55}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:14px 26px}.channel-list{display:flex;flex-wrap:wrap;gap:14px}
label{cursor:pointer}select{padding:8px;border:1px solid #c7d2e2;border-radius:6px;background:white;font:inherit}
.pill{display:inline-flex;gap:8px;align-items:center;background:#f0f4fb;border-radius:7px;padding:9px 12px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:11px 9px;text-align:left;border-bottom:1px solid #e2e7ef}th{background:#eaf0f8}
.muted{color:#53667f}.chart{width:100%;min-height:390px}.empty{padding:45px 16px;text-align:center;color:#586982}
small{color:#54657a}.status{margin-top:14px;font-size:14px;line-height:1.6}
@media(max-width:700px){.wrap{padding:18px 12px}.card{padding:12px}table{min-width:780px}}
'''

JS = r'''
const channels = __DATA__;
const HOUR = 3600000, DAY = 24 * HOUR;
const ids = channels.map(c => c.id);
const chosen = new Set(ids);
const colors = ['#5868ec','#00a987','#e87748','#9c6cce','#e3a229','#317eb7'];
const colorById = Object.fromEntries(channels.map((c,i)=>[c.id,colors[i%colors.length]]));
const allStart = Math.max(...channels.map(c=>c.first));
const allEnd = Math.min(...channels.map(c=>c.last));
const nice = ms => new Date(ms).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})+' UTC';
const num = n => Number(n).toLocaleString('en-GB',{maximumFractionDigits:0});
const fmt = (n,dec=1) => Number.isFinite(n) ? n.toFixed(dec) : '—';
const selected = () => channels.filter(c=>chosen.has(c.id));
const $ = id=>document.getElementById(id);
function windowFor(list,period){
  const end=Math.min(...list.map(c=>c.last));
  const start=period==='all' ? Math.max(...list.map(c=>c.first)) : end - Number(period)*DAY;
  return {start,end, valid:start<end};
}
function complete(c,start,end){
  // Tolerance for an hourly polling cycle; don't silently shorten requested periods.
  return c.first <= start+1.5*HOUR && c.last >= end-1.5*HOUR;
}
function rowsFor(c,start,end){
  const rows=[];
  for(const v of c.videos){
    const points=v.points.filter(p=>p[0]>=start && p[0]<=end);
    if(points.length<2) continue;
    const first=points[0],last=points[points.length-1];
    const hours=(last[0]-first[0])/HOUR;
    if(hours<=0) continue;
    const gain=last[1]-first[1];
    rows.push({id:v.id,title:v.title,gain,hours,rate:gain/hours,pct:first[1]>0?gain*100/first[1]:NaN});
  }
  return rows;
}
function median(values){
  const a=values.filter(Number.isFinite).sort((x,y)=>x-y);
  if(!a.length)return NaN;
  const m=Math.floor(a.length/2);
  return a.length%2?a[m]:(a[m-1]+a[m])/2;
}
function countEvents(c,start,end){
  const within=c.events.filter(e=>e.time>=start && e.time<=end);
  return {title:within.filter(e=>e.type==='title').length,thumbnail:within.filter(e=>e.type==='thumbnail').length};
}
function eligible(c){
  const curves=[];
  for(const v of c.videos){
    if(v.pub===null)continue;
    const pts=v.points.map(p=>({age:(p[0]-v.pub)/HOUR,views:p[1]})).filter(p=>p.age>=0&&p.age<=72);
    if(pts.length<3||pts[0].age>3||pts[pts.length-1].age<12)continue;
    curves.push({video:v,points:pts});
  }
  return curves;
}
const layout=(title,yTitle,extra={})=>({title:{text:title,font:{size:18}},template:'plotly_white',height:390,
  margin:{l:65,r:25,t:60,b:75},xaxis:{automargin:true},yaxis:{title:yTitle,automargin:true},
  legend:{orientation:'h',y:-.28},hovermode:'closest',...extra});
const config={responsive:true,displaylogo:false};
function plot(id,traces,lay){Plotly.react(id,traces,lay,config);}
function empty(id,message){Plotly.purge(id);$(id).innerHTML='<div class="empty">'+message+'</div>';}
function update(){
  const list=selected(), period=$('period').value;
  if(!list.length){$('status').textContent='Select at least one channel.';$('summary').innerHTML='';
    for(const id of ['gain','rate','changes','launch'])empty(id,'Select a channel to display this chart.');return;}
  const w=windowFor(list,period);
  const partial=!w.valid||list.some(c=>!complete(c,w.start,w.end));
  let message=w.valid?`Selected window: ${nice(w.start)} to ${nice(w.end)}. `:'No overlapping observations for these channels. ';
  if(period!=='all')message+=`Requested period: last ${period} days. `;
  if(partial)message+='Insufficient coverage for a fair comparison over this entire period. No growth figures are shown; choose a shorter period or All shared history.';
  else message+='Growth uses paired readings within this window; individual video coverage can vary. Metadata changes below use this same window.';
  $('status').textContent=message;
  const summaries=partial?[]:list.map(c=>{
    const rows=rowsFor(c,w.start,w.end), ev=countEvents(c,w.start,w.end);
    return {channel:c,rows,ev,gain:rows.reduce((s,r)=>s+r.gain,0),rate:median(rows.map(r=>r.rate)),pct:median(rows.map(r=>r.pct))};
  });
  $('summary').innerHTML=summaries.length?summaries.map(s=>`<tr><td>${escapeHTML(s.channel.name)}</td><td>${escapeHTML(s.channel.creator)}</td><td>${s.rows.length}</td><td>${num(s.gain)}</td><td>${fmt(s.rate)}</td><td>${Number.isFinite(s.pct)?fmt(s.pct,2)+'%':'—'}</td><td>${s.ev.title}</td><td>${s.ev.thumbnail}</td><td>${eligible(s.channel).length}</td></tr>`).join(''):'<tr><td colspan="9">Insufficient complete coverage for the requested period.</td></tr>';
  if(summaries.length){
    plot('gain',[{type:'bar',x:summaries.map(s=>s.channel.name),y:summaries.map(s=>s.gain),marker:{color:summaries.map(s=>colorById[s.channel.id])},text:summaries.map(s=>num(s.gain)),textposition:'outside'}],layout('Additional views across monitored videos','Net change in public views'));
    plot('rate',[{type:'bar',x:summaries.map(s=>s.channel.name),y:summaries.map(s=>s.rate),marker:{color:summaries.map(s=>colorById[s.channel.id])},text:summaries.map(s=>fmt(s.rate)),textposition:'outside'}],layout('Median video growth rate','Views/hour per video'));
    const cats=summaries.map(s=>s.channel.name);
    plot('changes',[{type:'bar',name:'Title changes',x:cats,y:summaries.map(s=>s.ev.title)},{type:'bar',name:'Thumbnail changes',x:cats,y:summaries.map(s=>s.ev.thumbnail)}],layout('Recorded metadata changes during selected window','Detected changes',{barmode:'group'}));
  } else for(const id of ['gain','rate','changes'])empty(id,'Insufficient shared coverage for this period.');
  // Launch curves are age-aligned, independent of the selected calendar window.
  const traces=[];const counts=[];
  for(const c of list){
    const curves=eligible(c);counts.push(`${c.name}: ${curves.length}`);
    for(let j=0;j<curves.length;j++){
      const {video,points}=curves[j];
      traces.push({type:'scatter',mode:'lines',x:points.map(p=>p.age),y:points.map(p=>p.views),
        name:`${c.name} — ${video.title}`,legendgroup:c.id,showlegend:true,line:{color:colorById[c.id],width:2,dash:['solid','dash','dot','dashdot'][j%4]},
        customdata:points.map(()=>video.title),hovertemplate:'%{customdata}<br>Age: %{x:.1f}h<br>Views: %{y:,.0f}<extra>'+escapeHTML(c.name)+'</extra>'});
    }
  }
  $('launch-info').textContent='Eligible videos (first observation within 3 hours of publication; at least 12 hours of follow-up): '+counts.join(' · ')+'. Age-aligned curves are independent of the selected calendar period. Dashed guides mark 24, 48 and 72 hours.';
  if(traces.length){
    const shapes=[24,48,72].map(h=>({type:'line',xref:'x',yref:'paper',x0:h,x1:h,y0:0,y1:1,line:{color:'#9ca9bc',width:1,dash:'dot'}}));
    plot('launch',traces,layout('Early-life public views (eligible uploads only)','Total public views',{
      xaxis:{title:'Hours since publication',range:[0,72]},shapes,height:470,legend:{orientation:'h',y:-.3,font:{size:11}}}));
  } else empty('launch','No eligible uploads yet. Curves will appear when a newly published video has enough observations.');
}
function escapeHTML(str){return String(str).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
$('channel-list').innerHTML=channels.map(c=>`<label class="pill"><input type="checkbox" data-channel="${escapeHTML(c.id)}" checked> ${escapeHTML(c.name)}</label>`).join('');
$('channel-list').addEventListener('change',e=>{if(e.target.matches('input[data-channel]')){
  const id=e.target.dataset.channel;if(e.target.checked)chosen.add(id);else chosen.delete(id);update();}});
$('period').addEventListener('change',update);
update();
'''


def build(channels, output):
    payload = json.dumps(channels, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    script = JS.replace('__DATA__', payload)
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Interactive channel comparisons</title><script>' + get_plotlyjs() + '</script><style>' + CSS + '</style></head><body>'
            '<main class="wrap"><h1>Channel comparisons</h1><p>Compare independent YouTube channel databases. '
            'Paul Messner and Honest Ramble are operated by the same creator.</p>'
            '<section class="card"><h2>Choose channels and period</h2><div class="controls"><div id="channel-list" class="channel-list"></div>'
            '<label>Period <select id="period"><option value="all">All shared history</option><option value="1">Last 24 hours</option>'
            '<option value="7">Last 7 days</option><option value="30">Last 30 days</option></select></label></div>'
            '<div class="status" id="status" role="status"></div></section>'
            '<div class="notice">This report uses publicly observed view counts, not impressions or click-through rates. '
            'Videos differ in age, audience, topic and publication schedule. Counts are not evidence that title or thumbnail changes caused view growth. '
            'First-discovery events are excluded from metadata-change counts. No missing hourly values are invented.</div>'
            '<section class="card"><h2>At a glance</h2><div class="scroll"><table><thead><tr>'
            '<th>Channel</th><th>Creator</th><th>Videos with paired readings</th><th>Net view growth</th>'
            '<th>Median views/hour</th><th>Median % growth</th><th>Title changes</th><th>Thumbnail changes</th><th>Launch-eligible</th>'
            '</tr></thead><tbody id="summary"></tbody></table></div><p class="muted">Metadata-change counts refer to the selected period. '
            'A per-video growth rate uses its first and last available readings in that period.</p></section>'
            '<section class="card"><div class="chart" id="gain"></div></section>'
            '<section class="card"><div class="chart" id="rate"></div></section>'
            '<section class="card"><h2>Early-life comparisons</h2><p id="launch-info" class="muted"></p><div class="chart" id="launch"></div></section>'
            '<section class="card"><div class="chart" id="changes"></div></section>'
            '<section class="card"><h2>Reading the comparisons</h2><p>The period selector is anchored to the latest timestamp shared by the selected channels. '
            'If a channel does not cover the requested full period, the growth comparison is withheld rather than silently shortened. '
            'Select fewer channels or All shared history to compare the data that exists.</p>'
            '<p>Early-life curves are independent of the calendar-period filter: each starts at the observed time since publication, '
            'not an invented zero-view baseline. The 24/48/72-hour guides are reference points, not interpolated milestones.</p></section>'
            '</main><script>' + script + '</script></body></html>')
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix('.tmp')
    tmp.write_text(page, encoding='utf-8')
    os.replace(tmp, output)
    print(f'Wrote {output} ({len(channels)} channels; interactive channel and period controls)', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='channels.json')
    p.add_argument('--output', default='reports/channel-comparison.html')
    args = p.parse_args()
    base = Path(args.config).resolve().parent
    conf = json.loads(Path(args.config).read_text(encoding='utf-8'))
    channels = []
    for item in conf['channels']:
        ch = load_channel(item, base)
        if ch:
            channels.append(ch)
        else:
            print('Skipping channel without observations:', item['id'], flush=True)
    if len(channels) < 2:
        raise SystemExit('Need at least two channels with observations for comparisons.')
    output = Path(args.output)
    if not output.is_absolute():
        output = base / output
    build(channels, output)


if __name__ == '__main__':
    main()
