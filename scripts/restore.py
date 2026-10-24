#!/usr/bin/env python3
"""Extract a backup into a NEW directory; never overwrite live data."""
import argparse
import sqlite3
import tarfile
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('archive')
    p.add_argument('--output', required=True, help='Must be a nonexistent directory')
    a = p.parse_args()
    target = Path(a.output).resolve()
    if target.exists():
        raise SystemExit('Refusing to overwrite an existing restore destination')
    with tarfile.open(a.archive, 'r:gz') as tar:
        members = tar.getmembers()
        if any(not m.isfile() or '/' in m.name or '\\' in m.name or m.name.startswith('.') for m in members):
            raise SystemExit('Unsafe archive member')
        target.mkdir(parents=True)
        for m in members:
            with tar.extractfile(m) as src, (target / m.name).open('wb') as dst:
                import shutil
                shutil.copyfileobj(src, dst)
    for db in target.glob('*.sqlite3'):
        with sqlite3.connect(db) as conn:
            assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    print(f'Restored and checked files in {target}. Live databases unchanged.')

if __name__ == '__main__':
    main()
