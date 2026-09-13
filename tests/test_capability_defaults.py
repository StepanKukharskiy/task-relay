"""Small local settings/dispatch fixtures; no generation, account or messenger calls."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from task_relay import capability_defaults as defaults, credentials, gemini, api_providers as api
from task_relay.relay_paths import Paths
from task_relay.bridge import State


class Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.paths = Paths(root, root/'data', root/'work', root/'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        change = patch.object(gemini, 'DATA', self.paths.data)
        change.start(); self.addCleanup(change.stop)
        credentials.save(self.paths.data/'gemini.json', dict(api_key='fixture-secret', models={
            'text': 'gemini-text', 'image': 'gemini-image', 'video': 'veo-fixture'},
            catalog=['gemini-text', 'gemini-image', 'gemini-new-image', 'veo-fixture', 'veo-other']))
        credentials.save(self.paths.data/'openai.json', dict(api_key_ref={'source':'environment','name':'RELAY_FIXTURE_KEY'},
            model='text-fixture', catalog=['text-fixture', 'gpt-image-fixture'], image_catalog=['gpt-image-fixture']))
        env = patch.dict('os.environ', {'RELAY_FIXTURE_KEY': 'fixture-key'})
        env.start(); self.addCleanup(env.stop)

    def save(self, cap, provider, model, revision=None):
        return defaults.update(dict(revision=defaults.read(self.state.db)['revision'] if revision is None else revision,
                                    capability=cap, provider=provider, model=model), self.paths)

    def test_independent_defaults_reuse_credentials_and_existing_catalog(self):
        before = (self.paths.data/'openai.json').read_bytes()
        self.save('image', 'openai', 'gpt-image-fixture')
        self.save('video', 'gemini', 'veo-other')
        self.save('text', 'gemini', 'gemini-text')
        self.assertEqual((self.paths.data/'openai.json').read_bytes(), before)
        self.assertEqual(api.read_config('openai')['models']['image'], 'gpt-image-fixture')
        self.assertEqual(api.read_config('openai')['model'], 'text-fixture')
        self.assertEqual(gemini.read_config()['models']['video'], 'veo-other')
        from orchestrator.execution import catalog
        with patch('orchestrator.execution.importlib.util.find_spec', return_value=object()):
            row = next(x for x in catalog() if x['id'] == 'openai.image')
        self.assertEqual(row['configured_model'], 'gpt-image-fixture')
        self.assertTrue(row['available'])
        from task_relay.orchestrator_chat import provider
        self.assertEqual(provider(self.state), ('gemini', 'gemini-text'))
        safe = json.dumps(defaults.snapshot(self.paths))
        self.assertNotIn('fixture-secret', safe)
        self.assertNotIn('fixture-key', safe)
        self.assertNotIn('api_key', safe)

    def test_stale_window_and_unsupported_choices_leave_everything_unchanged(self):
        self.save('image', 'openai', 'gpt-image-fixture', 0)
        before = defaults.read(self.state.db)
        for cap, provider, model, revision in [('video','gemini','veo-other',0),
                ('video','openai','text-fixture',1), ('image','openai','text-fixture',1),
                ('image','qwen','image-fixture',1), ('3d','gemini','gemini-text',1)]:
            with self.assertRaises(ValueError): self.save(cap,provider,model,revision)
            self.assertEqual(defaults.read(self.state.db), before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_model_default_changes').fetchone()[0], 1)

    def test_video_queue_freezes_default_and_task_override_survives_settings_change(self):
        self.state.db.execute('INSERT INTO backend_tasks(id,backend,model,cwd,session_id) VALUES (?,?,?,?,?)',
                              ('fixture-task','gemini','gemini-text',str(self.paths.workspaces),'fixture-session'))
        self.state.db.commit()
        self.save('video','gemini','veo-fixture')
        first = gemini.prepare_run(self.state,'first','fixture-task','video')
        with self.state.db:
            self.state.db.execute('INSERT INTO gemini_runs(job_id,capability,model,response_path,options_json) VALUES (?,?,?,?,?)', first)
        self.save('video','gemini','veo-other')
        self.assertEqual(first[2], 'veo-fixture')
        self.assertEqual(self.state.db.execute("SELECT model FROM gemini_runs WHERE job_id='first'").fetchone()[0], 'veo-fixture')
        self.assertEqual(gemini.prepare_run(self.state,'second','fixture-task','video')[2], 'veo-other')
        with self.state.db:
            self.state.db.execute('INSERT INTO gemini_models VALUES (?,?,?)', ('fixture-task','video','veo-explicit'))
        self.assertEqual(gemini.prepare_run(self.state,'third','fixture-task','video')[2], 'veo-explicit')

    def test_selected_provider_disconnect_does_not_fall_back(self):
        self.save('text','openai','text-fixture')
        credentials.save(self.paths.data/'openai.json', {'enabled':False, 'api_key':'fixture'})
        from task_relay.orchestrator_chat import provider
        with self.assertRaises(ValueError): provider(self.state)
        row = next(x for x in defaults.snapshot(self.paths)['capabilities'] if x['capability']=='text')
        self.assertEqual(row['selected']['provider'], 'openai')
        self.assertFalse(row['selected_available'])

    def test_model_menu_update_and_chat_provider_change_share_preference(self):
        self.save('image','gemini','gemini-image')
        with self.state.db:
            self.assertTrue(defaults.update_selected(self.state.db,'image','gemini','gemini-new-image'))
        self.assertEqual(gemini.read_config()['models']['image'], 'gemini-new-image')
        self.save('text','openai','text-fixture')
        with self.state.db: defaults.clear_text(self.state.db, 'openai')
        self.assertEqual(defaults.read(self.state.db)['choices']['text']['model'], 'text-fixture')
        with self.state.db: defaults.clear_text(self.state.db)
        self.assertNotIn('text', defaults.read(self.state.db)['choices'])
        self.assertEqual(defaults.read(self.state.db)['choices']['image']['model'], 'gemini-new-image')

    def test_pending_provider_setup_blocks_save_and_failure_is_atomic(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO provider_jobs VALUES ('setup','gemini','refresh','queued',0)")
        with self.assertRaisesRegex(ValueError, 'Finish provider setup'):
            self.save('image','gemini','gemini-image')
        self.assertEqual(defaults.read(self.state.db)['revision'], 0)
        with self.state.db: self.state.db.execute('DELETE FROM provider_jobs')
        original = defaults.write
        def fail(db, value):
            original(db, value)
            raise ValueError('interrupted fixture')
        with patch.object(defaults, 'write', fail), self.assertRaisesRegex(ValueError,'interrupted'):
            self.save('text','openai','text-fixture')
        self.assertEqual(defaults.read(self.state.db)['revision'], 0)
        self.assertIsNone(self.state.get('orchestrator_provider'))

    def test_unknown_settings_version_is_preserved(self):
        self.save('image','gemini','gemini-image')
        with self.state.db:
            self.state.db.execute("UPDATE relay_model_defaults SET value=?", (json.dumps({'version':2,'revision':1,'choices':{}}),))
        with self.assertRaisesRegex(ValueError, 'preserved'): defaults.snapshot(self.paths)
        with self.assertRaisesRegex(ValueError, 'preserved'): self.save('image','gemini','gemini-image',1)
        self.assertEqual(json.loads(self.state.db.execute('SELECT value FROM relay_model_defaults').fetchone()[0])['version'],2)

    def test_implicit_image_action_cannot_ignore_other_provider_default(self):
        from task_relay.orchestrator_images import validate_selection
        action = {'kind':'generate_image','reference_ids':[]}
        snap = {'capabilities':{'model_defaults':{'image':{'provider':'openai','model':'gpt-image-fixture'}}}}
        with self.assertRaisesRegex(ValueError, 'no fallback'): validate_selection(action,snap)
        validate_selection({**action,'provider':'gemini'}, snap)
        validate_selection(action, {**snap, 'media_reply':{'task_id':'existing-gemini-image'}})

    def test_shared_status_keeps_frozen_models_uncertainty_and_review_state(self):
        from task_relay.generation_jobs import catalog
        with self.state.db:
            self.state.db.execute("INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES ('video-job','task',1,'Exact video request','uncertain',0)")
            self.state.db.execute("INSERT INTO gemini_runs(job_id,capability,model,stage,response_path,options_json) VALUES ('video-job','video','veo-frozen','submitting','fixture.json','{}')")
            self.state.db.execute("INSERT INTO production_attempts(id,run,task,assignment,state,frozen,session) VALUES ('image-attempt','run','image','assignment','completed',?,'{}')", (json.dumps({'execution':{'capability':'openai.image','parameters':{'model':'gpt-image-frozen'}}}),))
            self.state.db.execute("INSERT INTO production_tasks(run,id,assignment,status,latest) VALUES ('run','image','assignment','awaiting_user','image-attempt')")
            self.state.db.execute("INSERT INTO production_artifacts(id,run,task,attempt,path,blob,sha256,bytes,purpose,source) VALUES ('artifact','run','image','image-attempt','image.png','fixture','hash',3,'candidate','output')")
        self.save('video','gemini','veo-other')
        self.save('image','openai','gpt-image-fixture')
        before = self.state.db.total_changes
        jobs = catalog(self.state.db)['jobs']
        self.assertEqual(self.state.db.total_changes, before)
        self.assertEqual(jobs[0]['status'], 'uncertain')
        self.assertEqual(jobs[0]['model'], 'veo-frozen')
        self.assertEqual(jobs[0]['receipt_id'], 'video-job')
        self.assertEqual(jobs[1]['model'], 'gpt-image-frozen')
        self.assertEqual(jobs[1]['review_status'], 'awaiting_user')
        self.assertEqual(jobs[1]['artifacts'][0]['id'], 'artifact')


if __name__ == '__main__': unittest.main()
