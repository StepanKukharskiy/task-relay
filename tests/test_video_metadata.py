import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from bridge import Telegram
from media import video_metadata


class Tests(unittest.TestCase):
    def probe(self, stream, duration='65.0'):
        response = Mock(stdout=json.dumps({'streams': [stream], 'format': {'duration': duration}}).encode())
        with patch('shutil.which', return_value='/fixture/ffprobe'), patch('subprocess.run', return_value=response) as run:
            result = video_metadata('/tmp/portrait.mp4')
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertIn('file', run.call_args.args[0])
        return result

    def test_portrait_and_landscape_keep_distinct_dimensions(self):
        self.assertEqual(self.probe({'width': 1080, 'height': 1920, 'sample_aspect_ratio': '1:1'}), {'width': 1080, 'height': 1920, 'duration': 65})
        self.assertEqual(self.probe({'width': 1920, 'height': 1080}), {'width': 1920, 'height': 1080, 'duration': 65})

    def test_display_rotation_takes_precedence_over_stale_tag(self):
        meta = self.probe({'width': 1920, 'height': 1080, 'tags': {'rotate': '0'}, 'side_data_list': [{'rotation': -90}]})
        self.assertEqual((meta['width'], meta['height']), (1080, 1920))

    def test_non_square_pixels_use_display_width(self):
        meta = self.probe({'width': 720, 'height': 576, 'sample_aspect_ratio': '16:15'})
        self.assertEqual((meta['width'], meta['height']), (768, 576))

    def test_probe_failure_and_invalid_dimensions_do_not_guess(self):
        for error in (subprocess.TimeoutExpired('ffprobe', 5), FileNotFoundError()):
            with patch('shutil.which', return_value='/fixture/ffprobe'), patch('subprocess.run', side_effect=error):
                self.assertEqual(video_metadata('/tmp/unknown.mp4'), {})
        self.assertEqual(self.probe({'width': 0, 'height': 1080}), {})
        self.assertEqual(self.probe({'width': 1920, 'height': 1080, 'tags': {'rotate': '45'}}), {})

    def test_upload_sends_dimensions_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'portrait.mp4'
            original = b'0000ftypisomUNCHANGED'
            path.write_bytes(original)
            telegram = Telegram('test')
            with patch('bridge.video_metadata', return_value={'width': 1080, 'height': 1920, 'duration': 65}), patch.object(telegram, 'request', return_value={}) as request:
                telegram.send_media(1, path, path.name, 'video', 'Portrait')
            method, body, _ = request.call_args.args
            self.assertEqual(method, 'sendVideo')
            self.assertIn(b'name="width"\r\n\r\n1080\r\n', body)
            self.assertIn(b'name="height"\r\n\r\n1920\r\n', body)
            self.assertIn(b'name="duration"\r\n\r\n65\r\n', body)
            self.assertIn(original, body)
            self.assertEqual(path.read_bytes(), original)

    def test_unreadable_dimensions_use_original_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'unknown.mp4'
            path.write_bytes(b'unknown')
            telegram = Telegram('test')
            with patch('bridge.video_metadata', return_value={}), patch.object(telegram, 'request', return_value={}) as request:
                telegram.send_media(1, path, path.name, 'video', 'Unknown')
            self.assertEqual(request.call_args.args[0], 'sendDocument')
            self.assertIn(b'name="document"', request.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
