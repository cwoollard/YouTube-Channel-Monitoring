#!/usr/bin/env python3
"""Start one existing monitor implementation from channels.json (no schema changes)."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def command(config: Path, channel_id: str) -> list[str]:
    base = config.resolve().parent
    channels = json.loads(config.read_text(encoding='utf-8'))['channels']
    matches = [c for c in channels if c['id'] == channel_id]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one channel named {channel_id!r}')
    c = matches[0]
    if not channel_id.isascii() or not channel_id.replace('_','').replace('-','').isalnum():
        raise ValueError('Unsafe channel identifier')
    db = Path(c['database'])
    if not db.is_absolute():
        db = base / db
    output = db.with_suffix('')
    thumb = base / 'thumbnails' / channel_id
    db.parent.mkdir(parents=True, exist_ok=True)
    thumb.mkdir(parents=True, exist_ok=True)
    return [sys.executable, str(base / 'youtube_channel_monitor_v3.py'), c['url'],
            '--db', str(db), '--output', str(output), '--thumbnail-dir', str(thumb),
            '--recent', str(int(c.get('recent',20))), '--interval', str(int(c.get('interval',3600))),
            '--delay', str(float(c.get('delay',2)))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('channel_id')
    parser.add_argument('--config', default=str(Path(__file__).with_name('channels.json')))
    parser.add_argument('--print-command', action='store_true')
    args = parser.parse_args()
    cmd = command(Path(args.config), args.channel_id)
    if args.print_command:
        print(' '.join(cmd))
        return
    raise SystemExit(subprocess.call(cmd))

if __name__ == '__main__':
    main()
