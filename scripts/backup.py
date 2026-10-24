#!/usr/bin/env python3
"""Consistent SQLite snapshots, optional S3 upload via installed AWS CLI."""
import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path


def backup(config: Path, destination: Path, s3_uri: str | None = None):
    base = config.resolve().parent
    destination.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    work = destination / f'.snapshot-{stamp}'
    work.mkdir(exist_ok=False)
    try:
        cfg = json.loads(config.read_text(encoding='utf-8'))
        shutil.copy2(config, work / 'channels.json')
        count = 0
        for channel in cfg['channels']:
            source = Path(channel['database'])
            if not source.is_absolute():
                source = base / source
            if not source.exists():
                continue
            target = work / f"{channel['id']}.sqlite3"
            with sqlite3.connect(f'file:{source.resolve()}?mode=ro', uri=True) as src:
                with sqlite3.connect(target) as dst:
                    src.backup(dst)
            with sqlite3.connect(target) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError(f'Integrity check failed for {channel["id"]}')
            count += 1
        if count == 0:
            raise RuntimeError('No databases found; refusing to produce empty backup')
        archive = destination / f'youtube-monitor-{stamp}.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for file in work.iterdir():
                tar.add(file, arcname=file.name)
        print(f'Created {archive} ({count} databases)')
        if s3_uri:
            if not s3_uri.startswith('s3://'):
                raise ValueError('S3 destination must start with s3://')
            subprocess.run(['aws', 's3', 'cp', str(archive), s3_uri.rstrip('/') + '/' + archive.name,
                            '--only-show-errors'], check=True)
            print('S3 upload complete')
        return archive
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='channels.json')
    p.add_argument('--dest', default='backups')
    p.add_argument('--s3-uri', help='Optional S3 URI; requires configured AWS CLI')
    a = p.parse_args()
    backup(Path(a.config), Path(a.dest), a.s3_uri)
