"""Local update preparation retains bindings and refuses stale/active installs."""
import importlib.util
import json
from pathlib import Path
import plistlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'desktop/scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    SPEC = importlib.util.spec_from_file_location('install_local', SCRIPTS / 'install-local.py')
    local = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(local)


class LocalInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installed = self.root / 'Task Relay.app'
        self.candidate = self.root / 'Candidate.app'
        for app in (self.installed, self.candidate):
            (app / 'Contents').mkdir(parents=True)
            (app / 'Contents/fixture').write_text(app.name)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '0.13.61' if app == self.installed else '0.13.62'}))
        self.data = self.root / 'data'
        self.data.mkdir()
        with sqlite3.connect(self.data / 'state.sqlite') as db:
            db.execute('CREATE TABLE production_attempts(state TEXT)')
        runtime = self.installed / 'Contents/Resources/resources/runtime'
        env = {'TASK_RELAY_DATA_DIR': str(self.data), 'TASK_RELAY_GENERATED_DIR': str(self.root / 'generated'), 'TASK_RELAY_WORKSPACE_DIR': str(self.root / 'projects')}
        self.plists = [self.root / (label + '.plist') for label in local.LABELS]
        owners = ['task-relay-desktop-v1', 'task-relay-companion-messages-v1']
        commands = [[str(runtime / 'python/bin/python3'), str(runtime / 'app/bridge.py'), 'run'], [str(runtime / 'helpers/Messages Relay.app/Contents/MacOS/MessagesRelay')]]
        for i, path in enumerate(self.plists):
            path.write_bytes(plistlib.dumps({'Label': local.LABELS[i], 'TaskRelayDesktopOwner': owners[i], 'EnvironmentVariables': env, 'ProgramArguments': commands[i], 'WorkingDirectory': str(runtime / 'app')}))
        self.before = [p.read_bytes() for p in self.plists]
        self.recovery = self.root / 'recovery'
        self.addCleanup(patch.stopall)
        patch.object(local, 'PLISTS', self.plists).start()

    def prepare(self):
        with patch('sys.argv', ['install', '--prepare', str(self.recovery), '--candidate', str(self.candidate), '--installed', str(self.installed)]):
            local.main()

    def test_downgrade_is_rejected_before_prepare_mutates_anything(self):
        (self.candidate / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '0.13.60'}))
        with self.assertRaisesRegex(ValueError, 'downgrade from 0.13.61 to 0.13.60'):
            self.prepare()
        self.assertFalse(self.recovery.exists())
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_legacy_downgrade_manifest_cannot_stop_services(self):
        self.prepare()
        path = self.recovery / 'install-manifest.json'
        value = json.loads(path.read_text())
        (self.candidate / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '0.13.60'}))
        value['candidate_digest'] = local.digest(self.candidate)
        path.write_text(json.dumps(value))
        with patch('sys.argv', ['install', '--apply', str(path)]), patch.object(local, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'downgrade'):
                local.main()
        run.assert_not_called()
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_preparation_records_main_app_migration_without_mutating_services(self):
        self.prepare()
        manifest = json.loads((self.recovery / 'install-manifest.json').read_text())
        spec = manifest['updated_messages_spec']
        self.assertEqual([str(self.installed / 'Contents/MacOS/task-relay-desktop'), '--messages-service'], spec['ProgramArguments'])
        self.assertEqual(str(self.data), spec['EnvironmentVariables']['TASK_RELAY_DATA_DIR'])
        telegram = manifest['updated_telegram_spec']
        self.assertEqual(telegram['ProgramArguments'][1:], ['-m', 'task_relay.bridge', 'run'])
        self.assertEqual(telegram['EnvironmentVariables'], plistlib.loads(self.before[0])['EnvironmentVariables'])
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_already_migrated_telegram_prepares_without_rewriting_services(self):
        spec = plistlib.loads(self.plists[0].read_bytes())
        spec['ProgramArguments'] = [spec['ProgramArguments'][0], '-m', 'task_relay.bridge', 'run']
        self.plists[0].write_bytes(plistlib.dumps(spec))
        before = self.plists[0].read_bytes()
        self.prepare()
        manifest = json.loads((self.recovery / 'install-manifest.json').read_text())
        self.assertEqual(manifest['updated_telegram_spec'], {**spec, 'AssociatedBundleIdentifiers':['com.taskrelay.desktop'], 'LimitLoadToSessionType':'Aqua'})
        self.assertEqual(self.plists[0].read_bytes(), before)

    def test_older_manifest_is_refused_before_service_or_bundle_changes(self):
        self.prepare()
        path = self.recovery / 'install-manifest.json'
        value = json.loads(path.read_text()); del value['updated_telegram_spec']
        path.write_text(json.dumps(value))
        with patch('sys.argv', ['install', '--apply', str(path)]), patch.object(local, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'new installation manifest'):
                local.main()
        run.assert_not_called()
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_active_attempt_prevents_update_preparation(self):
        with sqlite3.connect(self.data / 'state.sqlite') as db:
            db.execute("INSERT INTO production_attempts VALUES ('running')")
        with self.assertRaisesRegex(RuntimeError, 'Active or queued'):
            self.prepare()
        self.assertFalse(self.recovery.exists())
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_changed_candidate_cannot_stop_services(self):
        self.prepare()
        (self.candidate / 'Contents/fixture').write_text('changed')
        with patch('sys.argv', ['install', '--apply', str(self.recovery / 'install-manifest.json')]), patch.object(local, 'run') as run:
            with self.assertRaisesRegex(AssertionError, 'Candidate changed'):
                local.main()
        run.assert_not_called()
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

class GuardedMaintenanceTests(unittest.TestCase):
    prepare = LocalInstallTests.prepare

    def setUp(self):
        LocalInstallTests.setUp(self)
        from task_relay.bridge import State
        self.state = State(self.data / 'state.sqlite')
        self.addCleanup(self.state.db.close)
        # The inherited fixture supplies a minimal attempts table; historical rows
        # deliberately remain unrelated to delivery maintenance.
        with self.state.db:
            for i in ('completion', 'obsolete-approval'):
                self.state.db.execute("INSERT INTO relay_delivery_effects VALUES (?,?,?,'submitting',1,NULL,NULL,12)", ('text:'+i+':0',i,__import__('hashlib').sha256(b'{}').hexdigest()))
                self.state.db.execute('INSERT INTO outbox(id,text,sent) VALUES (?,?,?)', (i,'original '+i,int(i=='obsolete-approval')))
            self.state.db.execute("INSERT INTO production_attempts(state) VALUES ('completed')")
        local.DB = self.data / 'state.sqlite'
        local.INSTALLED, local.CANDIDATE = self.installed, self.candidate
        patch.object(local, 'loaded', return_value=False).start()
        patch.object(local, 'sender_processes', return_value=[]).start()
        self.rows = local.pending_deliveries()
        self.policy = __import__('task_relay.channel_policy', fromlist=['read']).read(self.state.db)

    def test_hold_preparation_is_read_only_and_binds_exact_intents(self):
        with self.assertRaisesRegex(RuntimeError, 'Active or queued'):
            self.prepare()
        with patch('sys.argv', ['install','--prepare',str(self.recovery),'--candidate',str(self.candidate),
                               '--installed',str(self.installed),'--hold-uncertain-deliveries']):
            local.main()
        value=json.loads((self.recovery/'install-manifest.json').read_text())
        self.assertEqual(value['delivery_quarantine'],self.rows)
        self.assertEqual(local.pending_deliveries(),self.rows)
        self.assertEqual(self.before,[p.read_bytes() for p in self.plists])

    def test_changed_or_new_intent_stops_prepared_maintenance(self):
        with self.state.db:
            self.state.db.execute("UPDATE relay_delivery_effects SET attempts=2 WHERE event_id='completion'")
        with self.assertRaisesRegex(RuntimeError,'changed'):
            local.idle(self.rows)
        with self.assertRaisesRegex(RuntimeError,'changed'):
            local.maintenance_pause('update',self.rows)
        self.assertEqual(self.policy,__import__('task_relay.channel_policy',fromlist=['read']).read(self.state.db))

    def test_active_work_remains_blocked_even_with_delivery_hold(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO production_attempts(state) VALUES ('running')")
        with self.assertRaisesRegex(RuntimeError,'production_attempts'):
            local.idle(self.rows)

    def test_alive_sender_or_loaded_service_cannot_quarantine(self):
        local.maintenance_pause('update',self.rows)
        with patch.object(local,'sender_processes',return_value=['123 sender']):
            with self.assertRaisesRegex(RuntimeError,'not proven stopped'):
                local.quarantine_deliveries('update')
        with patch.object(local,'loaded',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'not proven stopped'):
                local.quarantine_deliveries('update')
        self.assertEqual(local.pending_deliveries(),self.rows)

    def test_interrupted_transaction_rolls_back_both_effects_and_audit(self):
        local.maintenance_pause('update',self.rows)
        with self.state.db:
            self.state.db.execute("CREATE TRIGGER interrupt_quarantine BEFORE UPDATE ON relay_delivery_effects WHEN OLD.event_id='obsolete-approval' BEGIN SELECT RAISE(ABORT,'injected interruption'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'injected interruption'):
            local.quarantine_deliveries('update')
        self.assertEqual(local.pending_deliveries(),self.rows)
        journal=json.loads(self.state.db.execute('SELECT record FROM relay_install_maintenance').fetchone()[0])
        self.assertEqual(journal['phase'],'paused')
        self.assertEqual(journal['deliveries'],self.rows)

    def test_committed_quarantine_survives_restart_without_replay_or_history_change(self):
        from task_relay import channel_policy, delivery_effects
        from task_relay.bridge import State
        from unittest.mock import Mock
        history=[tuple(r) for r in self.state.db.execute('SELECT * FROM outbox ORDER BY id')]
        local.maintenance_pause('update',self.rows)
        local.quarantine_deliveries('update')
        self.state.db.close()
        self.state=State(self.data/'state.sqlite')
        self.addCleanup(self.state.db.close)
        self.assertFalse(channel_policy.outgoing(self.state.db,'telegram'))
        with self.assertRaisesRegex(RuntimeError,'Earlier maintenance'):
            local.maintenance_pause('second',[])
        local.release_maintenance('update')
        policy=channel_policy.read(self.state.db)
        self.assertEqual({k:v for k,v in policy.items() if k!='revision'}, {k:v for k,v in self.policy.items() if k!='revision'})
        for original in self.rows:
            row=dict(self.state.db.execute('SELECT * FROM relay_delivery_effects WHERE id=?',(original['id'],)).fetchone())
            self.assertEqual(row['status'],'uncertain')
            for key in ('id','event_id','digest','receipt','attempts'):
                self.assertEqual(row[key],original[key])
            transport=Mock()
            with self.assertRaises(delivery_effects.UncertainDelivery):
                delivery_effects.send(self.state,row['id'],row['event_id'],{},transport)
            transport.assert_not_called()
        self.assertEqual(history,[tuple(r) for r in self.state.db.execute('SELECT * FROM outbox ORDER BY id')])
        self.assertEqual(self.state.db.execute('SELECT state FROM production_attempts').fetchone()[0],'completed')
        self.assertEqual(local.pending_deliveries(),[])
        local.idle()

    def test_changed_channel_policy_does_not_get_overwritten_on_release(self):
        from task_relay import channel_policy
        local.maintenance_pause('update',self.rows)
        local.quarantine_deliveries('update')
        with self.state.db:
            value=channel_policy.read(self.state.db);value['revision']+=1;value['proactive']='none'
            local.store_policy(self.state.db,value)
        with self.assertRaisesRegex(RuntimeError,'state changed'):
            local.release_maintenance('update')
        self.assertEqual(channel_policy.read(self.state.db),value)

    def apply_fixture(self, interrupt=False):
        from task_relay import channel_policy
        from types import SimpleNamespace
        import shutil, zipfile
        for app in (self.installed,self.candidate):
            path=app/'Contents/Info.plist';value=plistlib.loads(path.read_bytes())
            value['CFBundleIdentifier']='com.taskrelay.desktop';path.write_bytes(plistlib.dumps(value))
        def bundle_command(args):
            args=[str(v) for v in args]
            if args[0]=='codesign':return
            if args[:4]==['ditto','-c','-k','--sequesterRsrc']:
                source=Path(args[-2])
                with zipfile.ZipFile(args[-1],'w') as archive:
                    for path in source.rglob('*'):
                        if path.is_file():archive.write(path,path.relative_to(source.parent))
            elif args[:3]==['ditto','-x','-k']:
                with zipfile.ZipFile(args[-2]) as archive:archive.extractall(args[-1])
            elif args[0]=='ditto':shutil.copytree(args[1],args[2])
            else:self.fail('Unexpected host call '+str(args))
        with patch('sys.argv', ['install','--prepare',str(self.recovery),'--candidate',str(self.candidate),
                               '--installed',str(self.installed),'--hold-uncertain-deliveries']):
            local.main()
        (self.data/'messages-pilot').mkdir()
        (self.data/'messages-pilot/health.json').write_text('{"status":"needs_attention","updated_at":0}')
        present=set(local.LABELS)
        operations=[]
        def command(args,check=True):
            operations.append(args[0:2])
            if args[:2]==['launchctl','bootout']:present.discard(args[2].split('/')[-1])
            if args[:2]==['launchctl','bootstrap']:
                label=Path(args[3]).stem;present.add(label)
                self.assertFalse(channel_policy.outgoing(self.state.db,'telegram'))
                self.assertEqual(local.pending_deliveries(),[])
                with self.state.db:
                    for key in ('desktop','desktop-plans','scan','production','orchestrator-chat'):
                        self.state.put('health:'+key,{'last_success':local.time.time()})
                (self.data/'messages-pilot/health.json').write_text(json.dumps({'status':'needs_attention','updated_at':local.time.time()}))
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        real_replace=local.replace_contents
        def replace(*args):
            self.assertFalse(present)
            self.assertEqual(local.pending_deliveries(),[])
            if interrupt:raise KeyboardInterrupt('injected before replacement')
            return real_replace(*args)
        with patch('sys.argv',['install','--apply',str(self.recovery/'install-manifest.json')]), \
             patch.object(local,'loaded',side_effect=lambda label:label in present), \
             patch.object(local,'run',side_effect=command),patch.object(local,'app_pids',return_value=[]), \
             patch.object(local,'maintain_backups',return_value={'status':'preserved'}), \
             patch.object(local,'replace_contents',side_effect=replace), \
             patch('task_relay.app_bundle.run',side_effect=bundle_command):
            if interrupt:
                with self.assertRaises(KeyboardInterrupt):local.main()
            else:local.main()
        receipt=json.loads((self.recovery/'install-receipt.json').read_text())
        return receipt

    def test_install_stops_senders_and_quarantines_before_replacement(self):
        from task_relay import channel_policy
        receipt=self.apply_fixture()
        self.assertEqual(receipt['maintenance']['phase'],'released')
        self.assertEqual(receipt['maintenance']['deliveries'],self.rows)
        self.assertTrue(Path(receipt['pre_pause_backup']).is_file())
        self.assertTrue(Path(receipt['database_backup']).is_file())
        self.assertEqual((self.installed/'Contents/fixture').read_text(),'Candidate.app')
        self.assertTrue(channel_policy.outgoing(self.state.db,'telegram'))

    def test_interrupted_install_preserves_uncertainty_and_paused_restart(self):
        from task_relay import channel_policy
        receipt=self.apply_fixture(interrupt=True)
        self.assertEqual(receipt['phase'],'needs_inspection')
        self.assertTrue(receipt['restored_before_new_service_start'])
        self.assertEqual(local.pending_deliveries(),[])
        self.assertFalse(channel_policy.outgoing(self.state.db,'telegram'))
        self.assertEqual((self.installed/'Contents/fixture').read_text(),'Task Relay.app')
        for row in self.state.db.execute('SELECT * FROM relay_delivery_effects'):
            self.assertEqual(row['status'],'uncertain')
            self.assertEqual(row['attempts'],1)
        with patch('sys.argv',['install','--apply',str(self.recovery/'install-manifest.json')]),patch.object(local,'run') as command:
            with self.assertRaisesRegex(RuntimeError,'receipt already exists'):local.main()
        command.assert_not_called()

    def test_fresh_install_cannot_bypass_an_interrupted_maintenance_hold(self):
        local.maintenance_pause('interrupted',self.rows)
        local.quarantine_deliveries('interrupted')
        self.assertEqual(local.pending_deliveries(),[])
        with self.assertRaisesRegex(RuntimeError,'Earlier maintenance'):
            self.prepare()
        self.assertFalse(self.recovery.exists())
        self.assertEqual(self.before,[p.read_bytes() for p in self.plists])
