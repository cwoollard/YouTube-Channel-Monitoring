import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backup import snapshot
from restore import restore, verify_archive

class BackupTest(unittest.TestCase):
    def test_roundtrip_and_missing_db(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'data').mkdir()
            (root / 'thumbnails').mkdir()
            (root / 'thumbnails' / 'abc.img').write_bytes(b'old-thumbnail')
            db = root / 'data' / 'a.sqlite3'
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE observations(video_id TEXT)')
                c.execute("INSERT INTO observations VALUES ('x')")
            (root / 'channels.json').write_text(json.dumps({'channels': [{'id':'a','database':'data/a.sqlite3'}]}))
            archive = snapshot(root / 'channels.json', root / 'backups')
            verify_archive(archive)
            restored = root / 'restored'
            restore(archive, restored)
            self.assertEqual((restored / 'thumbnails' / 'abc.img').read_bytes(), b'old-thumbnail')
            with sqlite3.connect(restored / 'databases' / 'a.sqlite3') as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 1)
            with self.assertRaises(FileExistsError):
                restore(archive, restored)
            db.unlink()
            with self.assertRaises(FileNotFoundError):
                snapshot(root / 'channels.json', root / 'backups')

if __name__ == '__main__':
    unittest.main()
