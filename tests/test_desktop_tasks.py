"""Desktop command identity, local delivery and interrupted submission."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from task_relay.bridge import State
from task_relay.desktop_tasks import DesktopTaskError, enqueue, enqueue_create, enqueue_file, list_tasks, process_commands, process_creations, recover_commands, stop, task_detail
from task_relay.relay_paths import Paths


class DesktopTasksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root / 'app', root / 'data', root / 'workspaces', root / 'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        self.task_id = str(uuid.uuid4())
        with self.state.db:
            self.state.db.execute('INSERT INTO watched(id,path,offset,title,status,updated_at) VALUES (?,?,?,?,?,?)',
                                  (self.task_id, '', 0, 'Fixture task', 'idle', int(time.time())))
            self.state.db.execute('INSERT INTO backend_tasks(id,backend,session_id,cwd,model) VALUES (?,?,?,?,?)',
                                  (self.task_id, 'openai', 'fixture', str(root), 'fixture-model'))

    def source(self):
        return type('Source', (), {'state': self.state, 'config': {}, 'desktop_factory': None})()

    def ready(self):
        with self.state.db:
            self.state.put('health:desktop', {'interface_version': 1, 'last_success': time.time()})

    def test_duplicate_identity_queues_once_and_local_receipt_never_enters_telegram_outbox(self):
        self.ready()
        request_id = str(uuid.uuid4())
        first = enqueue(self.task_id, 'Continue fixture', request_id, self.paths)
        second = enqueue(self.task_id, 'Continue fixture', request_id, self.paths)
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(second['status'], 'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_commands').fetchone()[0], 1)
        with patch('task_relay.backends.api.prepare_run', return_value=None):
            process_commands(self.source())
        receipt = task_detail(self.task_id, self.paths)
        self.assertEqual(receipt['commands'][0]['status'], 'accepted')
        self.assertEqual(receipt['jobs'][0]['status'], 'queued')
        self.assertFalse(receipt['can_send'])
        self.assertTrue(receipt['can_stop'])
        self.assertEqual(receipt['events'][-1]['channel'], 'desktop')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE sent=0').fetchone()[0], 0)
        self.assertTrue(stop(self.task_id, self.paths)['changed'])
        self.assertEqual(self.state.db.execute('SELECT cancel FROM backend_jobs').fetchone()[0], 1)
        self.assertFalse(task_detail(self.task_id, self.paths)['can_stop'])
        again = enqueue(self.task_id, 'Continue fixture', request_id, self.paths)
        self.assertEqual(again['status'], 'accepted')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        self.assertEqual(list_tasks(self.paths)['tasks'][0]['title'], 'Fixture task')

    def test_old_service_or_changed_request_is_rejected_before_side_effect(self):
        request_id = str(uuid.uuid4())
        with self.assertRaises(DesktopTaskError):
            enqueue(self.task_id, 'Continue fixture', request_id, self.paths)
        self.ready()
        enqueue(self.task_id, 'Continue fixture', request_id, self.paths)
        with self.assertRaises(DesktopTaskError):
            enqueue(self.task_id, 'Changed text', request_id, self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_commands').fetchone()[0], 1)

    def test_interrupted_claim_becomes_uncertain_and_is_never_replayed(self):
        self.ready()
        request_id = str(uuid.uuid4())
        enqueue(self.task_id, 'Continue fixture', request_id, self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE desktop_commands SET status='submitting' WHERE request_id=?", (request_id,))
        self.assertEqual(recover_commands(self.state), 1)
        with patch('task_relay.backends.api.prepare_run', return_value=None):
            process_commands(self.source())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertEqual(enqueue(self.task_id, 'Continue fixture', request_id, self.paths)['status'], 'uncertain')

    def test_codex_instruction_uses_exact_task_and_keeps_receipt_local(self):
        class CodexFake:
            starts = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def ready_owner(self, task_id, on_open=None):
                return 'fixture-owner'

            def start(self, task_id, text, owner, **_):
                self.starts.append((task_id, text, owner))

        rollout = self.paths.data / 'rollout.jsonl'
        rollout.write_text(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_complete'}}) + '\n')
        with self.state.db:
            self.state.db.execute('DELETE FROM backend_tasks WHERE id=?', (self.task_id,))
            self.state.db.execute('UPDATE watched SET path=? WHERE id=?', (str(rollout), self.task_id))
        self.ready()
        enqueue(self.task_id, 'Continue Codex fixture', str(uuid.uuid4()), self.paths)
        source = self.source()
        source.desktop_factory = CodexFake
        process_commands(source)
        self.assertEqual(CodexFake.starts, [(self.task_id, 'Continue Codex fixture', 'fixture-owner')])
        detail = task_detail(self.task_id, self.paths)
        self.assertEqual(detail['commands'][0]['status'], 'accepted')
        self.assertEqual(detail['events'][-1]['channel'], 'desktop')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE sent=0').fetchone()[0], 0)

    def test_new_task_is_idempotent_and_does_not_change_telegram_selection(self):
        self.ready()
        with self.state.db:
            self.state.put('selected', 'telegram-selection')
            self.state.put('orchestrator_mode', True)
        request_id = str(uuid.uuid4())
        project = str(self.paths.data.parent)
        first = enqueue_create('openai', project, 'Desktop task', request_id, self.paths)
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(enqueue_create('openai', project, 'Desktop task', request_id, self.paths)['status'], 'queued')
        with self.assertRaises(DesktopTaskError):
            enqueue_create('openai', project, 'Different task', request_id, self.paths)
        with patch('task_relay.backends.api.read_config', return_value={'model': 'fixture-model'}):
            process_creations(self.source())
        created = enqueue_create('openai', project, 'Desktop task', request_id, self.paths)
        self.assertEqual(created['status'], 'accepted', created)
        self.assertEqual(self.state.get('selected'), 'telegram-selection')
        self.assertTrue(self.state.get('orchestrator_mode'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_creations').fetchone()[0], 1)
        self.assertEqual(list_tasks(self.paths)['creations'][0]['task_id'], created['task_id'])

    def test_new_task_rejection_is_recorded_without_partial_task(self):
        self.ready()
        request_id = str(uuid.uuid4())
        enqueue_create('openai', str(self.paths.data.parent), 'Unavailable provider', request_id, self.paths)
        with patch('task_relay.backends.api.read_config', return_value=None):
            process_creations(self.source())
        receipt = enqueue_create('openai', str(self.paths.data.parent), 'Unavailable provider', request_id, self.paths)
        self.assertEqual(receipt['status'], 'rejected')
        self.assertIsNone(receipt['task_id'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM watched').fetchone()[0], 1)

    def test_new_task_without_folder_gets_stable_isolated_workspace(self):
        self.ready()
        request_id = str(uuid.uuid4())
        first = enqueue_create('openai', '', '', request_id, self.paths)
        self.assertEqual(first['status'], 'queued')
        workspace = self.paths.workspaces / 'desktop-tasks' / request_id
        self.assertTrue(workspace.is_dir())
        queued = self.state.db.execute('SELECT cwd,title FROM desktop_creations WHERE request_id=?',
                                       (request_id,)).fetchone()
        self.assertEqual(queued['cwd'], str(workspace.resolve()))
        self.assertEqual(queued['title'], 'OpenAI task')
        self.assertEqual(enqueue_create('openai', '', '', request_id, self.paths)['status'], 'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_creations').fetchone()[0], 1)
        with patch('task_relay.backends.api.read_config', return_value={'model': 'fixture-model'}):
            process_creations(self.source())
        created = enqueue_create('openai', '', '', request_id, self.paths)
        self.assertEqual(created['status'], 'accepted')
        self.assertEqual(task_detail(created['task_id'], self.paths)['task']['project'], str(workspace.resolve()))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_new_task_workspace_cannot_follow_symlink_outside_root(self):
        self.ready()
        external = self.paths.data / 'outside'
        external.mkdir()
        self.paths.workspaces.mkdir()
        (self.paths.workspaces / 'desktop-tasks').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(DesktopTaskError, 'outside its configured folder'):
            enqueue_create('openai', '', '', str(uuid.uuid4()), self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_creations').fetchone()[0], 0)

    def test_selected_task_shows_current_permission_card(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES ('approval-job',?,1,'fixture','waiting',?)",
                                  (self.task_id, time.time()))
            self.state.db.execute("INSERT INTO tool_requests VALUES ('tool','approval-job',?,'Bash','{\"command\":\"echo ok\"}','pending',?)",
                                  (self.task_id, time.time() + 900))
        cards = task_detail(self.task_id, self.paths)['approvals']
        self.assertEqual(len(cards), 1)
        self.assertIn('echo ok', cards[0]['review'])

    def test_text_file_is_frozen_and_duplicate_identity_cannot_resend_changed_bytes(self):
        self.ready()
        selected = self.paths.data / 'brief.md'
        selected.write_text('Original brief\n')
        request_id = str(uuid.uuid4())
        first = enqueue_file(self.task_id, str(selected), 'Use this brief', request_id, self.paths)
        self.assertEqual(first['status'], 'queued')
        frozen = self.state.db.execute('SELECT prompt FROM desktop_commands WHERE request_id=?', (request_id,)).fetchone()[0]
        self.assertIn('Original brief', frozen)
        self.assertNotIn(str(self.paths.data), frozen)
        selected.write_text('Changed brief\n')
        again = enqueue_file(self.task_id, str(selected), 'Use this brief', request_id, self.paths)
        self.assertEqual(again['status'], 'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_commands').fetchone()[0], 1)
        with patch('task_relay.backends.api.prepare_run', return_value=None):
            process_commands(self.source())
        self.assertEqual(self.state.db.execute('SELECT prompt FROM backend_jobs').fetchone()[0], frozen)

    def test_text_file_limits_reject_before_queueing(self):
        self.ready()
        selected = self.paths.data / 'large.txt'
        selected.write_bytes(b'x' * 9001)
        with self.assertRaises(DesktopTaskError):
            enqueue_file(self.task_id, str(selected), '', str(uuid.uuid4()), self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_commands').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
