#!/usr/bin/env python3
"""Publish the seven generated YouTube reports to a private S3 origin."""
import argparse
import os
from pathlib import Path
import subprocess

REPORTS = (
    'channel-stephen.html', 'channel-paul.html', 'channel-honest.html',
    'channel-katie.html', 'channel-goodbloke.html',
    'channel-comparison.html', 'youtube_channel_report.html',
)


def publish(directory: Path, bucket: str, profile: str, region: str, dry_run: bool = False):
    if not bucket or '/' in bucket or bucket.startswith('s3:'):
        raise ValueError('Provide an S3 bucket name, not a URI')
    directory = directory.resolve()
    files = [directory / name for name in REPORTS]
    for path in files:
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise ValueError(f'Missing, empty, or symlinked report: {path}')
        with path.open('rb') as f:
            if b'<html' not in f.read(1024).lower() and b'<!doctype html' not in path.read_bytes()[:1024].lower():
                raise ValueError(f'Not an HTML report: {path}')
    print(f'Validated {len(files)} reports in {directory}', flush=True)
    for path in files:
        cmd = ['aws', 's3api', 'put-object', '--bucket', bucket, '--key', path.name,
               '--body', str(path), '--content-type', 'text/html; charset=utf-8',
               '--cache-control', 'public, max-age=60', '--profile', profile,
               '--region', region, '--output', 'json']
        if dry_run:
            print(f'Would publish {path.name}', flush=True)
        else:
            subprocess.run(cmd, check=True, timeout=180, stdout=subprocess.DEVNULL)
            print(f'Published {path.name}', flush=True)
    print('Publication complete' if not dry_run else 'Dry run complete', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, default=Path('reports'))
    parser.add_argument('--bucket', default=os.environ.get('YOUTUBE_PUBLIC_BUCKET'))
    parser.add_argument('--profile', default='youtube-publisher')
    parser.add_argument('--region', default='eu-west-2')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.bucket:
        parser.error('Set --bucket or YOUTUBE_PUBLIC_BUCKET')
    publish(args.reports, args.bucket, args.profile, args.region, args.dry_run)


if __name__ == '__main__':
    main()
