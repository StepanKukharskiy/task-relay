"""Supported authoring entry point; synthetic jobs and fake execution only."""
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
import uuid
from task_relay import authoring,author_cli,desktop_node_drafts as drafts,desktop_node_runs as runs
from task_relay import desktop_node_files as files,desktop_bridge,desktop_workspace as workspace
from tests import test_same_canvas_rerun as fixtures

ROOT=Path(__file__).resolve().parents[1]


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        fixtures.SameCanvas.setUp(self)
        original=desktop_bridge.dispatch
        def dispatch(action,value):
            if action=='workspace-detail':return workspace.detail(value['run'],self.paths)
            return original(action,value)
        p=patch.object(authoring,'bridge',dispatch);p.start();self.addCleanup(p.stop)
        p=patch('task_relay.app_updates.Updater');u=p.start();u.return_value.host.support.return_value={'supported':False};self.addCleanup(p.stop)
        # New draft retry lookup shares this fixture's binding.
        p=patch('task_relay.relay_paths.PATHS',self.paths);p.start();self.addCleanup(p.stop)

    def edit(self,target=None,request='Change the second node only.\nKeep the first result.'):
        target=target or dict(kind='canvas',id=self.run)
        record=authoring.dispatch('open',target)
        workflow=copy.deepcopy(record['workflow']);workflow['tasks'][-1]['objective']='Revised second'
        return dict(target=dict(target,revision=record['revision']),title=record['title'],workflow=workflow,request=request)

    def save(self,preview):
        return authoring.dispatch('edit-save',{k:preview[k] for k in ('proposal','fingerprint')})

    def test_revision_preview_save_exact_retry_and_history_preserve_execution(self):
        before=list(self.state.db.iterdump());p=authoring.dispatch('edit-preview',self.edit())
        self.assertEqual(before,list(self.state.db.iterdump()));self.assertEqual(p['changes']['changed'],['second'])
        saved=self.save(p);self.assertFalse(saved['execution_authorized'])
        self.assertEqual(saved['authoring']['request'],p['proposal']['request'])
        after=list(self.state.db.iterdump());self.assertTrue(self.save(p)['reused']);self.assertEqual(after,list(self.state.db.iterdump()))
        self.assertEqual(self.original,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])
        nextp=authoring.dispatch('edit-preview',self.edit(request='Another exact request'))
        self.save(nextp)
        with self.assertRaisesRegex(ValueError,'changed'):self.save(p)
        events=[json.loads(r[0]) for r in self.state.db.execute("SELECT data FROM production_events WHERE kind='canvas_workflow_saved'")]
        self.assertEqual([r['authoring']['request'] for r in events],[p['proposal']['request'],'Another exact request'])

    def test_tampered_preview_and_stale_base_never_save(self):
        value=self.edit();p=authoring.dispatch('edit-preview',value);before=list(self.state.db.iterdump())
        tampered=copy.deepcopy(p);tampered['proposal']['workflow']['tasks'][0]['objective']='Unreviewed'
        with self.assertRaisesRegex(ValueError,'changed'):self.save(tampered)
        self.assertEqual(before,list(self.state.db.iterdump()))
        self.save(p)
        with self.assertRaisesRegex(ValueError,'changed'):authoring.dispatch('edit-preview',value)

    def test_contract_change_invalidates_preview_before_any_write(self):
        p=authoring.dispatch('edit-preview',self.edit());before=list(self.state.db.iterdump())
        original=authoring.definition
        def changed(op):return dict(original(op),description='Changed contract')
        with patch.object(authoring,'definition',changed):
            with self.assertRaisesRegex(ValueError,'contract changed'):self.save(p)
        self.assertEqual(before,list(self.state.db.iterdump()))

    def test_new_draft_idempotence_prior_versions_and_no_admission(self):
        value=self.edit();value['target']=dict(kind='new',id=None,revision=None)
        p=authoring.dispatch('edit-preview',value);count=self.state.db.execute('select count(*) from production_runs').fetchone()[0]
        saved=self.save(p);self.assertTrue(self.save(p)['reused'])
        self.assertEqual(count,self.state.db.execute('select count(*) from production_runs').fetchone()[0])
        target=dict(kind='draft',id=saved['id']);change=self.edit(target,request='  Exact whitespace\n')
        changed=self.save(authoring.dispatch('edit-preview',change))
        old=self.paths.data/'node-drafts/history'/saved['id']/(saved['revision']+'.json')
        self.assertEqual(json.loads(old.read_text())['workflow'],saved['workflow'])
        self.assertEqual(changed['authoring']['request'],'  Exact whitespace\n')
        collision=copy.deepcopy(p['proposal']);collision['title']='A different creation'
        collision=authoring.dispatch('edit-preview',collision)
        with self.assertRaisesRegex(ValueError,'identity'):self.save(collision)

    def test_filtered_operation_discloses_animation_contract_without_execution(self):
        from orchestrator.operation_definition import catalog
        before=list(self.state.db.iterdump());row=authoring.dispatch('operation',{'id':'blender.animate'})['operation']
        self.assertEqual(row,catalog(operations=['blender.animate'],include_legacy=True)[0])
        self.assertIn('camera',row['preparation']['schema']['properties'])
        self.assertIn('frame_start',row['preparation']['schema']['properties'])
        self.assertTrue(row['outputs']);self.assertEqual(before,list(self.state.db.iterdump()))
        with self.assertRaisesRegex(ValueError,'registered'):authoring.dispatch('operation',{'id':'blender.invented'})

    def test_scoped_run_admits_once_and_never_dispatches_from_cli(self):
        saved=self.save(authoring.dispatch('edit-preview',self.edit()))
        value=dict(target=dict(kind='canvas',id=self.run),revision=saved['revision'],scope='second',values={})
        check=authoring.dispatch('run-preview',value)
        self.assertEqual([t['id'] for t in check['preview']['plan']['tasks']],['second'])
        calls=len(self.factory.calls)
        command=dict(command=check['command'],fingerprint=check['preview']['fingerprint'],allow_paid=False,approve_host_code=[],acknowledge_uncertain=[])
        admitted=authoring.dispatch('run-start',command)
        self.assertTrue(authoring.dispatch('run-start',command)['reused'])
        self.assertEqual(calls,len(self.factory.calls))
        self.rt.tick(admitted['run']);attempt=self.rt.task(admitted['run'],'second')['latest']
        self.factory.finish(attempt);self.rt.tick(admitted['run'])
        status=authoring.dispatch('run-status',{'run':self.run})
        self.assertEqual(status['status'],'completed')
        self.assertEqual(self.original,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])

    def test_stale_run_and_missing_authorization_fields_reject(self):
        r=authoring.dispatch('open',dict(kind='canvas',id=self.run))
        p=authoring.dispatch('run-preview',dict(target=dict(kind='canvas',id=self.run),revision=r['revision'],scope='second',values={}))
        c=dict(command=p['command'],fingerprint=p['preview']['fingerprint'],allow_paid=False,approve_host_code=[],acknowledge_uncertain=[])
        for key in ('allow_paid','approve_host_code','acknowledge_uncertain'):
            bad=dict(c);bad.pop(key)
            with self.assertRaises(ValueError):authoring.dispatch('run-start',bad)
        self.save(authoring.dispatch('edit-preview',self.edit()))
        with self.assertRaisesRegex(ValueError,'changed'):authoring.dispatch('run-start',c)

    def test_update_recovery_lock_blocks_save(self):
        p=authoring.dispatch('edit-preview',self.edit());before=list(self.state.db.iterdump())
        u=Mock();u.host.support.return_value={'supported':True}
        @contextmanager
        def lock():yield
        u.lock=lock
        with patch('task_relay.app_updates.Updater',return_value=u),patch('task_relay.app_updates.read',return_value={'approved':1,'phase':'needs_attention'}):
            with self.assertRaisesRegex(ValueError,'recovery'):self.save(p)
        self.assertEqual(before,list(self.state.db.iterdump()))


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.env=dict(os.environ,TASK_RELAY_DATA_DIR=str(self.root/'data'),TASK_RELAY_WORKSPACE_DIR=str(self.root/'projects'),TASK_RELAY_GENERATED_DIR=str(self.root/'generated'))

    def call(self,action,value=None):
        code='import sys;sys.path.insert(0,sys.argv.pop(1));from task_relay.cli import main;main()'
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),'author',action,'--input','-'],
            input=json.dumps(value or {}),text=True,capture_output=True,cwd=self.root,env=self.env)
        reply=json.loads(result.stdout);self.assertEqual(reply['ok'],result.returncode==0);return reply

    def test_commands_schema_and_registry_discovery_without_data_or_code_writes(self):
        for action,value in [('commands',{}),('commands',{'command':'edit-save'}),('schema',{}),('operations',{'query':'blender'}),('operation',{'id':'blender.animate'}),('jobs',{})]:
            reply=self.call(action,value);self.assertTrue(reply['ok'],reply)
        self.assertFalse((self.root/'data').exists())

    def test_create_edit_round_trip_from_arbitrary_directory(self):
        w=json.loads((ROOT/'examples/reusable-summary.workflow.json').read_text())
        p=self.call('edit-preview',dict(target=dict(kind='new',id=None,revision=None),title='Portable authoring',workflow=w,request='Save this exact workflow.'))
        self.assertTrue(p['ok'],p);p=p['result']
        settings={k:p[k] for k in ('proposal','fingerprint')}
        saved=self.call('edit-save',settings);self.assertTrue(saved['ok'],saved)
        retry=self.call('edit-save',settings);self.assertTrue(retry['result']['reused'])
        opened=self.call('open',dict(kind='draft',id=saved['result']['id']))
        self.assertEqual(opened['result']['workflow'],w)
        self.assertFalse((self.root/'data/state.sqlite').exists())

    def test_unsupported_command_and_extra_keys_are_structured_errors(self):
        self.assertFalse(self.call('delete-everything')['ok'])
        self.assertFalse(self.call('jobs',{'hidden_mutation':True})['ok'])
        with self.assertRaisesRegex(ValueError,'finite'):author_cli.decode(b'{"x":NaN}')
        with self.assertRaisesRegex(ValueError,'exceeds'):author_cli.decode(b' '*600001)
