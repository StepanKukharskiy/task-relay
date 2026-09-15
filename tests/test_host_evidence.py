import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from task_relay.bridge import State
from task_relay.host_evidence import application_signature,record_check,environments
from orchestrator.runtime import file_hash


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.state=State(self.root/'state.sqlite');self.appfile=self.root/'blender';self.appfile.write_text('executable fixture')
        self.app={'available':True,'executable':str(self.appfile)}

    def tearDown(self):self.state.db.close();self.tmp.cleanup()

    def receipt(self,name='receipt.json',success=True):
        d={'host_execution':True,'capability':'blender.startup','recorded_at':time.time(),
           'application_signature':application_signature(self.appfile),
           'runtime_sources':{n:file_hash(Path('orchestrator')/n) for n in ('blender_host.py','blender_scene.py')},
           'runs':[{'returncode':0 if success else -11,'timeout':False,'stdout':'BLENDER_STARTUP_OK 5.1.2' if success else ''}]}
        p=self.root/name;p.write_text(json.dumps(d));return p

    def test_controlled_success_is_visible_without_rewriting_old_production(self):
        p=self.receipt()
        with self.state.db:record_check(self.state,p)
        current=environments(self.state,self.app)['registered_host']
        self.assertEqual(current['startup_status'],'passed')
        self.assertIn('Controlled',current['latest_check']['evidence_kind'])
        self.assertEqual(self.state.db.execute('select count(*) from production_attempts').fetchone()[0],0)

    def test_diagnostic_completion_does_not_mean_startup_success(self):
        with self.state.db:record_check(self.state,self.receipt(success=False))
        self.assertEqual(environments(self.state,self.app)['registered_host']['startup_status'],'failed')

    def test_changed_executable_or_tampered_receipt_is_not_current_evidence(self):
        p=self.receipt()
        with self.state.db:record_check(self.state,p)
        self.appfile.write_text('new version')
        self.assertEqual(environments(self.state,self.app)['registered_host']['startup_status'],'unverified')
        p.write_text('{}')
        self.assertEqual(environments(self.state,self.app)['registered_host']['recent_checks'],[])

    def test_newer_matching_failure_supersedes_success(self):
        with self.state.db:
            record_check(self.state,self.receipt('one.json'));record_check(self.state,self.receipt('two.json',False))
        self.assertEqual(environments(self.state,self.app)['registered_host']['startup_status'],'failed')

    def test_old_runtime_is_historical_and_import_is_idempotent(self):
        p=self.receipt();d=json.loads(p.read_text());d['runtime_sources']['blender_scene.py']='older';p.write_text(json.dumps(d))
        with self.state.db:record_check(self.state,p);record_check(self.state,p)
        self.assertEqual(len(self.state.get('host-checks:blender')),1)
        host=environments(self.state,self.app)['registered_host']
        self.assertEqual(host['startup_status'],'unverified');self.assertFalse(host['recent_checks'][0]['current_environment_match'])

if __name__=='__main__':unittest.main()
