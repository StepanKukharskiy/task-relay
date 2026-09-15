import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay import host_apps


class Tests(unittest.TestCase):
    def test_catalog_does_not_mutate_reused_detection_results(self):
        import json
        detected={'available':True,'major':8,'executable':'fixture-rhino'}
        with patch.object(host_apps,'rhino',return_value=detected):
            for _ in range(2):
                catalog=host_apps.catalog()
                self.assertEqual(json.loads(json.dumps(catalog))[1]['major'],8)
                self.assertNotIn('installed_versions',detected)
                self.assertNotIn('selection_note',detected)

    def test_rhino_inventory_keeps_both_versions_and_preference_does_not_launch(self):
        import plistlib
        from contextlib import nullcontext
        from task_relay import rhino_preferences as preferences
        from task_relay.relay_paths import Paths
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();paths=Paths(root,root/'data',root/'work',root/'generated')
            for major in (7,8):
                app=root/('Rhino '+str(major)+'.app')/'Contents'
                (app/'MacOS').mkdir(parents=True)
                executable=app/'MacOS/Rhinoceros';executable.write_text('fixture');executable.chmod(0o700)
                (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':str(major)+'.32'}))
            with patch.object(host_apps,'RHINO_APPLICATIONS',root),patch('sys.platform','darwin'),patch.dict(os.environ,{},clear=True),patch('subprocess.run',side_effect=AssertionError('Do not launch')),patch('task_relay.onboarding.setup_lock',side_effect=nullcontext):
                with patch.object(preferences,'preference',return_value='auto'):
                    row=host_apps.catalog()[1]
                    self.assertEqual(row['major'],8)
                    self.assertEqual([r['major'] for r in row['installed_versions']],[7,8])
                preferences.update({'major':'7'},paths)
                self.assertEqual(preferences.preference(paths),'7')
                with patch.object(preferences,'preference',return_value='7'):
                    self.assertEqual(host_apps.rhino()['major'],7)
                    self.assertEqual(host_apps.rhino()['interpreter'],'IronPython 2.7')
                before=(paths.data/'rhino-preference.json').read_bytes()
                with patch.dict(os.environ,{'TASK_RELAY_RHINO_VERSION':'8'}),self.assertRaises(ValueError):preferences.update({'major':'7'},paths)
                self.assertEqual((paths.data/'rhino-preference.json').read_bytes(),before)

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
        from task_relay.bridge import State
        from task_relay.production_control import queue_artifact_preview
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
