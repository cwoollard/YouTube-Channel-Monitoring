#!/usr/bin/env python3
"""Verify and safely restore backup archives into a new directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile
import tempfile
import shutil


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_checked(archive, target):
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        names = set()
        for member in members:
            name = member.name
            path = PurePosixPath(name)
            if (not member.isfile() or name in names or path.is_absolute()
                    or any(part in ('..', '.') for part in path.parts)
                    or '\\' in name or name.startswith('-')):
                raise ValueError(f'Unsafe archive entry: {name}')
            names.add(name)
        if 'manifest.json' not in names or 'channels.json' not in names:
            raise ValueError('Missing manifest or channel configuration')
        for member in members:
            dst = target.joinpath(*PurePosixPath(member.name).parts)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dst.open('xb') as out:
                shutil.copyfileobj(src, out)
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1:
        raise ValueError('Unsupported manifest format')
    expected = manifest['files']
    actual = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}
    if actual != set(expected) | {'manifest.json'}:
        raise ValueError('Unexpected or missing archive files')
    for name, metadata in expected.items():
        p = target / name
        if p.stat().st_size != metadata['size'] or digest(p) != metadata['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
    for channel, info in manifest['channels'].items():
        if info['status'] != 'ok':
            continue
        dbpath = target / 'databases' / f'{channel}.sqlite3'
        with sqlite3.connect(f'file:{dbpath.as_posix()}?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError(f'Database integrity failed: {channel}')
            n = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
            v = db.execute('SELECT COUNT(DISTINCT video_id) FROM observations').fetchone()[0]
            if n != info['observations'] or v != info['videos']:
                raise ValueError(f'Database counts mismatch: {channel}')
    return manifest


def verify_archive(archive):
    with tempfile.TemporaryDirectory(prefix='youtube-verify-') as d:
        return extract_checked(Path(archive), Path(d))


def restore(archive, output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite: {output}')
    # Verify fully before creating destination; copy only after validation.
    with tempfile.TemporaryDirectory(prefix='youtube-restore-') as d:
        tmp = Path(d)
        manifest = extract_checked(Path(archive), tmp)
        shutil.copytree(tmp, output)
    print(f'Restored and verified {output} ({len(manifest["channels"])} configured channels). Live data unchanged.')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('archive')
    p.add_argument('--output', help='Nonexistent directory for restore')
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args()
    if a.verify_only:
        verify_archive(a.archive)
        print('Archive checksums and SQLite integrity verified')
    elif a.output:
        restore(a.archive, a.output)
    else:
        p.error('Specify --output or --verify-only')


if __name__ == '__main__':
    main()
