"""Definitive rejected-request recovery, without replay or new authorization."""
import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from task_relay import completion_recovery as recovery
from orchestrator import gemini_worker
from tests import test_completion_recovery as recovery_fixtures
from tests.test_orchestrator import pair
from orchestrator.storage import transaction

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.rt=SimpleNamespace(root=self.root)
        self.attempt=dict(id='failed',task='catalog',frozen=json.dumps(dict(backend={'type':'gemini-agent','model':'fixture'},operation_contract={'id':'sourcing.options','version':1,'parameters':{}},runtime_sources={'gemini_worker.py':'old-adapter-hash'})))
        self.receipt=dict(status='finished',external_outcome='no_pending_response',pending_requests=[],tool_calls=0,api_requests=1)
        self.control=self.root/'workers/failed';self.control.mkdir(parents=True)
        self.request=dict(provider='gemini',model='fixture',payload={'tools':[{'functionDeclarations':[dict(name='operation_submit',parametersJsonSchema={'properties':{'records':{'type':'array'}}})]}]})
        (self.control/'api-01.request.json').write_text(json.dumps(self.request))
        (self.control/'api-01.outcome.json').write_text(json.dumps(dict(outcome='rejected',http_status=400)))

    def test_exact_changed_adapter_rejection_supplies_auditable_gap(self):
        gap=recovery.schema_repair_gap(self.rt,self.attempt,self.receipt)
        self.assertEqual(gap['kind'],'provider_schema_repair');self.assertEqual(gap['changed_tools'],['operation_submit'])
        self.assertEqual(len(gap['rejected_request_sha256']),64)
        self.assertFalse(list(self.control.glob('api-*.response.json')))

    def test_uncertain_generated_executed_or_unchanged_requests_cannot_recover(self):
        for patch in (dict(external_outcome='unknown'),dict(pending_requests=['call']),dict(tool_calls=1),dict(api_requests=2),dict(status='running')):
            with self.subTest(patch=patch):self.assertIsNone(recovery.schema_repair_gap(self.rt,self.attempt,{**self.receipt,**patch}))
        frozen=json.loads(self.attempt['frozen']);frozen['runtime_sources']['gemini_worker.py']=__import__('hashlib').sha256(Path(gemini_worker.__file__).read_bytes()).hexdigest()
        self.assertIsNone(recovery.schema_repair_gap(self.rt,{**self.attempt,'frozen':json.dumps(frozen)},self.receipt))
        (self.control/'api-01.response.json').write_text('{}')
        self.assertIsNone(recovery.schema_repair_gap(self.rt,self.attempt,self.receipt))

    def test_other_errors_wrong_identity_and_current_wire_stay_held(self):
        for status in (429,500):
            (self.control/'api-01.outcome.json').write_text(json.dumps(dict(outcome='rejected',http_status=status)))
            self.assertIsNone(recovery.schema_repair_gap(self.rt,self.attempt,self.receipt))
        (self.control/'api-01.outcome.json').write_text(json.dumps(dict(outcome='rejected',http_status=400)))
        for change in (dict(model='different'),dict(payload={'tools':[{'functionDeclarations':[dict(name='operation_submit',parameters={'properties':{'records_json':{'type':'string'}}})]}]})):
            (self.control/'api-01.request.json').write_text(json.dumps({**self.request,**change}))
            self.assertIsNone(recovery.schema_repair_gap(self.rt,self.attempt,self.receipt))

class Integration(unittest.TestCase):
    setUp=recovery_fixtures.Tests.setUp
    tearDown=recovery_fixtures.Tests.tearDown
    request=recovery_fixtures.Tests.request
    stage=recovery_fixtures.Tests.stage
    create=recovery_fixtures.Tests.create
    step=recovery_fixtures.Tests.step
    prepare=recovery_fixtures.Tests.prepare
    # Reuse native runtime fixtures, not inherited unrelated checks.
    def test_rejected_schema_recovery_uses_existing_grant_and_keeps_attempt(self):
        p,s=self.prepare();plan=pair(max_attempts=1);plan['id']='parent';self.rt.create(plan);self.rt.tick('parent')
        attempt=self.rt.task('parent','produce')['latest']
        receipt=dict(status='finished',exit_code=1,reason='ProviderError: rejected schema',pending_requests=[],external_outcome='no_pending_response',tool_calls=0,api_requests=1)
        self.factory.sessions[attempt]['status']=receipt;self.rt.tick('parent')
        row=dict(self.state.db.execute('select * from production_attempts where id=?',(attempt,)).fetchone())
        frozen=json.loads(row['frozen']);frozen.update(backend={'type':'gemini-agent','model':'fixture'},operation_contract={'id':'sourcing.options','version':1,'parameters':{}},runtime_sources={'gemini_worker.py':'old-adapter-hash'})
        control=self.rt.root/'workers'/attempt;control.mkdir(parents=True,exist_ok=True)
        (control/'api-01.request.json').write_text(json.dumps(dict(provider='gemini',model='fixture',payload={'tools':[{'functionDeclarations':[dict(name='operation_submit',parametersJsonSchema={'properties':{'records':{'type':'array'}}})]}]})))
        (control/'api-01.outcome.json').write_text(json.dumps(dict(outcome='rejected',http_status=400)))
        with transaction(self.state.db):self.state.db.execute('update production_attempts set frozen=? where id=?',(json.dumps(frozen),attempt))
        baseline=recovery.snapshot(self.state,'parent');self.assertEqual(baseline['gaps'][0]['kind'],'provider_schema_repair')
        before=list(self.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.rt.task('parent','produce')['latest'],attempt);self.assertEqual(self.rt.task('parent','produce')['attempts'],1);self.assertEqual(before,self.factory.calls)
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.state.db.execute('select count(*) from completion_recoveries').fetchone()[0],1)
