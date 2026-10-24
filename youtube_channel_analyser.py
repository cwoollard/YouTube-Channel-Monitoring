#!/usr/bin/env python3
"""Generate an offline, self-contained HTML analysis from YouTube monitor SQLite data.
Install: python3 -m pip install -U pandas plotly
Run: python3 youtube_channel_analyser.py --db youtube_channel_monitor.sqlite3
"""
import argparse
import html
import sqlite3
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.offline import plot


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default='youtube_channel_monitor.sqlite3')
    ap.add_argument('--output', default='youtube_channel_report.html')
    ap.add_argument('--max-videos', type=int, default=12, help='Number of newest videos plotted')
    a = ap.parse_args()
    with sqlite3.connect(a.db) as c:
        obs = pd.read_sql_query('SELECT o.*, v.published, v.url FROM observations o LEFT JOIN videos v USING(video_id)', c)
        changes = pd.read_sql_query('SELECT * FROM changes ORDER BY changed_at', c)
        listing = pd.read_sql_query('SELECT * FROM listing_observations', c) if c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='listing_observations'").fetchone()[0] else pd.DataFrame()
    if obs.empty:
        raise SystemExit('Database has no observations.')
    obs['observed_at'] = pd.to_datetime(obs['observed_at'], utc=True, errors='coerce')
    obs['published'] = pd.to_datetime(obs['published'], utc=True, errors='coerce')
    obs = obs.dropna(subset=['observed_at']).sort_values(['video_id','observed_at'])
    for col in ['views','likes','comments']:
        obs[col] = pd.to_numeric(obs[col], errors='coerce')
    obs['elapsed_h'] = obs.groupby('video_id')['observed_at'].diff().dt.total_seconds()/3600
    obs['view_delta'] = obs.groupby('video_id')['views'].diff()
    obs['raw_views_per_hour'] = obs['view_delta']/obs['elapsed_h']
    obs['negative_adjustment'] = obs['view_delta'] < 0
    # Zero growth is valid. Negative public-count revisions are displayed at zero,
    # but retained as distinct events in the hover text and adjustment table.
    obs['views_per_hour'] = obs['raw_views_per_hour'].clip(lower=0)
    obs['rolling_6h'] = float('nan')
    for vid, group in obs.groupby('video_id'):
        group = group.sort_values('observed_at')
        # A six-hour window requires a reasonably complete run of observations.
        # Split at gaps >2.5h, so smoothing never bridges missing collection.
        segments = (group['elapsed_h'].fillna(0) > 2.5).cumsum()
        for _, segment in group.groupby(segments):
            times = segment['observed_at']
            counts = segment['views']
            for idx in segment.index:
                end_time = obs.at[idx, 'observed_at']
                window = segment[(times >= end_time - pd.Timedelta(hours=6)) & (times <= end_time) & counts.notna()]
                if len(window) < 3:
                    continue
                hours = (window['observed_at'].iloc[-1] - window['observed_at'].iloc[0]).total_seconds() / 3600
                if hours < 2 or hours > 6.01:
                    continue
                delta = window['views'].iloc[-1] - window['views'].iloc[0]
                obs.at[idx, 'rolling_6h'] = max(0, delta / hours)
    # Do not treat a long observation gap as an hourly measurement.
    obs.loc[(obs.elapsed_h > 2.5) | (obs.elapsed_h < .1) | obs.views.isna() | obs.groupby('video_id').views.shift().isna(), 'views_per_hour'] = float('nan')
    last = obs.groupby('video_id').tail(1).sort_values('published', ascending=False)
    chosen = last.head(a.max_videos)['video_id'].tolist()
    titles = {r.video_id: str(r.title or r.video_id) for r in last.itertuples()}
    figures=[]
    for kind in ['views','views_per_hour']:
        fig=go.Figure()
        for vid in chosen:
            d=obs[obs.video_id==vid]
            fig.add_trace(go.Scatter(x=d.observed_at,y=d[kind],name=titles[vid][:60],mode='lines+markers' if len(d)<12 else 'lines',connectgaps=False,
                hovertemplate='%{x}<br>%{y:,.1f}<extra>%{fullData.name}</extra>'))
        fig.update_layout(title='Cumulative public views' if kind=='views' else 'Views per hour (gaps >2.5h excluded)',height=490,
                          xaxis_title='Observation time (UTC)',yaxis_title='Views' if kind=='views' else 'Views/hour',hovermode='x unified',legend=dict(orientation='h',y=-.2),margin=dict(l=55,r=30,t=60,b=60))
        figures.append(fig)
    # Video-specific view curves with markers for recorded changes.
    detail=[]
    changes['changed_at']=pd.to_datetime(changes['changed_at'],utc=True,errors='coerce')
    for vid in last['video_id'].tolist():
        d=obs[obs.video_id==vid]
        fig=make_subplots(specs=[[{'secondary_y':True}]])
        fig.add_trace(go.Scatter(x=d.observed_at,y=d.views,name='Views',mode='lines'),secondary_y=False)
        fig.add_trace(go.Scatter(x=d.observed_at,y=d.views_per_hour,name='Views/hour (adjusted)',mode='lines',connectgaps=False,customdata=d[['view_delta']].to_numpy(),hovertemplate='%{x}<br>Rate: %{y:.1f}/hour<br>Raw view change: %{customdata[0]:+.0f}<extra></extra>'),secondary_y=True)
        fig.add_trace(go.Scatter(x=d.observed_at,y=d.rolling_6h,name='6h rolling rate',mode='lines',connectgaps=False,line=dict(width=3)),secondary_y=True)
        revisions=d[d.negative_adjustment & d.views_per_hour.notna()]
        if not revisions.empty:
            fig.add_trace(go.Scatter(x=revisions.observed_at,y=[0]*len(revisions),name='Downward view revision',mode='markers',marker=dict(symbol='x',size=10,color='darkorange'),customdata=revisions[['view_delta']].to_numpy(),hovertemplate='%{x}<br>Public count revised by %{customdata[0]:+.0f} views<extra></extra>'),secondary_y=True)
        for r in changes[(changes.video_id==vid)&changes.change_type.isin(['title_changed','thumbnail_changed'])].itertuples():
            if pd.notna(r.changed_at):
                fig.add_vline(x=r.changed_at.to_pydatetime().timestamp()*1000,line_dash='dot',line_color='gray')
        fig.update_layout(title=titles[vid],height=380,hovermode='x unified',margin=dict(l=55,r=45,t=65,b=45))
        fig.update_yaxes(title_text='Cumulative views',secondary_y=False)
        fig.update_yaxes(title_text='Views/hour',secondary_y=True)
        detail.append(fig)
    parts=[]
    first=True
    for fig in figures+detail:
        parts.append(plot(fig,include_plotlyjs=True if first else False,output_type='div',config={'responsive':True,'displaylogo':False}))
        first=False
    # One selectable chart per monitored video, including older high-performing uploads.
    detail_html=[]
    for i, vid in enumerate(last['video_id'].tolist()):
        title=html.escape(titles[vid])
        detail_html.append(f'<section class="card video-detail" data-video="{html.escape(vid)}" style="display:none"><h3>{title}</h3>{parts[i+2]}</section>')
    options=''.join(f'<option value="{html.escape(vid)}" {"selected" if vid == last.iloc[0].video_id else ""}>{html.escape(titles[vid])}</option>' for vid in last['video_id'].tolist())
    summary=last[['title','published','views','likes','comments','video_id']].copy()
    summary['published']=summary.published.dt.strftime('%Y-%m-%d')
    summary['video_id']=summary.video_id.map(lambda x:f'<a href="https://www.youtube.com/watch?v={html.escape(x)}">Video</a>')
    summary=summary.rename(columns={'title':'Latest title','published':'Published','views':'Views','likes':'Likes','comments':'Comments','video_id':'Link'})
    change_rows=changes[['changed_at','video_id','change_type','old_value','new_value']].copy()
    change_rows['changed_at']=change_rows.changed_at.dt.strftime('%Y-%m-%d %H:%M UTC')
    change_rows=change_rows.rename(columns={'changed_at':'Observed','video_id':'Video ID','change_type':'Event','old_value':'Old','new_value':'New'})
    negative_rows=obs[obs.negative_adjustment][['observed_at','video_id','title','view_delta']].copy()
    negative_rows['observed_at']=negative_rows.observed_at.dt.strftime('%Y-%m-%d %H:%M UTC')
    negative_rows=negative_rows.rename(columns={'observed_at':'Observed','video_id':'Video ID','title':'Video','view_delta':'Revision (views)'})
    variants=''
    if not listing.empty:
        grp=listing.groupby(['video_id','listing_title','detail_title'],dropna=False).size().reset_index(name='Polls')
        grp=grp.sort_values('Polls',ascending=False).head(80)
        variants='<h2>Channel-listing versus detail titles</h2><p>Counts represent observations by this monitor, NOT YouTube audience allocation.</p>'+grp.to_html(index=False,escape=True,classes='data')
    start=obs.observed_at.min().strftime('%d %b %Y')
    end=obs.observed_at.max().strftime('%d %b %Y')
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>YouTube Channel Analysis</title><style>
    body{{font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#172337;background:#f4f7fb;margin:0}}
    main{{max-width:1320px;margin:auto;padding:24px}}h1{{font-size:32px}}h2{{margin-top:42px}}
    .card{{background:white;border-radius:12px;padding:18px;margin:18px 0;box-shadow:0 2px 14px #18315312;overflow:visible}}
    .data{{border-collapse:collapse;width:100%;font-size:13px}}.data td,.data th{{padding:9px;border-bottom:1px solid #e5e9f0;text-align:left;max-width:440px;overflow-wrap:anywhere}}
    select{{font:inherit;padding:10px;width:min(100%,700px);border:1px solid #bac8db;border-radius:8px;background:white}} .video-detail h3{{margin:0 0 8px}}
    .data th{{background:#eaf0f8}}.note{{background:#fff8e8;padding:16px;border-left:4px solid #e0a522}}
    </style></head><body><main><h1>YouTube Channel Monitoring Report</h1>
    <p><b>{start} – {end}</b> · {len(obs):,} observations · {obs.video_id.nunique()} videos · {len(changes)} recorded events</p>
    <div class="note"><b>Interpretation:</b> Public view totals are shared across title/thumbnail variants. A title appearing in a poll does not identify which version individual viewers saw or prove that it increased clicks. Zero-growth hours are shown at zero; downward public-count revisions are marked separately and plotted at zero. Six-hour rolling rates require at least three observations spanning two hours and never bridge gaps over 2.5 hours. View rates across long gaps are excluded; no missing hourly values are invented. Before/after changes are not causal estimates. Dotted markers indicate recorded metadata changes only.</div>
    <section class="card">{parts[0]}</section><section class="card">{parts[1]}</section>
    <h2>Individual video timelines</h2><p>Choose any monitored video, including older uploads such as the vintage tent video. Each chart shows cumulative views, hourly rate, six-hour rolling rate and recorded changes.</p><label for="video-picker"><b>Video:</b></label><br><select id="video-picker">{options}</select>{''.join(detail_html)}
    <section class="card"><h2>Latest video statistics</h2>{summary.to_html(index=False,escape=False,classes='data')}</section>
    <section class="card"><h2>Downward public-view-count revisions</h2>{negative_rows.to_html(index=False,escape=True,classes='data') if not negative_rows.empty else '<p>No downward revisions recorded.</p>'}</section>
    <section class="card"><h2>Recorded events</h2>{change_rows.to_html(index=False,escape=True,classes='data')}</section>
    <section class="card">{variants or '<h2>Listing variants</h2><p>Run monitor v3 to start collecting separate channel-listing titles.</p>'}</section>
    <p>Generated locally from the supplied SQLite database. All chart JavaScript is embedded; this file works offline.</p></main><script>
    const picker=document.getElementById('video-picker');
    function showVideo(){{document.querySelectorAll('.video-detail').forEach(el=>{{el.style.display=el.dataset.video===picker.value?'block':'none';}}); window.dispatchEvent(new Event('resize'));}}
    picker.addEventListener('change',showVideo);showVideo();
    </script></body></html>'''
    Path(a.output).write_text(page,encoding='utf-8')
    print(f'Wrote {a.output} ({len(obs)} observations, {obs.video_id.nunique()} videos)')

if __name__=='__main__':
    main()
