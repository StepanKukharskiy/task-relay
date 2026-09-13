import io
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from task_relay.bridge import State
from task_relay import browser_research as research
from task_relay.browser_jobs import Journal
from task_relay.host_perplexity import Port, MAX_MESSAGE, prepare, registry_folder
from task_relay.perplexity_native import Driver as NativeDriver
from task_relay.relay_paths import Paths
from tests.test_browser_jobs import Driver, URL


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(Path(self.tmp.name) / 'data/state.sqlite')
        self.addCleanup(self.state.db.close)
        research.initialize(self.state.db)
        research.connection(self.state.db, 'fixture')

    def test_exact_request_and_channel_result_without_model_or_duplicate_submit(self):
        text = '/perplexity Exact question\nwith a second line'
        receipt = research.enqueue(self.state, 'message1', text, 'messages')
        self.assertEqual(research.enqueue(self.state, 'message1', text, 'messages'), receipt)
        driver = Driver()
        result = research.run_next(self.state, driver)
        self.assertEqual(driver.sent, ['Exact question\nwith a second line'])
        self.assertEqual(result['status'], 'completed')
        self.assertIsNone(research.run_next(self.state, driver))
        row = self.state.db.execute("SELECT o.text,c.channel FROM outbox o JOIN relay_event_channels c ON c.event_id=o.id WHERE o.id=?",
                                    ('perplexity-research:' + receipt + ':completed',)).fetchone()
        self.assertIn(URL, row['text'])
        self.assertEqual(row['channel'], 'messages')
        with self.assertRaisesRegex(ValueError, 'different text'):
            research.enqueue(self.state, 'message1', '/perplexity changed', 'messages')

    def test_channel_insert_failure_rolls_back_journal_and_entire_intake(self):
        self.state.db.execute("CREATE TRIGGER reject_channel BEFORE INSERT ON relay_event_channels BEGIN SELECT RAISE(ABORT,'fail'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            research.enqueue(self.state, 'atomic', '/perplexity example')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_research_requests').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_lost_reply_reconnect_and_reconciliation_never_resubmit(self):
        receipt = research.enqueue(self.state, 'lost', '/perplexity example', 'local')
        driver = Driver(); driver.error = TimeoutError('Lost reply')
        self.assertEqual(research.run_next(self.state, driver)['status'], 'uncertain')
        research.recover(self.state)
        self.assertIsNone(research.run_next(self.state, driver))
        with self.assertRaises(ValueError): research.requeue(self.state, receipt)
        research.requeue(self.state, receipt, inspect=True, url=URL)
        result = research.run_next(self.state, driver)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(driver.sent, ['example'])

    def test_crash_after_claim_is_terminal_until_explicit_observation(self):
        receipt = research.enqueue(self.state, 'crash', '/perplexity example')
        with self.state.db:
            self.state.db.execute("UPDATE browser_research_requests SET state='running' WHERE id=?", (receipt,))
        Journal(self.state.db).claim(receipt, Driver().snapshot())
        research.recover(self.state)
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'uncertain')
        self.assertIsNone(research.run_next(self.state, Driver()))

    def test_completion_before_delivery_commit_recovers_one_outbox(self):
        receipt = research.enqueue(self.state, 'done', '/perplexity example')
        with self.state.db:
            self.state.db.execute("UPDATE browser_research_requests SET state='running' WHERE id=?", (receipt,))
        Journal(self.state.db).update(receipt, 'completed', url=URL, result='Observed answer')
        research.recover(self.state); research.recover(self.state)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE id=?", ('perplexity-research:' + receipt + ':completed',)).fetchone()[0], 1)

    def test_offline_connection_blocks_before_accepting_work(self):
        with self.state.db:self.state.db.execute('UPDATE browser_research_connection SET updated=0')
        with self.assertRaisesRegex(ValueError, 'No Search was queued'):
            research.enqueue(self.state, 'offline', '/perplexity example')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0], 0)

    def test_explicit_followup_keeps_target_and_exact_prompt(self):
        receipt = research.enqueue(self.state, 'follow', '/perplexity ' + URL + '\nExpand point 2', 'local')
        job = Journal(self.state.db).get(receipt)
        self.assertEqual(job['target'], URL)
        self.assertEqual(job['prompt'], 'Expand point 2')
        self.assertIsNone(research.request_text('What do you think about using Perplexity?'))
        self.assertIsNone(research.request_text('Use Perplexity to research local browser control'))

    def test_blocked_login_is_not_retried_until_requested(self):
        receipt = research.enqueue(self.state, 'login', '/perplexity example', 'local')
        driver = Driver(); driver.ready = False
        self.assertEqual(research.run_next(self.state, driver)['status'], 'blocked')
        driver.ready = True
        self.assertIsNone(research.run_next(self.state, driver))
        research.requeue(self.state, receipt)
        self.assertEqual(research.run_next(self.state, driver)['status'], 'completed')
        self.assertEqual(driver.sent, ['example'])

    def test_generated_native_host_process_consumes_queue_and_returns_result(self):
        base = Path(self.tmp.name)
        package = prepare(base / 'native', Paths(base, base / 'data', base / 'work', base / 'generated'))
        manifest = json.loads(Path(package['host_manifest']).read_text())
        process = subprocess.Popen([manifest['path'], package['host_manifest'], 'perplexity@task-relay.local'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if process.poll() is None:process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        port = Port(process.stdout, process.stdin)
        port.write({'action': 'poll'})
        self.assertEqual(port.read(timeout=5), {'action': 'idle'})
        receipt = research.enqueue(self.state, 'process', '/perplexity example', 'local')
        port.write({'action': 'poll'})
        fixture = Driver()
        for action in ('open', 'snapshot', 'submit', 'snapshot'):
            message = port.read(timeout=5)
            self.assertEqual(message['action'], action)
            if action == 'open':fixture.open(message['url']); value = True
            elif action == 'snapshot':value = fixture.snapshot()
            else:fixture.submit(message['prompt'], message['baseline']); value = True
            port.write({'id': message['id'], 'value': value})
        self.assertEqual(port.read(timeout=5), {'action': 'idle'})
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'completed')
        self.assertEqual(fixture.sent, ['example'])
        port.write({'action': 'poll'})
        self.assertEqual(port.read(timeout=5), {'action': 'idle'})


class ProtocolTests(unittest.TestCase):
    def test_opened_tab_destination_change_blocks_before_submit(self):
        class FakePort:
            def __init__(self):self.sent = []
            def write(self, message):self.sent.append(message)
            def read(self):
                m = self.sent[-1]
                return {'id': m['id'], 'value': True if m['action'] == 'open' else
                        {'url': URL, 'text': '', 'ready': True, 'queries': 0, 'answers': 0}}
        port = FakePort(); driver = NativeDriver(port)
        driver.open()
        with self.assertRaisesRegex(ValueError, 'changed destination'):
            driver.snapshot()
        self.assertEqual([m['action'] for m in port.sent], ['open', 'snapshot'])

    def test_native_framing_unicode_disconnect_and_size_limit(self):
        target = io.BytesIO()
        Port(io.BytesIO(), target).write({'text': 'Exact ✓ question'})
        self.assertEqual(Port(io.BytesIO(target.getvalue()), io.BytesIO()).read(), {'text': 'Exact ✓ question'})
        with self.assertRaises(EOFError): Port(io.BytesIO(b'\x01'), io.BytesIO()).read()
        with self.assertRaises(ValueError): Port(io.BytesIO(struct.pack('=I', MAX_MESSAGE + 1)), io.BytesIO()).read()

    def test_mismatched_reply_cannot_trigger_another_command(self):
        class FakePort:
            sent = []
            def write(self, value): self.sent.append(value)
            def read(self): return {'id': 'stale', 'value': True}
        port = FakePort()
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            NativeDriver(port).submit('example', {})
        self.assertEqual(len(port.sent), 1)

    def test_reviewable_installer_quotes_paths_and_limits_extension(self):
        with tempfile.TemporaryDirectory(prefix='relay space ') as root:
            base = Path(root); paths = Paths(base, base / 'data', base / 'work', base / 'generated')
            result = prepare(base / 'install', paths)
            manifest = json.loads(Path(result['host_manifest']).read_text())
            self.assertEqual(manifest['allowed_extensions'], ['perplexity@task-relay.local'])
            text = Path(manifest['path']).read_text()
            self.assertIn("'TASK_RELAY_DATA_DIR=", text)
            self.assertIn('"$@"', text)
            addon = json.loads(Path(result['extension']).read_text())
            self.assertNotIn('<all_urls>', addon['permissions'])
            self.assertNotIn('cookies', addon['permissions'])


from tests import test_bridge as bridge_fixtures
from tests import test_messages_orchestrator as messages_fixtures


class TelegramIntakeTests(unittest.TestCase):
    setUp = bridge_fixtures.Tests.setUp
    tearDown = bridge_fixtures.Tests.tearDown
    message = bridge_fixtures.Tests.message
    pair = bridge_fixtures.Tests.pair

    def test_natural_browser_phrasings_reach_orchestrator_without_shortcut_copying(self):
        from task_relay import orchestrator_chat as chat
        self.pair()
        research.initialize(self.state.db)
        prompts=['Use Perplexity to research browser automation',
                 'Please look up fixture suppliers on Perplexity and send the result here.',
                 'Найди в Perplexity поставщиков арматуры в Бергене за 2025 год.']
        with patch.object(chat,'provider',return_value=('gemini','fixture')):
            self.bridge.process(self.message(prompts[0], id=201, user=999))
            for ident,text in enumerate(prompts,202):
                self.bridge.process(self.message(text,id=ident))
                self.bridge.process(self.message(text,id=ident))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0],0)
        self.assertEqual([r[0] for r in self.state.db.execute('SELECT prompt FROM orchestrator_chats ORDER BY id')],prompts)


class MessagesIntakeTests(unittest.TestCase):
    setUp = messages_fixtures.Tests.setUp
    tearDown = messages_fixtures.Tests.tearDown
    new_pilot = messages_fixtures.Tests.new_pilot
    append = messages_fixtures.Tests.append
    date = messages_fixtures.Tests.date
    msg = messages_fixtures.Tests.msg
    pair = messages_fixtures.Tests.pair
    drain = messages_fixtures.Tests.drain
    router = messages_fixtures.Tests.router

    def test_paired_research_retains_its_channel_and_never_calls_planner(self):
        router = self.router(); self.pair()
        research.initialize(router.state.db); research.connection(router.state.db, 'fixture')
        self.pilot.receive(self.msg('/perplexity Example', 'wrong', chat_id=99))
        self.assertEqual(router.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0], 0)
        self.pilot.receive(self.msg('/perplexity Example', 'right'))
        self.pilot.receive(self.msg('/perplexity Example', 'right'))
        self.assertEqual(router.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0], 1)
        self.assertEqual(router.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 0)
        self.assertEqual(router.state.db.execute('SELECT channel FROM browser_research_requests').fetchone()[0], 'messages')


if __name__ == '__main__': unittest.main()
