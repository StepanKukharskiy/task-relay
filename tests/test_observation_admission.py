"""Controlled shared receipt and native read failures; no browser or provider."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_source_recovery_policy import Handoff
from tests.test_native_source_browser import Tests as NativeBase,Helper
from task_relay.external_evidence import recorded_sources
from task_relay.host_computer import NativeSessionError
from task_relay import computer_contract as contract
from orchestrator.runtime import Runtime
from orchestrator.runtime_outcomes import UncertainOperation

class Admission(Handoff):
    def execute_operation(self,ident,renderer,*,native=False):
        from orchestrator import step_runner
        self.rt.tick('job');state=self.factory.sessions[self.rt.task('job',ident)['latest']]
        control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        with patch('task_relay.source_browser.render',side_effect=renderer):
            result=step_runner.execute(state['frozen'],control)
        # Transport fixture returns the actual registered operation receipt.
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[],operation=result)
        self.rt.tick('job');return result,control

    def qualify(self,inline):
        ref,artifact=self.begin(inline=inline)
        state=self.rt.task('job','read')['status'];count=len(self.factory.calls)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        source=dict(artifact=artifact['id'],sha256=artifact['sha256'],bytes=artifact['bytes'])
        proof=recorded_sources(self.rt,[source],allow_empty=True)
        self.assertEqual(len(proof),1);self.assertEqual(proof[0]['origin_artifact'],artifact['id'])
        self.assertEqual(self.rt.task('job','read')['status'],state)
        self.assertEqual(len(self.factory.calls),count)
        row=self.rt.db.execute('select frozen,session from production_attempts where id=?',(artifact['attempt'],)).fetchone()
        frozen=json.loads(row['frozen']);control=Path(json.loads(row['session'])['control'])
        # Exact retained envelope cannot substitute for the underlying receipt.
        receipt=control/'work-operations/0001/operation-materialized.json' if inline else control/'operation-materialized.json'
        original=receipt.read_bytes();receipt.write_text('{}')
        with self.assertRaises((ValueError,UncertainOperation)):recorded_sources(self.rt,[source],allow_empty=True)
        receipt.write_bytes(original)
        self.rt.db.execute("update production_attempts set state='uncertain' where id=?",(artifact['attempt'],))
        self.assertEqual(recorded_sources(self.rt,[source],allow_empty=True),[])
        return frozen

    def test_inline_blocked_producer_admits_exact_committed_source(self):self.qualify(True)
    def test_standalone_source_admission_survives_restart(self):
        # Legacy standalone admission is separately covered; committed projection
        # must verify its original operation before recovery selection.
        ref,artifact=self.begin()
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        source=dict(artifact=artifact['id'],sha256=artifact['sha256'],bytes=artifact['bytes'])
        self.assertEqual(len(recorded_sources(self.rt,[source],allow_empty=True)),1)
        from orchestrator.evidence_recovery import committed
        self.assertEqual(len(list(committed(self.rt,artifact))),1)

    def test_completed_inline_producer_and_alias_use_same_receipt(self):
        _,artifact=self.begin(inline=True)
        self.rt.db.execute("update production_attempts set state='completed' where id=?",(artifact['attempt'],))
        source=dict(artifact='selected-byte-alias',sha256=artifact['sha256'],bytes=artifact['bytes'])
        self.assertEqual(recorded_sources(self.rt,[source],allow_empty=True)[0]['artifact'],'selected-byte-alias')

class Native(NativeBase):
    from tests.test_browser_fallback_lifecycle import retain_evidence as tearDown
    def helper_failure(self,change=None):
        helper=Helper(self.root);original=helper.call
        def reply(request):
            if request['operation']!='observe':return original(request)
            helper.calls.append(request)
            value=dict(protocol=contract.PROTOCOL,ok=False,error='selected_document_url_changed_or_unavailable',
                observation_failure=dict(version=1,terminal=True,operation='observe',requested_url=request['observation_request']['expected_url'],
                    target=request['observation_request']['target'],token=request['token'],action_executed=False))
            if change:change(value)
            raise NativeSessionError(value['error'],value)
        helper.call=reply
        return helper

    def test_confirmed_read_failure_preserves_prior_capture_and_is_not_replayed(self):
        helper=self.helper_failure()
        with self.assertRaisesRegex(ValueError,'confirmed failure'):self.read(helper)
        state=json.loads((self.root/'native-receipts.json').read_text())
        self.assertEqual([a['state'] for a in state['actions']],['completed','failed'])
        receipt=json.loads(state['actions'][0]['receipt'])
        self.assertTrue((Path(receipt['folder'])/'page.txt').read_text())
        with self.assertRaisesRegex(ValueError,'confirmed failure'):self.read(helper)
        self.assertEqual(len(helper.calls),2)
        failure=json.loads(state['actions'][1]['receipt']);(Path(failure['folder'])/'rejection.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):self.read(helper)

    def test_confirmed_failure_allows_other_source_and_retains_original_receipts(self):
        from contextlib import nullcontext
        from task_relay import source_native_browser as host
        from orchestrator.source_fallback import collect
        from tests.test_native_source_browser import binding,pack,URL
        source=pack();source['entries'].append(dict(query='another unresolved item',target_ids=['B'],pages=[],retrievals=[dict(url='https://other.example/item',outcome='failed')]))
        before=copy.deepcopy(source);readers=[]
        def render(url,domains,root):
            if url==URL:
                saved=self.root;self.root=Path(root);helper=self.helper_failure();self.root=saved
            else:helper=Helper(Path(root))
            readers.append(helper)
            return host.render(url,domains,root,binding=binding(),max_observations=2,helper=helper,lease_context=nullcontext,wait=lambda _:None)
        result,stats=collect(source,[],2,self.root/'batch',render,read_policy=binding())
        value=json.loads(result)
        self.assertEqual(value['entries'][:len(before['entries'])],before['entries'])
        self.assertEqual(stats['rendered'],1);self.assertEqual(len(readers),2)
        self.assertEqual([len(h.calls) for h in readers],[2,2])
        again=collect(source,[],2,self.root/'batch',lambda *_:self.fail('No replay'),read_policy=binding())
        self.assertEqual(again,(result,stats))
        self.assertEqual(len(list((self.root/'batch').rglob('rejection.json'))),1)

    def test_uncorrelated_read_failure_remains_uncertain(self):
        helper=self.helper_failure(lambda v:v['observation_failure'].update(token='foreign'))
        with self.assertRaises(UncertainOperation):self.read(helper)
        self.assertFalse((self.root/'render-outcome.json').exists())
        with self.assertRaises(UncertainOperation):self.read(helper)
        self.assertEqual(len(helper.calls),2)

    def test_late_same_origin_observation_retains_actual_url_and_no_navigation_replay(self):
        from tests.test_native_source_browser import URL
        helper=Helper(self.root);original=helper.call
        def reply(request):
            value=original(request)
            if request['operation']!='launch':value['observation']['url']=URL+'/canonical'
            return value
        with patch.object(helper,'call',side_effect=reply):value=self.read(helper)
        self.assertEqual(value['requested_url'],URL);self.assertEqual(value['url'],URL+'/canonical')
        self.assertEqual([c['operation'] for c in helper.calls],['launch','observe','scroll','scroll'])
        self.assertEqual(helper.calls[2]['observation_request']['expected_url'],URL+'/canonical')
        self.assertEqual(self.read(),value)

    def test_navigation_failure_cannot_claim_observation_no_effect(self):
        helper=self.helper_failure(lambda v:v['observation_failure'].update(operation='navigate',action_executed=True))
        with self.assertRaises(UncertainOperation):self.read(helper)

class Consumer(Admission):
    def create(self,inputs):
        from tests.test_owner_intents import Tests
        self.inventory=self.source(json.dumps(dict(items=[dict(id='part',label='Part')])),'inventory.json','application/json')
        return Tests.create(self,inputs=[*inputs,self.inventory])

    def test_content_admission_reuses_inline_receipt_without_dispatching_another_read(self):
        self.grant.update(coordination_version=1,owner_progress_version=1)
        original,richer=self.begin(inline=True)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        task=dict(id='consume',objective='Use retained observations',content=dict(family='collection.options',
            sources=dict(inventory_path=dict(artifact=self.inventory['artifact']),source_pack_path=dict(artifact=original['artifact'])),
            parameters=dict(field_definitions={'name':'text'},identity_field='name',max_records=1,options_per_item=1,count_policy='target')))
        before=len(self.factory.calls)
        self.session().delegate(dict(request_id='consume',tasks=[task]))
        spec=self.rt.spec(self.rt.task('job','consume'))
        from orchestrator.worker_capabilities import backend_for
        plan=json.loads(self.rt.db.execute("select plan from production_runs where id='job'").fetchone()[0])
        inputs=self.rt.checked_inputs('job',spec,backend_for(spec,plan['backend']))
        selected=next(i for i in inputs if i['artifact']==richer['id'])
        self.assertEqual(selected['sourcing_source_receipt']['origin_artifact'],richer['id'])
        self.assertEqual(len(self.factory.calls),before)
        self.assertEqual(self.rt.task('job','read')['status'],'blocked')
