import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish import REPORTS, publish


class PublishTests(unittest.TestCase):
    def test_missing_file_prevents_any_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch('publish.subprocess.run') as run:
            with self.assertRaises(ValueError):
                publish(Path(tmp), 'example-bucket', 'youtube-publisher', 'eu-west-2')
            run.assert_not_called()

    def test_homepage_uploaded_last(self):
        with tempfile.TemporaryDirectory() as tmp, patch('publish.subprocess.run') as run:
            for name in REPORTS:
                (Path(tmp) / name).write_text('<!doctype html><html></html>')
            publish(Path(tmp), 'example-bucket', 'youtube-publisher', 'eu-west-2')
            self.assertEqual(run.call_count, 7)
            self.assertEqual(run.call_args.args[0][run.call_args.args[0].index('--key') + 1], 'youtube_channel_report.html')
            self.assertTrue(all('--content-type' in call.args[0] for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
