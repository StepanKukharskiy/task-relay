"""Controlled browser work/Skill/source/recovery tests; no real account/provider."""
import io
import json
from pathlib import Path
import struct
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

from task_relay import browser_capture as bc, browser_native as native, work_state as ws
from task_relay.host_browser_capture import install


def capture(text='We will compare Brazil competitors. Check local-language pricing sources.', **extra):
    return {'source_type': 'conversation', 'url': 'https://chatgpt.com/c/controlled', 'title': 'Competition',
            'extracted_content': text, 'source_metadata': {'captured_at': '2026-10-02T12:00:00Z',
            'adapter': 'chatgpt', 'limitations': ['Only loaded text was captured.']}, **extra}


def answer():
    return {'skill_candidates': [{'files': [{'path': 'SKILL.md', 'content': '---\nname: competitor-research\ndescription: Research country competitors\n---\n\nCheck local-language primary sources.\n'}], 'base_sha256': None}],
            'work_changes': [{'title': 'Competition / Brazil', 'objective': 'Compare Brazil competitors', 'status': 'in_progress',
                'conclusions': [{'text': 'Country scope is Brazil', 'quote': 'compare Brazil competitors'}],
                'decision_proposals': [{'text': 'Research Brazil first', 'quote': 'compare Brazil competitors'}],
                'questions': [{'text': 'Which companies?', 'quote': None}],
                'next_actions': [{'text': 'Check local-language pricing', 'quote': 'Check local-language pricing sources.'}],
                'artifact_references': [], 'dependencies': []}]}


class BrowserCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.folder = Path(self.temp.name).resolve()
        self.db = ws.connect(self.folder / 'state.sqlite'); bc.initialize(self.db)
    def tearDown(self): self.db.close(); self.temp.cleanup()
    def save_work(self):
        result = bc.relay_analyze_capture(self.db, capture(), answer=answer())
        return bc.save(self.db, capture(), 'work', result['work_changes'][0], 'Keep Brazil work', 'fixture:work', confirmed=True)
    def test_artifact_reference_accepts_exact_source_url_without_inventing_links(self):
        source = bc.capture(capture())
        self.assertNotIn(source['url'], source['content'])
        data = answer()
        data['work_changes'][0]['artifact_references'] = [{'label': 'Captured conversation', 'url': source['url']}]
        reviewed = bc.candidates(source, data)
        self.assertEqual(reviewed['work_changes'][0]['artifact_references'][0]['url'], source['url'])
        for missing in (source['url'] + '?invented=true', 'https://files.example.test/uncaptured'):
            with self.subTest(url=missing):
                data['work_changes'][0]['artifact_references'][0]['url'] = missing
                with self.assertRaisesRegex(ValueError, 'not captured'):
                    bc.candidates(source, data)
        for unsafe in ('javascript:alert(1)', 'https://user:pass@example.test/artifact'):
            with self.subTest(url=unsafe):
                data['work_changes'][0]['artifact_references'][0]['url'] = unsafe
                with self.assertRaisesRegex(ValueError, 'http'):
                    bc.candidates({**source, 'content': source['content'] + ' ' + unsafe}, data)

    def test_cross_site_state_and_new_chat_continuation(self):
        proposal = bc.relay_analyze_capture(self.db, capture(), answer=answer())
        self.assertEqual(bc.library(self.db), {'work': [], 'skills': [], 'sources': []})
        receipt = self.save_work(); pid = receipt['work_id']
        selected = capture('Brazil pricing is listed at 20 BRL.', optional_work_id=pid)
        selected.update(source_type='selection', url='https://pricing.example.test/br', title='Brazil pricing', selected_content=selected.pop('extracted_content'))
        source_receipt = bc.save(self.db, selected, 'source', None, 'Keep selected Brazil pricing', 'fixture:source', confirmed=True, base_revision=receipt['revision'])
        state = bc.bounded_work(self.db, pid)
        self.assertEqual(state['browser_state']['questions'][0]['text'], 'Which companies?')
        self.assertEqual(state['sources'][0]['url'], selected['url'])
        exact = json.loads(self.db.execute('SELECT source_json FROM browser_sources').fetchone()[0])
        self.assertEqual(exact['content'], selected['selected_content'])
        self.assertEqual(ws.snapshot(self.db, pid)['decisions'], [])
        self.assertEqual(len(ws.snapshot(self.db, pid)['proposals']), 1)
        skill_receipt = bc.save(self.db, capture(), 'skill', proposal['skill_candidates'][0], 'Keep method', 'fixture:skill', confirmed=True)
        original = json.loads(self.db.execute('SELECT original FROM browser_receipts WHERE key=?', ('fixture:skill',)).fetchone()[0])
        self.assertEqual(original['request'], 'Keep method')
        self.assertEqual(original['capture']['content'], capture()['extracted_content'])
        projected = bc.project_skill(self.db, skill_receipt, self.folder)
        self.assertTrue((Path(projected['path']) / 'SKILL.md').is_file())
        self.db.close(); self.db = ws.connect(self.folder / 'state.sqlite')
        context = bc.continue_work(self.db, pid, 'Prepare the report', 'competitor-research')['context']
        packet = json.loads(context)
        self.assertEqual(packet['work']['project']['revision'], source_receipt['revision'])
        self.assertEqual(packet['skill']['name'], 'competitor-research')
        self.assertIn('never tool authorization', context)
        self.assertIn('20 BRL', context)  # Relevant captured evidence, without the original chat.
    def test_atomic_failure_does_not_leave_partial_work(self):
        before = ws.append
        def broken(db, pid, kind, *args, **kwargs):
            if kind == 'decision': raise ValueError('controlled write interruption')
            return before(db, pid, kind, *args, **kwargs)
        with patch.object(ws, 'append', side_effect=broken), self.assertRaisesRegex(ValueError, 'controlled'):
            self.save_work()
        self.assertEqual(self.db.execute('SELECT count(*) FROM work_projects').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM browser_receipts').fetchone()[0], 0)
    def test_lost_reply_replays_only_exact_committed_save(self):
        first = self.save_work(); count = len(ws.records(self.db, first['work_id']))
        self.assertEqual(first, self.save_work()); self.assertEqual(count, len(ws.records(self.db, first['work_id'])))
        changed = answer()['work_changes'][0]; changed['title'] = 'Different'
        with self.assertRaisesRegex(ValueError, 'different reviewed'):
            bc.save(self.db, capture(), 'work', changed, 'Keep Brazil work', 'fixture:work', confirmed=True)
    def test_stale_update_fails_and_preserves_source_and_old_version(self):
        receipt = self.save_work(); pid = receipt['work_id']; value = capture(optional_work_id=pid)
        bc.save(self.db, value, 'source', None, 'Keep source', 'fixture:source', confirmed=True, base_revision=receipt['revision'])
        with self.assertRaisesRegex(ValueError, 'Work changed'):
            bc.save(self.db, value, 'work', answer()['work_changes'][0], 'Update', 'fixture:update', confirmed=True, base_revision=receipt['revision'])
        self.assertEqual(len(bc.library(self.db)['sources']), 1)
        self.assertEqual(len(bc.bounded_work(self.db, pid)['capture_history']), 1)
    def test_uncited_proposal_and_unselected_skill_update_rejected(self):
        data = answer(); data['work_changes'][0]['conclusions'][0]['quote'] = 'Invented citation'
        with self.assertRaisesRegex(ValueError, 'absent'): bc.relay_analyze_capture(self.db, capture(), answer=data)
        data = answer(); proposal = bc.relay_analyze_capture(self.db, capture(), answer=data)
        bc.save(self.db, capture(), 'skill', proposal['skill_candidates'][0], 'Keep', 'fixture:skill', confirmed=True)
        data['skill_candidates'][0]['files'][0]['content'] += '\nCheck currency.\n'
        with self.assertRaisesRegex(ValueError, 'Select it explicitly'):
            bc.save(self.db, capture(), 'skill', bc.relay_analyze_capture(self.db, capture(), answer=data)['skill_candidates'][0], 'Improve', 'fixture:change', confirmed=True)
    def test_reviewed_skill_improvement_retains_both_versions(self):
        first = bc.relay_analyze_capture(self.db, capture(), answer=answer())['skill_candidates'][0]
        bc.save(self.db, capture(), 'skill', first, 'Keep', 'fixture:skill', confirmed=True)
        improved = answer(); improved['skill_candidates'][0]['files'][0]['content'] += '\nCheck currency.\n'
        improved['skill_candidates'][0]['base_sha256'] = first['sha256']
        value = capture(optional_skill_name=first['name'])
        second = bc.relay_analyze_capture(self.db, value, answer=improved)['skill_candidates'][0]
        bc.save(self.db, value, 'skill', second, 'Improve reusable method', 'fixture:improve', confirmed=True)
        self.assertEqual(self.db.execute('SELECT count(*) FROM browser_skill_versions').fetchone()[0], 2)
        with self.assertRaisesRegex(ValueError, 'Skill changed'):
            bc.save(self.db, value, 'skill', first | {'base_sha256': first['sha256']}, 'Old base', 'fixture:stale-skill', confirmed=True)
    def test_no_provider_source_path_and_no_automatic_call(self):
        with patch('task_relay.gemini.read_config', return_value=None), patch('task_relay.internal_jobs.run') as run:
            result = bc.relay_analyze_capture(self.db, capture(), request_key='fixture:analysis')
            self.assertIn('analysis_prompt', result); run.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'explicit Save'):
            bc.save(self.db, capture(), 'source', None, 'Keep', 'fixture:source', confirmed=False)
    def test_completed_analysis_recovery_does_not_call_provider_twice(self):
        class Client:
            calls = 0
            def request(self, *args, **kwargs):
                self.calls += 1
                return {'candidates': [{'content': {'parts': [{'text': json.dumps(answer())}]}}]}
        client = Client()
        with patch('task_relay.gemini.read_config', return_value=None):
            first = bc.relay_analyze_capture(self.db, capture(), request_key='fixture:analysis', client=client)
            second = bc.relay_analyze_capture(self.db, capture(), request_key='fixture:analysis', client=client)
        self.assertEqual(first, second); self.assertEqual(client.calls, 1)
        self.db.execute("UPDATE internal_jobs SET status='sending'"); self.db.commit()
        with patch('task_relay.gemini.read_config', return_value=None), self.assertRaisesRegex(ValueError, 'no submission.*repeated'):
            bc.relay_analyze_capture(self.db, capture(), request_key='fixture:analysis', client=client)
        self.assertEqual(client.calls, 1)
    def test_skill_projection_failure_recovers_without_duplicate_save(self):
        proposal = bc.relay_analyze_capture(self.db, capture(), answer=answer())['skill_candidates'][0]
        message = {'action': 'save', 'capture': capture(), 'kind': 'skill', 'candidate': proposal, 'request': 'Keep method', 'request_key': 'fixture:skill', 'confirmed': True}
        with patch.object(bc.FILES, 'write', side_effect=OSError('controlled projection interruption')):
            first = native.dispatch(self.db, self.folder, message)
        self.assertEqual(first['projection'], 'pending')
        second = native.dispatch(self.db, self.folder, message)
        self.assertEqual(second['projection'], 'complete')
        self.assertEqual(self.db.execute('SELECT count(*) FROM browser_skill_versions').fetchone()[0], 1)
    def test_native_limits_and_narrow_actions(self):
        stream = io.BytesIO(); native.write_message(stream, {'text': 'Бразилия'}); stream.seek(0)
        self.assertEqual(native.read_message(stream)['text'], 'Бразилия')
        with self.assertRaisesRegex(ValueError, 'budget'):
            native.read_message(io.BytesIO(struct.pack('=I', native.MAX_MESSAGE + 1)))
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            native.dispatch(self.db, self.folder, {'action': 'desktop-dispatch'})
    def test_registration_scopes_origin_and_quotes_paths(self):
        extension_id = 'a' * 32
        runtime = Path(__file__).resolve().parents[1]
        registration = self.folder / 'NativeMessagingHosts'
        result = install(extension_id, self.folder / 'test data', runtime, __import__('sys').executable, registration=registration)
        manifest = json.loads(Path(result['manifest']).read_text())
        self.assertEqual(manifest['allowed_origins'], ['chrome-extension://' + extension_id + '/'])
        self.assertIn('"$1"', Path(manifest['path']).read_text())
        with self.assertRaises(ValueError): install('*', self.folder, runtime, __import__('sys').executable, registration=registration)
    def test_native_process_framing_and_caller_gate(self):
        ident = 'a' * 32; origin = 'chrome-extension://' + ident + '/'
        command = [sys.executable, '-m', 'task_relay.browser_native', origin, '--extension-id', ident, '--data-dir', str(self.folder)]
        incoming = io.BytesIO(); native.write_message(incoming, {'action': 'status'}); native.write_message(incoming, {'action': 'library'})
        result = subprocess.run(command, input=incoming.getvalue(), capture_output=True, check=True)
        replies = io.BytesIO(result.stdout)
        self.assertTrue(native.read_message(replies)['result']['connected'])
        self.assertEqual(native.read_message(replies)['result'], {'work': [], 'skills': [], 'sources': []})
        command[3] = 'chrome-extension://' + 'b' * 32 + '/'
        rejected = subprocess.run(command, input=incoming.getvalue(), capture_output=True)
        self.assertNotEqual(rejected.returncode, 0); self.assertEqual(rejected.stdout, b'')


if __name__ == '__main__': unittest.main()
