#!/usr/bin/env python3
"""Generate independent channel reports plus a selector landing page.

Keeps the existing nginx root filename youtube_channel_report.html.
"""
import argparse
import html
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='channels.json')
    p.add_argument('--output-dir', default='reports')
    p.add_argument('--analyser', default='youtube_channel_analyser.py')
    p.add_argument('--max-videos', type=int, default=12)
    a = p.parse_args()
    base = Path(a.config).resolve().parent
    output = Path(a.output_dir)
    if not output.is_absolute():
        output = base / output
    output.mkdir(parents=True, exist_ok=True)
    analyser = Path(a.analyser)
    if not analyser.is_absolute():
        analyser = base / analyser
    channels = json.loads(Path(a.config).read_text(encoding='utf-8'))['channels']
    ids = set()
    available = []
    for channel in channels:
        cid = channel['id']
        if not cid.isascii() or not cid.replace('-', '').replace('_', '').isalnum() or cid in ids:
            raise ValueError('Invalid or duplicate channel id: ' + cid)
        ids.add(cid)
        db = Path(channel['database'])
        if not db.is_absolute():
            db = base / db
        target = output / f'channel-{cid}.html'
        if not db.is_file():
            print(f'Skipping {cid}: no database at {db}', flush=True)
            continue
        cmd = [sys.executable, str(analyser), '--db', str(db), '--output', str(target), '--max-videos', str(a.max_videos)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f'Could not generate {cid}: {exc}', file=sys.stderr, flush=True)
            continue
        subprocess.run([sys.executable, str(base / 'scripts' / 'add_exports.py'), str(target)], check=True)
        available.append((cid, channel['name'], target.name))
    if len(available) >= 2:
        comparison_cmd = [sys.executable, str(base / 'youtube_comparison_report.py'), '--config', str(Path(a.config).resolve()), '--output', str(output / 'channel-comparison.html')]
        try:
            subprocess.run(comparison_cmd, check=True)
            subprocess.run([sys.executable, str(base / 'scripts' / 'add_exports.py'), str(output / 'channel-comparison.html')], check=True)
            available.append(('comparison', 'Channel Comparisons', 'channel-comparison.html'))
        except subprocess.CalledProcessError as exc:
            print(f'Comparison report failed: {exc}', file=sys.stderr, flush=True)
    if not available:
        raise SystemExit('No reports available yet; no landing page replaced.')
    options = ''.join(f'<option value="{html.escape(filename, quote=True)}">{html.escape(name)}</option>' for _, name, filename in available)
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>YouTube Creator Reports</title>
<style>html,body{margin:0;height:100%;font:16px system-ui,-apple-system,sans-serif;background:#f4f7fb;color:#172337}header{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:12px max(16px,calc((100% - 1200px)/2));background:#172337;color:white}h1{font-size:20px;margin:0}label{font-weight:600}select{padding:9px;min-width:230px;max-width:95vw;border:1px solid #bac8db;border-radius:7px;font:inherit}iframe{display:block;width:100%;height:calc(100vh - 68px);border:0}small{opacity:.8}</style></head><body><header><h1>YouTube Creator Reports</h1><label for="channel">Creator</label><select id="channel">''' + options + '''</select><small>Independent reports and comparisons</small></header><iframe id="report" title="Creator analytics" loading="eager"></iframe>
<script>const picker=document.getElementById('channel'),frame=document.getElementById('report');const choices=Array.from(picker.options).map(x=>x.value);const requested=new URLSearchParams(location.search).get('channel');if(requested&&choices.includes('channel-'+requested+'.html'))picker.value='channel-'+requested+'.html';function show(){frame.src=picker.value;const id=picker.value.slice(8,-5);history.replaceState(null,'','?channel='+encodeURIComponent(id));}picker.addEventListener('change',show);show();</script></body></html>'''
    dest = output / 'youtube_channel_report.html'
    tmp = output / '.youtube_channel_report.tmp'
    tmp.write_text(page, encoding='utf-8')
    os.replace(tmp, dest)
    print(f'Updated {dest} with {len(available)} channel choices', flush=True)


if __name__ == '__main__':
    main()
