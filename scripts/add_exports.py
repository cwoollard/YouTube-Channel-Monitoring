#!/usr/bin/env python3
"""Add client-side export controls to self-contained Plotly reports.

Exports reflect the currently visible graph, including user-selected comparison period.
PNG/SVG use Plotly's in-browser exporter; HTML includes plotly.js and plot data.
"""
import argparse
from pathlib import Path

JS = r'''<script id="yt-monitor-export-tools">
(function(){
 const style=document.createElement('style');
style.textContent=`
 .yt-export-panel {
   display: flex;
   gap: 8px;
   flex-wrap: wrap;
   margin: 12px 0 4px;
   padding-top: 12px;
   border-top: 1px solid #e5e9f0;
   clear: both;
 }

 .yt-export-panel button {
   font: 13px system-ui;
   padding: 7px 12px;
   border: 1px solid #b7c5d8;
   background: #fff;
   border-radius: 6px;
   cursor: pointer;
 }

 .yt-export-panel button:hover {
   background: #f1f5fb;
 }

 .card {
   overflow: visible !important;
 }
`;
 document.head.appendChild(style);
 function save(blob,name){const a=document.createElement('a');const u=URL.createObjectURL(blob);a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1500)}
 function install(){
  if(!window.Plotly)return;
  document.querySelectorAll('.js-plotly-plot').forEach((graph,i)=>{
   if(graph.dataset.ytExport)return;
   graph.dataset.ytExport='1';
   const bar=document.createElement('div');bar.className='yt-export-panel';
   const title=(graph.layout&&graph.layout.title&&(graph.layout.title.text||graph.layout.title))||'youtube-graph';
   const stem=String(title).replace(/<[^>]+>/g,'').replace(/[^a-z0-9_-]+/gi,'-').slice(0,65)||('graph-'+i);
   ['PNG','SVG','HTML'].forEach(type=>{
    const btn=document.createElement('button');btn.textContent='Export '+type;
    btn.addEventListener('click',async()=>{
     try{
      if(type==='HTML'){
       const figure={data:graph.data,layout:graph.layout};
       // Use the bundled Plotly script from the current offline report if available.
       const scripts=[...document.scripts];const bundled=scripts.find(s=>s.textContent.length>100000 && s.textContent.includes('Plotly'));
       if(!bundled)throw Error('Bundled Plotly JS not found');
       const page='<!doctype html><html><head><meta charset="utf-8"><title>'+stem+'</title></head><body><div id="chart" style="width:100%;height:90vh"></div><script>'+bundled.textContent.replace(/<\/script/gi,'<\\/script')+'<\/script><script>Plotly.newPlot("chart",'+JSON.stringify(figure).replace(/<\/script/gi,'<\\/script')+',{responsive:true});<\/script></body></html>';
       save(new Blob([page],{type:'text/html'}),stem+'.html');
      }else await Plotly.downloadImage(graph,{format:type.toLowerCase(),filename:stem,width:1200,height:700,scale:2});
     }catch(e){alert('Export failed: '+e.message)}
    });bar.appendChild(btn);
   });
const card = graph.closest('.card');

if (card) {
    card.appendChild(bar);
} else {
    graph.parentElement.insertBefore(bar, graph.nextSibling);
}
  });
 }
 setInterval(install,1500);install();
})();
</script>'''

def add_exports(path: Path):
    html = path.read_text(encoding='utf-8')
    if 'id="yt-monitor-export-tools"' in html:
        return
    if '</body>' not in html:
        raise ValueError(f'Missing closing body in {path}')
    path.write_text(html.replace('</body>', JS + '</body>'), encoding='utf-8')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('files', nargs='+', type=Path)
    args=p.parse_args()
    for file in args.files:
        add_exports(file)
        print(f'Added graph exports to {file}')
