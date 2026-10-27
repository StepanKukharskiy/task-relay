"""Decision metadata → real owner tool loop and admission; no paid calls."""
import copy,json,unittest
from pathlib import Path
from orchestrator import owner_decision,job_owner,owner_intents,working_context,executors,worker_capabilities
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from tests import test_owner_compilation as fixture
from tests.test_operation_session import CONFIG

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    create=fixture.Tests.create
    source=fixture.Tests.source
    session=fixture.Tests.session

    def setup_job(self):
        self.grant.update(operations=['pptx.create','pptx.render'],deliverables={'deck':'application/vnd.openxmlformats-officedocument.presentationml.presentation','pdf':'application/pdf'})
        self.grant['task_limits'].update(tool_calls=24,provider_requests=24,output_bytes=20000000,seconds=600)
        self.grant['workers'].append(worker_capabilities.entry(dict(type='gemini-code',model='fixture',runtime='a'*64)))
        ref=self.source('WORKER-ONLY EVIDENCE '*2000)
        self.create(request='Exact request: produce an editable deck and PDF.',inputs=[ref]);self.rt.tick('job')
        return ref,self.session()

    def test_first_response_can_delegate_from_supplied_route_without_catalog_or_file_reads(self):
        ref,s=self.setup_job();outer=self;seen=[]
        class Model:
            def request(self,endpoint,payload,**kwargs):
                seen.append(payload)
                outer.assertEqual(len(seen),1,payload['contents'][-1])
                initial=json.loads(payload['contents'][0]['parts'][0]['text'])
                outer.assertEqual(initial['request'],'Exact request: produce an editable deck and PDF.')
                states=[json.loads(p['text'][len(working_context.STATE_PREFIX):]) for m in payload['contents'] for p in m.get('parts',[]) if p.get('text','').startswith(working_context.STATE_PREFIX)]
                brief=states[-1]['decision_brief'];route=next(r for r in brief['work_routes'] if r['available'] and r['work'].get('mode')=='create')
                outer.assertNotIn('WORKER-ONLY EVIDENCE',json.dumps(payload))
                outer.assertEqual(brief['available_inputs'][0]['ref'],dict(artifact=ref['artifact']))
                task=dict(id='make',objective='Produce the requested files; inspect and correct them',inputs=[i['ref'] for i in brief['available_inputs']],work=route['work'])
                return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(functionCall=dict(name='job_delegate',args=dict(request_id='direct',tasks=[task])))]))])
        control=s.control
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,s.frozen['backend'])))
        result=execute(s.frozen,control,client=Model(),config_reader=lambda:(CONFIG,s.frozen['backend']))
        self.assertEqual(result['outcome'],'yielded');self.assertEqual(len(seen),1)
        self.rt.tick('job');child=self.factory.sessions[self.rt.task('job','make')['latest']]['frozen']
        self.assertEqual(child['inputs'][0]['artifact'],ref['artifact'])
        self.assertIn('WORKER-ONLY EVIDENCE',(Path(child['workspace'])/child['inputs'][0]['path']).read_text())
        self.assertEqual(len(list(control.glob('tool-*.json'))),1)

    def test_brief_and_catalog_expose_explicit_modes_without_inventing_input_refs(self):
        _,session=self.setup_job()
        rows=[r for r in session.snapshot()['decision_brief']['work_routes'] if r['available']]
        self.assertEqual({r['work']['mode'] for r in rows},{'execute','create','revise'})
        for row in rows:
            mode=row['work']['mode']
            self.assertEqual(row['required_reference'],{'execute':'data','create':None,'revise':'baseline'}[mode])
            self.assertNotIn('data',row['work']);self.assertNotIn('baseline',row['work'])
        catalog=owner_intents.catalog(session.grant,['pptx.create'])['operations']['pptx.create']['worker_work']
        self.assertEqual(set(catalog['modes']),{r['work']['mode'] for r in rows})
        self.assertIn('Declare work.mode',session.frozen['instruction'])
        self.assertIn('repairs:[finding IDs]',session.frozen['instruction'])

    def test_findings_name_only_authorized_exact_evidence_and_remain_unaccepted(self):
        ref,s=self.setup_job();state=s.snapshot();raw='Full worker evidence '*1000
        issue=dict(id='finding',review_attempt=s.frozen['assignment_id'],issue=dict(message='Restore the missing image',evidence=raw))
        before=copy.deepcopy(s.grant)
        # build expects the legacy state artifact index; snapshot projects it out.
        state['artifacts']=[]
        brief=owner_decision.build(s,state,[issue])
        self.assertEqual(brief['findings'][0]['relevant_inputs'],[dict(artifact=ref['artifact'])])
        self.assertNotIn(raw,json.dumps(brief));self.assertEqual(s.grant,before)
        self.assertIn('correction',brief['next_action'])
        self.assertLess(len(json.dumps(brief)),6000)
        self.assertNotIn('sha256',json.dumps(brief));self.assertNotIn('prior/input.txt',json.dumps(brief))

    def test_pending_rejection_and_uncertainty_take_priority_over_new_work(self):
        _,s=self.setup_job();state=s.snapshot();state['artifacts']=[]
        state['tasks']=[dict(id='effect',status='uncertain',failure=dict(reason='Missing receipt'))]
        self.assertIn('do not resubmit',owner_decision.build(s,state,[])['next_action'])
        s.pending_submission=dict(proposal={'request_id':'same'},error='Wrong input')
        self.assertIn('saved proposal',owner_decision.build(s,state,[])['next_action'])
        self.assertEqual(owner_decision.build(s,state,[])['failures'][0]['id'],'effect')

    def test_ungranted_renderer_is_not_advertised_as_usable_work(self):
        _,s=self.setup_job();grant=copy.deepcopy(s.grant);grant['operations'].pop('pptx.render')
        route=owner_decision.routes(grant)[0]
        self.assertFalse(route['available']);self.assertIn('inspection companion',route['reason'])

    def test_route_requires_an_authorized_independent_reviewer(self):
        _,s=self.setup_job();grant=copy.deepcopy(s.grant);grant['workers']=grant['workers'][:1]
        route=owner_decision.routes(grant)[0]
        self.assertFalse(route['available']);self.assertIn('No eligible worker',route['reason'])

    def test_historical_brief_has_no_prospective_policy(self):
        self.grant['delegation_version']=2;self.create();self.rt.tick('job');s=self.session()
        self.assertNotIn('decision_brief_version',s.grant)
        self.assertNotIn('decision_brief',s.snapshot());self.assertIn('inputs',owner_intents.brief(s.frozen))

    def test_wait_hint_uses_same_runnable_boundary_as_scheduler(self):
        _,session=self.setup_job()
        session.delegate(dict(request_id='candidate',tasks=[dict(id='candidate',objective='Produce fixture text',outputs=[dict(name='result',media_type='text/plain',purpose='Fixture')]),dict(id='candidate_review',objective='Review exact fixture',review_of='candidate')]))
        with self.rt.transaction():
            self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE id='candidate'")
        state=session.snapshot()
        self.assertNotIn('job_wait',state['decision_brief']['next_action'])
        self.assertTrue(any(t['status']=='queued' for t in state['tasks']))
        with self.rt.transaction():
            self.rt.db.execute("UPDATE production_tasks SET status='running' WHERE id='candidate'")
        self.assertIn('job_wait',session.snapshot()['decision_brief']['next_action'])
