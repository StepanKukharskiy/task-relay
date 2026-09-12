import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import host_apps


class Tests(unittest.TestCase):
    def test_encoder_discovery_and_bad_override_do_not_launch_or_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'encoder';p.write_text('fixture');p.chmod(0o700)
            with patch('subprocess.run',side_effect=AssertionError('Discovery must not launch')):
                self.assertTrue(host_apps.video_tools({},lambda _:str(p))['available'])
                self.assertFalse(host_apps.video_tools({'TASK_RELAY_FFMPEG':'/missing'},lambda _:str(p))['available'])

    def test_explicit_missing_override_does_not_fall_back(self):
        result=host_apps.blender({'TASK_RELAY_BLENDER':'/missing/blender'},'darwin',lambda _: '/Applications/Blender.app/Contents/MacOS/Blender')
        self.assertFalse(result['available']);self.assertIn('TASK_RELAY_BLENDER',result['blocker'])

    def test_executable_discovery_does_not_launch_or_assume_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'blender';p.write_text('fixture');p.chmod(0o700)
            with patch('subprocess.run',side_effect=AssertionError('Discovery must not launch')):
                result=host_apps.blender({},'linux',lambda _:str(p))
            self.assertTrue(result['available']);self.assertEqual(result['executable'],str(p.resolve()))
            self.assertIn('presence only',result['evidence'])

    def test_production_image_preview_and_original_delivery_are_distinct(self):
        from bridge import State
        from production_control import queue_artifact_preview
        with tempfile.TemporaryDirectory() as tmp:
            state=State(Path(tmp)/'state.sqlite');p=Path(tmp)/'blob';p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'fixture')
            artifact={'id':'art','blob':str(p)}
            with state.db:
                queue_artifact_preview(state,'event',artifact,'preview.png','Tower')
                queue_artifact_preview(state,'event',artifact,'preview.png','Tower')
                queue_artifact_preview(state,'event',{'id':'native','blob':str(p)},'tower.blend','Tower')
            rows=state.db.execute('select id,kind from media_outbox').fetchall()
            self.assertEqual([tuple(r) for r in rows],[('production-preview:art','preview')])
            p.write_bytes(b'\x00\x00\x00\x20ftypisom'+b'fixture')
            with state.db:
                queue_artifact_preview(state,'event',{'id':'clip','blob':str(p)},'animation.mp4','Tower')
                queue_artifact_preview(state,'event',{'id':'clip','blob':str(p)},'animation.mp4','Tower')
            self.assertEqual(state.db.execute("select kind from media_outbox where id='production-preview:clip'").fetchone()[0],'video')
            self.assertEqual(state.db.execute('select count(*) from media_outbox').fetchone()[0],2)
            state.db.close()
