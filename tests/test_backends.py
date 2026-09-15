import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import types
import unittest
from unittest.mock import patch, Mock

from task_relay.bridge import Bridge, State
from task_relay import backends
from task_relay import claude_runner
from tests.test_bridge import TelegramFake, DesktopFake


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'state.sqlite')
        with self.state.db:
            self.state.put('user_id', 123)
            self.state.put('chat_id', 123)
        self.telegram = TelegramFake()
        self.bridge = Bridge(self.state, self.telegram, {}, DesktopFake)
        self.config = patch('task_relay.backends.claude_config', return_value={'auth': 'account', 'model': 'sonnet'})
        self.config.start()
        self.python = patch('task_relay.backends.CLAUDE_PYTHON', Path(__file__))
        self.python.start()
        self.uid = 1

    def tearDown(self):
        self.config.stop()
        self.python.stop()
        self.state.db.close()
        self.temp.cleanup()

    def send(self, text, user=123, reply='task', uid=None):
        self.uid += 1
        message = {'chat': {'id': user, 'type': 'private'}, 'from': {'id': user}, 'text': text}
        # These provider-execution fixtures continue their task by explicit reply.
        # Pass reply=None to exercise a fresh orchestrator message instead.
        if reply == 'task':
            row = self.state.db.execute('SELECT message_id FROM messages WHERE thread_id=? ORDER BY message_id DESC LIMIT 1',
                                        (self.state.get('selected'),)).fetchone() if not text.startswith('/') else None
            reply = row[0] if row else None
        if reply is not None:
            message['reply_to_message'] = {'message_id': reply}
        self.bridge.process({'update_id': uid or self.uid, 'message': message})

    def create(self):
        self.send(f'/new claude "{self.root}" Review project')
        return self.state.get('selected')

    def queued(self):
        tid = self.create()
        self.send('Implement the next step')
        return tid, self.state.db.execute('SELECT * FROM backend_jobs').fetchone()

    def test_new_task_selection_emoji_and_duplicate_creation(self):
        self.send(f'/new claude "{self.root}" My task', uid=8)
        tid = self.state.get('selected')
        self.send(f'/new claude "{self.root}" My task', uid=8)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)
        self.assertTrue(tid.startswith('claude:'))
        self.assertIn(self.state.emoji(tid), self.telegram.sent[-1][1])
        self.assertEqual(backends.task(self.state, tid)['cwd'], str(self.root.resolve()))

    def test_provider_creation_does_not_capture_new_orchestrator_requests(self):
        self.create()
        with patch('task_relay.orchestrator_chat.provider',return_value=('gemini','fixture')):
            self.send('Start a separate Codex research task',reply=None)
        self.assertEqual(self.state.db.execute('SELECT prompt FROM orchestrator_chats').fetchone()[0],
                         'Start a separate Codex research task')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)

    def test_claude_shortcut_keeps_session_and_rejects_busy_task(self):
        tid = self.create()
        self.send('/claude Read README.md')
        self.send('/claude A second instruction')
        jobs = self.state.db.execute('SELECT * FROM backend_jobs').fetchall()
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]['thread_id'], jobs[0]['prompt']), (tid, 'Read README.md'))
        self.assertIn('busy', self.telegram.sent[-1][1])

    def test_unpaired_user_and_invalid_folders_cannot_create(self):
        self.send(f'/new claude "{self.root}"', user=456)
        self.send('/new claude relative/folder')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 0)

    def test_queue_deduplicates_and_rejects_concurrent_turns(self):
        tid = self.create()
        self.send('First', uid=80)
        self.send('First', uid=80)
        self.send('Second')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM watched WHERE id=?', (tid,)).fetchone()[0], 'queued')

    def test_reply_routing_ignores_selected_task(self):
        first = self.create()
        reply = len(self.telegram.sent)
        self.create()
        self.send('For first task', reply=reply)
        self.assertEqual(self.state.db.execute('SELECT thread_id FROM backend_jobs').fetchone()[0], first)

    def test_unknown_reply_never_uses_selected_claude_task(self):
        self.create()
        self.send('Do work', reply=999)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_claude_status_does_not_connect_to_codex(self):
        self.create()
        with patch.object(DesktopFake, '__enter__', side_effect=AssertionError('Codex should not be used')):
            self.send('/status')
        self.assertIn('Claude: idle', self.telegram.sent[-1][1])
        self.send('/tasks')
        self.bridge.flush()
        self.assertIn('Claude · idle', self.telegram.sent[-1][1])

    def test_model_change_persists_only_when_idle(self):
        tid = self.create()
        self.send('/model opus')
        self.assertEqual(backends.task(self.state, tid)['model'], 'opus')
        self.send('Start')
        self.send('/model sonnet')
        self.assertEqual(backends.task(self.state, tid)['model'], 'opus')

    def test_stop_queued_job_never_spawns(self):
        tid, job = self.queued()
        self.send('/stop')
        popen = Mock()
        worker = backends.BackendWorker(self.state, popen)
        worker.tick()
        popen.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0], 'stopped')

    def test_supervisor_claims_before_spawn_and_does_not_block_commands(self):
        tid, job = self.queued()
        process = Mock()
        process.poll.return_value = None
        def spawn(*args, **kwargs):
            row = self.state.db.execute('SELECT status FROM backend_jobs').fetchone()
            self.assertEqual(row[0], 'running')
            self.assertNotIn(job['prompt'], str(args))
            self.assertTrue(kwargs['start_new_session'])
            return process
        worker = backends.BackendWorker(self.state, spawn)
        worker.tick()
        start = time.monotonic()
        self.send('/status')
        self.send('/tasks')
        self.bridge.flush()
        self.assertLess(time.monotonic() - start, 1)
        self.assertIn('Claude · running', self.telegram.sent[-1][1])
        process.poll.return_value = 1
        worker.tick()
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0], 'uncertain')
        self.send('Do not start')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        self.send('/recover')
        self.send('Continue after checking')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 2)

    def test_restart_preserves_queued_jobs_and_never_replays_running_jobs(self):
        tid, job = self.queued()
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running'")
        popen = Mock()
        worker = backends.BackendWorker(self.state, popen)
        worker.tick()
        popen.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0], 'uncertain')
        self.assertIn('not replayed', self.state.db.execute('SELECT text FROM outbox').fetchone()[0])

    def test_completion_reuses_file_delivery_and_maps_replies(self):
        tid, job = self.queued()
        artifact = self.root / 'result.txt'
        artifact.write_text('Result bytes')
        summary = f'Finished. [Result](<{artifact}>)'
        backends.finish(self.state, job['id'], 'completed', summary, .01)
        backends.finish(self.state, job['id'], 'completed', summary, .01)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
        self.bridge.flush()
        self.assertEqual(self.telegram.media[0][1], b'Result bytes')
        self.send('Revise it', reply=len(self.telegram.sent))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs WHERE thread_id=?', (tid,)).fetchone()[0], 2)

    def test_permission_approval_is_one_time_authorized_and_expiring(self):
        tid, job = self.queued()
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='waiting'")
            self.state.db.execute('INSERT INTO tool_requests VALUES (?,?,?,?,?,?,?)',
                                  ('req1', job['id'], tid, 'Bash', '{}', 'pending', time.time() + 100))
        self.send('/allow req1', user=456)
        self.assertEqual(self.state.db.execute('SELECT status FROM tool_requests').fetchone()[0], 'pending')
        self.send('/allow req1')
        self.assertEqual(self.state.db.execute('SELECT status FROM tool_requests').fetchone()[0], 'allowed')
        with self.assertRaises(ValueError):
            backends.decide(self.state, 'req1', False)
        with self.state.db:
            self.state.db.execute("UPDATE tool_requests SET status='pending',expires_at=0")
        with self.assertRaises(ValueError):
            backends.decide(self.state, 'req1', True)

    def test_runner_session_and_resume_with_sdk_contract_fake(self):
        tid, job = self.queued()
        captured = []
        class System:
            subtype = 'init'
            data = {'session_id': tid.split(':', 1)[1]}
        class Result:
            session_id = tid.split(':', 1)[1]
            result = 'Completed via SDK'
            is_error = False
            total_cost_usd = .01
            usage = {'input_tokens':10,'cache_read_input_tokens':30,'output_tokens':5}
        class Client:
            def __init__(self, options):
                captured.append(options)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def query(self, prompt): captured.append(prompt)
            async def receive_response(self):
                yield System()
                yield Result()
            async def interrupt(self): pass
        sdk = types.SimpleNamespace(ClaudeSDKClient=Client, ClaudeAgentOptions=lambda **kw: kw,
                                    ResultMessage=Result, SystemMessage=System,
                                    PermissionResultAllow=lambda **kw: kw, PermissionResultDeny=lambda **kw: kw)
        async def run(jid):
            with self.state.db:
                self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (jid,))
            await claude_runner.run_job(self.state, jid, os.getppid())
        with patch.dict('sys.modules', {'claude_agent_sdk': sdk}), \
                patch('task_relay.claude_runner.claude_config', return_value={'auth': 'account'}):
            asyncio.run(run(job['id']))
            self.assertEqual(captured[0]['session_id'], tid.split(':', 1)[1])
            self.assertIsNone(captured[0]['resume'])
            self.send('Continue')
            second = self.state.db.execute('SELECT id FROM backend_jobs ORDER BY created_at DESC LIMIT 1').fetchone()[0]
            asyncio.run(run(second))
        self.assertEqual(captured[2]['resume'], tid.split(':', 1)[1])
        self.assertIsNone(captured[2]['session_id'])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM backend_jobs WHERE status='completed'").fetchone()[0], 2)
        counts=[json.loads(r[0]) for r in self.state.db.execute('SELECT counts FROM usage_events')]
        self.assertEqual([r['total_tokens'] for r in counts],[45,45])

    def test_runner_waits_for_real_bridge_permission_decision(self):
        tid, job = self.queued()
        options = {}
        test = self
        class System:
            subtype = 'init'
            data = {'session_id': tid.split(':', 1)[1]}
        class Result:
            session_id = tid.split(':', 1)[1]
            result = 'Permission flow completed'
            is_error = False
            total_cost_usd = .01
        class Client:
            def __init__(self, options): self.options = options
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def query(self, prompt): pass
            async def interrupt(self): pass
            async def receive_response(self):
                yield System()
                action = {'command': 'python3 -m unittest'}
                pending = asyncio.create_task(self.options['can_use_tool']('Bash', action, None))
                await asyncio.sleep(0)
                req = test.state.db.execute('SELECT * FROM tool_requests').fetchone()
                test.assertEqual(req['status'], 'pending')
                test.assertEqual(test.state.db.execute('SELECT status FROM watched').fetchone()[0], 'waiting')
                test.send('/status')
                test.assertIn('Claude: waiting', test.telegram.sent[-1][1])
                test.send('/allow ' + req['id'], user=456)
                test.assertFalse(pending.done())
                test.send('/allow ' + req['id'])
                result = await pending
                test.assertEqual(result, {'updated_input': action})
                test.assertEqual(test.state.db.execute('SELECT status FROM tool_requests').fetchone()[0], 'used')
                yield Result()
        sdk = types.SimpleNamespace(ClaudeSDKClient=Client, ClaudeAgentOptions=lambda **kw: kw,
                                    ResultMessage=Result, SystemMessage=System,
                                    PermissionResultAllow=lambda **kw: kw, PermissionResultDeny=lambda **kw: kw)
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running'")
        with patch.dict('sys.modules', {'claude_agent_sdk': sdk}), \
                patch('task_relay.claude_runner.claude_config', return_value={'auth': 'account'}):
            asyncio.run(claude_runner.run_job(self.state, job['id'], os.getppid()))
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0], 'completed')

    def test_long_response_is_preserved_and_delivered_after_summary(self):
        tid, job = self.queued()
        summary = 'Long result. ' * 500
        backends.finish(self.state, job['id'], 'completed', summary)
        row = self.state.db.execute('SELECT result_path FROM backend_jobs').fetchone()
        self.assertEqual(Path(row[0]).read_text(), summary)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE sent=0').fetchone()[0], 2)
        event_text = self.state.db.execute('SELECT text FROM outbox WHERE id=?', (f'backend:{job["id"]}:result',)).fetchone()[0]
        self.assertIn(summary, event_text)
        self.bridge.flush()
        parts = [text.split('\n\n', 1)[1] for _, text in self.telegram.sent if 'Part ' in text]
        self.assertEqual(''.join(parts), event_text)
        self.assertEqual(self.telegram.media[0][1].decode(), summary)


if __name__ == '__main__':
    unittest.main()
