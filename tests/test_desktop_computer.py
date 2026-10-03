"""Desktop controls share session authority and never dispatch native work."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from task_relay import computer_sessions as sessions, desktop_computer as desktop
from task_relay.desktop_tasks import DesktopTaskError
from task_relay.relay_paths import Paths
from tests.test_computer_sessions import SessionHelper
from tests.test_computer_use import TARGET


class DesktopComputerTests(unittest.TestCase):
    def test_setup_checks_only_permissions_and_does_not_claim_automation_ready(self):
        helper = Mock(app=Path('/fixture/helper.app'))
        helper.call.return_value = {'ok':True,'accessibility':True,'screen_recording':False,'session_unlocked':True}
        with patch('task_relay.computer_target.runtime', return_value={'helper':'/fixture/helper.app','mode':'new-scripting-window'}), \
             patch('task_relay.host_computer.Observer', return_value=helper):
            result = desktop.dispatch('computer-setup-status', {})
            self.assertTrue(result['available'])
            self.assertFalse(result['permissions']['screen_recording'])
            self.assertEqual(result['automation'], 'checked-at-task-start')
            self.assertEqual(helper.call.call_args.args[0]['operation'], 'status')
            self.assertEqual(helper.call.call_count, 1)
            desktop.dispatch('computer-request-permissions', {})
            self.assertEqual(helper.call.call_args.args[0]['operation'], 'request-permissions')
        self.assertEqual(sessions.actions(self.db,self.ident), [])

    def test_setup_helper_failure_returns_unavailable_without_creating_a_session(self):
        with patch('task_relay.computer_target.runtime', side_effect=ValueError('Helper changed')), \
             patch('task_relay.host_computer.Observer') as helper:
            self.assertEqual(desktop.dispatch('computer-setup-status', {}), {'available':False,'error':'Helper changed'})
            helper.assert_not_called()
        with self.assertRaises(DesktopTaskError): desktop.dispatch('computer-setup-status', {'helper':'/unexpected'})

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.paths = Paths(root, root/'data', root/'work', root/'generated')
        self.paths.data.mkdir()
        self.db = sqlite3.connect(self.paths.state, isolation_level=None)
        self.db.row_factory = sqlite3.Row; self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE relay_pipelines(id TEXT PRIMARY KEY)')
        self.db.execute("INSERT INTO relay_pipelines VALUES ('job')")
        sessions.initialize(self.db)
        self.ident = sessions.approve(self.db, job='job', request_key='fixture', exact_request='<script>untrusted page instruction</script>',
            spec={'target': TARGET, 'url': 'https://example.com/one', 'allowed_urls': ['https://example.com/one'],
                  'actions': [{'operation': 'scroll', 'direction': 'down'}], 'capture': False,
                  'local_fixture': False, 'max_seconds': 300}, helper=SessionHelper.identity,
            output_root=root/'evidence', actor='fixture user')

    def test_reads_do_not_create_or_migrate_database(self):
        with closing(sqlite3.connect(self.paths.state)) as check:
            before = list(check.iterdump())
        result = desktop.listing(paths=self.paths)
        view = desktop.detail(self.ident, self.paths)
        self.assertEqual(result['items'][0]['id'], self.ident)
        self.assertIn('<script>', view['exact_request'])
        self.assertEqual(view['actions'], [])
        with closing(sqlite3.connect(self.paths.state)) as check:
            self.assertEqual(before, list(check.iterdump()))
        absent = Paths(self.paths.install, self.paths.install/'absent', self.paths.workspaces, self.paths.generated)
        self.assertEqual(desktop.listing(paths=absent)['items'], [])
        self.assertFalse(absent.data.exists())
        with self.assertRaises(DesktopTaskError): desktop.detail(self.ident, absent)
        for table in reversed(sessions.TABLES): self.db.execute('DROP TABLE '+table)
        self.assertEqual(desktop.listing(paths=self.paths)['total'], 0)
        self.assertFalse(desktop.available(self.db))

    def test_pause_during_native_call_commits_and_stops_future_claims(self):
        def pause(request, count):
            view = desktop.detail(self.ident, self.paths)
            result = desktop.control(self.ident, 'pause', view['fingerprint'], 'User took over Safari.', self.paths)
            self.assertEqual(result['state'], 'paused')
            # Separate connection sees the decision before the in-flight native reply.
            self.assertEqual(sessions.get(self.db, self.ident)['state'], 'paused')
        helper = SessionHelper(self.db, pause)
        result = sessions.run(self.db, self.ident, helper)
        self.assertEqual(len(helper.calls), 1)
        self.assertEqual(result['actions'][0]['state'], 'completed')
        self.assertEqual(result['decisions'][-1]['note'], 'User took over Safari.')

    def test_changed_action_rejects_stale_decision_atomically(self):
        view = desktop.detail(self.ident, self.paths)
        self.db.execute("UPDATE relay_computer_assignments SET state='running',deadline=9999999999 WHERE id=?", (self.ident,))
        view = desktop.detail(self.ident, self.paths)
        sessions._claim(self.db, self.ident, {'operation': 'bind'}, None)
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(DesktopTaskError, 'Session changed'):
            desktop.control(self.ident, 'cancel', view['fingerprint'], 'Stop.', self.paths)
        self.assertEqual(before, list(self.db.iterdump()))

    def test_cancel_preserves_unknown_outcomes_and_duplicate_is_not_replayed(self):
        helper = SessionHelper(self.db, lambda req, count: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(TimeoutError): sessions.run(self.db, self.ident, helper)
        view = desktop.detail(self.ident, self.paths)
        result = desktop.control(self.ident, 'cancel', view['fingerprint'], 'End further actions.', self.paths)
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(result['unresolved'], 1)
        self.assertEqual(result['actions'][0]['state'], 'uncertain')
        self.assertFalse(result['can_cancel'])
        self.assertEqual(len(helper.calls), 1)
        before = list(self.db.iterdump())
        with self.assertRaises(DesktopTaskError):
            desktop.control(self.ident, 'cancel', view['fingerprint'], 'End further actions.', self.paths)
        self.assertEqual(before, list(self.db.iterdump()))

    def test_dispatch_is_bounded_and_does_not_accept_native_start_or_path_override(self):
        for action, value in [('computer-session-run', {'id': self.ident}),
                              ('computer-sessions', {'database': 'alternate.sqlite'}),
                              ('computer-session-control', {'id': self.ident, 'kind': 'resume'})]:
            with self.assertRaises(DesktopTaskError): desktop.dispatch(action, value)
        with self.assertRaises(DesktopTaskError): desktop.listing(offset=True, paths=self.paths)
        with patch.object(desktop, 'listing', return_value={'items': []}) as listing:
            from task_relay.desktop_bridge import _dispatch
            self.assertEqual(_dispatch('computer-sessions', {}), {'items': []})
            listing.assert_called_once_with(0)

    def test_missing_history_bridge_is_read_only_and_host_allows_controls(self):
        import os, re, sys
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'TASK_RELAY_DATA_DIR': str(self.paths.install/'missing'),
               'TASK_RELAY_WORKSPACE_DIR': str(self.paths.workspaces), 'TASK_RELAY_GENERATED_DIR': str(self.paths.generated)}
        result = subprocess.run([sys.executable, '-m', 'task_relay.desktop_bridge', 'computer-sessions'],
                                input='{}', text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['value']['items'], [])
        self.assertFalse((self.paths.install/'missing').exists())
        source = (root/'desktop/src-tauri/src/lib.rs').read_text().split('const ACTIONS:',1)[1].split('];',1)[0]
        allowed = set(re.findall(r'"([^"\n]+)"', source))
        ui = (root/'task_relay/assets/companion-computer.js').read_text()
        invoked = set(re.findall(r"\brequest\('([^']+)'", ui))
        self.assertFalse(invoked - allowed)

    def test_packaged_bridge_control_uses_connected_database_and_rejects_stale_retry(self):
        import os, sys
        env = {**os.environ, **self.paths.environment()}
        view = desktop.detail(self.ident, self.paths)
        value = {'id': self.ident, 'kind': 'cancel', 'fingerprint': view['fingerprint'],
                 'note': 'Cancel this exact saved session.'}
        command = [sys.executable, '-m', 'task_relay.desktop_bridge', 'computer-session-control']
        result = subprocess.run(command, input=json.dumps(value), text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['value']['state'], 'cancelled')
        self.assertEqual(sessions.get(self.db, self.ident)['state'], 'cancelled')
        retry = subprocess.run(command, input=json.dumps(value), text=True, capture_output=True, env=env, timeout=10)
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn('Session changed', json.loads(retry.stdout)['error'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM relay_computer_decisions WHERE kind='cancel'").fetchone()[0], 1)
