import json
import tempfile
import unittest
from pathlib import Path
from monitor_channel import command

class ConfigTest(unittest.TestCase):
    def test_five_unique_channels(self):
        channels=json.loads(Path('channels.json').read_text())['channels']
        self.assertEqual(len(channels),5)
        self.assertEqual(len({c['id'] for c in channels}),5)
        self.assertEqual(len({c['database'] for c in channels}),5)

    def test_preserves_stephen_database_path(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/'channels.json'
            cfg.write_text('{"channels":[{"id":"stephen","url":"https://example.com","database":"data/youtube_channel_monitor.sqlite3"}]}')
            args=command(cfg,'stephen')
            self.assertIn(
                str((Path(folder) / 'data/youtube_channel_monitor.sqlite3').resolve()),
                args
            )

if __name__=='__main__':unittest.main()
