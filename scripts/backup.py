#!/usr/bin/env python3
"""Consistent, verifiable YouTube Monitor backups (Python standard library)."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot(config, destination, thumbnail_dir=None, tier='daily', s3_uri=None,
             profile=None, retain_local=7, allow_missing=None):
    config = Path(config).resolve()
    root = config.parent
    destination = Path(destination).resolve()
    thumbnail_dir = Path(thumbnail_dir).resolve() if thumbnail_dir else root / 'thumbnails'
    destination.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(config.read_text(encoding='utf-8'))
    channels = cfg['channels']
    ids = [ch['id'] for ch in channels]
    if len(ids) != len(set(ids)) or any('/' in x or '\\' in x or x in ('.', '..') for x in ids):
        raise ValueError('Channel IDs must be unique safe filenames')
    allow_missing = set(allow_missing or [])
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    archive = destination / f'youtube-monitor-{tier}-{stamp}.tar.gz'
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=destination) as tmp:
        work = Path(tmp)
        (work / 'databases').mkdir()
        shutil.copy2(config, work / 'channels.json')
        stats = {}
        for ch in channels:
            source = Path(ch['database'])
            if not source.is_absolute():
                source = root / source
            if not source.is_file():
                if ch['id'] in allow_missing:
                    stats[ch['id']] = {'status': 'explicitly-allowed-missing'}
                    continue
                raise FileNotFoundError(f'Missing configured database for {ch["id"]}: {source}')
            target = work / 'databases' / (ch['id'] + '.sqlite3')
            # Read-only connection to live DB; SQLite backup API handles WAL safely.
            with sqlite3.connect(f'file:{source.resolve().as_posix()}?mode=ro', uri=True) as src:
                dst = sqlite3.connect(target)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            with sqlite3.connect(target) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError(f'Integrity check failed: {ch["id"]}')
                observations = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
                videos = db.execute('SELECT COUNT(DISTINCT video_id) FROM observations').fetchone()[0]
            stats[ch['id']] = {'status': 'ok', 'observations': observations, 'videos': videos}
        if not any(v['status'] == 'ok' for v in stats.values()):
            raise RuntimeError('No databases backed up')
        if not thumbnail_dir.is_dir():
            raise FileNotFoundError(f'Thumbnail directory missing: {thumbnail_dir}')
        # Copy immutable historical thumbnails into snapshot; reject symlinks to avoid leaking other files.
        for folder, dirs, files in os.walk(thumbnail_dir):
            rel = Path(folder).relative_to(thumbnail_dir)
            dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
            for name in files:
                src = Path(folder) / name
                if src.is_symlink() or not src.is_file():
                    raise ValueError(f'Unsafe thumbnail: {src}')
                dst = work / 'thumbnails' / rel / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        (work / 'thumbnails').mkdir(exist_ok=True)
        files = {}
        for file in sorted(work.rglob('*')):
            if file.is_file():
                files[file.relative_to(work).as_posix()] = {'sha256': sha256(file), 'size': file.stat().st_size}
        manifest = {'format': 1, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'tier': tier, 'channels': stats, 'files': files}
        (work / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        # Archive is created outside snapshot dir and renamed only after successful close.
        fd, tempname = tempfile.mkstemp(prefix='.archive-', suffix='.tar.gz', dir=destination)
        os.close(fd)
        try:
            with tarfile.open(tempname, 'w:gz') as tar:
                for file in sorted(work.rglob('*')):
                    if file.is_file():
                        tar.add(file, arcname=file.relative_to(work).as_posix(), recursive=False)
            from restore import verify_archive
            verify_archive(Path(tempname))
            os.replace(tempname, archive)
        finally:
            if os.path.exists(tempname):
                os.unlink(tempname)
    print(f'Created and verified {archive} ({len([v for v in stats.values() if v["status"] == "ok"])} databases)')
    if s3_uri:
        if not s3_uri.startswith('s3://'):
            raise ValueError('S3 URI must start with s3://')
        cmd = ['aws', 's3', 'cp', str(archive), s3_uri.rstrip('/') + '/' + archive.name, '--only-show-errors']
        if profile:
            cmd += ['--profile', profile]
        subprocess.run(cmd, check=True)
        print('S3 upload complete')
    # Local retention applies to archives for this tier only, and only after success.
    if retain_local is not None:
        cutoff = dt.datetime.now().timestamp() - retain_local * 86400
        for old in destination.glob(f'youtube-monitor-{tier}-*.tar.gz'):
            if old != archive and old.stat().st_mtime < cutoff:
                old.unlink()
    return archive


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='channels.json')
    p.add_argument('--dest', default='backups')
    p.add_argument('--thumbnail-dir')
    p.add_argument('--tier', choices=['daily', 'weekly', 'monthly'], default='daily')
    p.add_argument('--s3-uri')
    p.add_argument('--profile')
    p.add_argument('--retain-local-days', type=int, default=7)
    p.add_argument('--allow-missing', action='append', default=[], metavar='CHANNEL_ID')
    a = p.parse_args()
    snapshot(a.config, a.dest, a.thumbnail_dir, a.tier, a.s3_uri, a.profile,
             a.retain_local_days, a.allow_missing)


if __name__ == '__main__':
    main()
