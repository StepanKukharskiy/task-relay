import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from task_relay import gemini
from task_relay import orchestrator_chat as chat
from task_relay import production_control as pc
from task_relay import production_planning as planning
from orchestrator import templates
from orchestrator.runtime import Runtime,file_hash
from tests.test_orchestrator import FakeFactory, pair
from tests import test_task_routing as fixtures


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        # Planning fixtures must not discover the developer's installed providers.
        from orchestrator import worker_capabilities
        discovery=patch.object(worker_capabilities,'capture',side_effect=lambda state,backend,locked=False:[worker_capabilities.entry(backend)])
        discovery.start();self.addCleanup(discovery.stop)
        with self.state.db:
            self.state.put('production-planner-policy',{'backend':pair()['backend']})
        self.factory=FakeFactory()
        self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)

    def tearDown(self):
        fixtures.Tests.tearDown(self)

    request=fixtures.Tests.request

    def action(self,**kwargs):
        return dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                    research_ids=[],planning_only=False,**kwargs)

    def queue(self,ident=1,action=None,text='Write a source-grounded brief. Do not render.'):
        self.request(action or self.action(),text,ident)
        row=self.row(ident)
        self.assertIsNotNone(row,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()[0])
        return row

    def row(self,ident=1):
        return self.state.db.execute('SELECT * FROM production_plans WHERE request_id=?',(ident,)).fetchone()

    def response(self):
        value=pair(gate='User selects the brief',max_attempts=1)
        for task in value['tasks']:
            task['tools']=['files','shell']
            task['limits']={'seconds':600,'tool_calls':60,'output_bytes':100000000}
        return dict(decision='ready',message='One brief and independent review.',
                    input_basis={'mode':'new','artifacts':[]},plan={k:value[k] for k in ('brief','tasks')})

    def ready(self,ident=1,action=None):
        self.queue(ident,action)
        planning.Worker(self.state,lambda *_:(json.dumps(self.response()),{'total_tokens':123})).tick()
        self.assertEqual(self.row(ident)['status'],'ready',self.row(ident)['error'])
        return self.row(ident)

    def click(self,token,verb='start',user=7):
        self.bridge.process({'update_id':90,'callback_query':{'id':'cb','data':f'plan:{verb}:{token}',
            'from':{'id':user},'message':{'chat':{'id':7,'type':'private'}}}})

    def start(self,row):
        self.bridge.flush(False);self.click(row['token'])

    def test_new_plan_corrects_draft_once_without_another_start(self):
        row=self.ready();self.assertIn('2 attempt(s)',planning.preview(row))
        self.start(row)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        first=self.rt.task('production-1','produce')['latest']
        self.factory.finish(first);worker.tick()
        review=self.rt.task('production-1','review')['latest']
        self.factory.finish(review,decision='revise');worker.tick();worker.tick()
        second=self.rt.task('production-1','produce')['latest']
        self.assertNotEqual(first,second)
        self.assertEqual(self.rt.task('production-1','produce')['attempts'],2)
        self.assertTrue(any(i.get('previous_delivery') for i in self.factory.sessions[second]['frozen']['inputs']))
        self.factory.finish(second);worker.tick()
        self.factory.finish(self.rt.task('production-1','review')['latest'],decision='accept');worker.tick()
        self.assertEqual(self.rt.status('production-1')['status'],'awaiting_user')
        self.assertEqual(len(self.factory.calls),4)

    def test_saved_one_attempt_plan_does_not_gain_a_revision(self):
        row=dict(self.queue());payload=json.loads(row['context']);payload['options']['max_attempts']=1
        row['context']=json.dumps(payload);row['options']=json.dumps(payload['options'])
        _,plan=planning.validate_result(json.dumps(self.response()),row)
        self.assertEqual([t['max_attempts'] for t in plan['tasks']],[1,1])

    def test_request_to_review_delivery_once(self):
        row=self.ready()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        call=self.state.db.execute('SELECT * FROM production_plan_calls').fetchone()
        self.assertEqual(json.loads(call['usage'])['total_tokens'],123)
        self.assertEqual(json.loads(call['request'])['original_request'],row['request'])
        self.assertEqual(json.loads(call['request'])['planner_instructions'],planning.PLANNER_SYSTEM)
        self.start(row);self.click(row['token'])
        controls=chat.controls(self.state,'production:production-1:planner-started')
        self.assertEqual(controls['inline_keyboard'][0][0]['text'],'Check status')
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick();worker.tick()
        self.assertEqual(len(self.factory.calls),1)
        self.factory.finish(self.rt.task('production-1','produce')['latest']);worker.tick()
        self.assertEqual(len(self.factory.calls),2)
        self.factory.finish(self.rt.task('production-1','review')['latest'],decision='accept');worker.tick()
        self.assertEqual(self.rt.status('production-1')['status'],'awaiting_user')
        self.assertEqual(self.row()['status'],'started')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertTrue(self.state.db.execute("SELECT 1 FROM media_outbox WHERE event_id LIKE 'production:%'").fetchone())
        frozen=next(iter(self.factory.sessions.values()))['frozen']
        self.assertTrue(any(i['path']=='request/USER-REQUEST.txt' for i in frozen['inputs']))

    def test_each_task_keeps_its_approved_deadline(self):
        row=self.queue(action=self.action(task_seconds=1800))
        response=self.response()
        response['plan']['tasks'][0]['limits']['seconds']=1800
        response['plan']['tasks'][1]['limits']['seconds']=900
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.assertIn('1800 seconds',planning.preview(row));self.assertIn('900 seconds',planning.preview(row))
        self.start(row)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        attempt=self.rt.task('production-1','produce')['latest']
        self.assertEqual(self.factory.sessions[attempt]['frozen']['limits']['seconds'],1800)
        self.factory.finish(attempt);worker.tick()
        review=self.rt.task('production-1','review')['latest']
        self.assertEqual(self.factory.sessions[review]['frozen']['limits']['seconds'],900)
        self.assertEqual(self.factory.sessions[attempt]['frozen']['limits']['seconds'],1800)

    def test_old_plan_ceiling_is_preserved_until_explicit_new_budget(self):
        row=self.queue()
        with self.state.db:
            options=json.loads(row['options']);options['limits']['seconds']=600
            context=json.loads(row['context']);context['options']=options
            from orchestrator.contracts import encoded,digest
            self.state.db.execute("UPDATE production_plans SET status='blocked',options=?,context=?,context_hash=? WHERE id=?",(encoded(options),encoded(context),digest(context),row['id']))
        second=self.queue(2,self.action(parent_id=row['id']))
        self.assertEqual(json.loads(second['options'])['limits']['seconds'],600)
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='blocked' WHERE id=?",(second['id'],))
        third=self.queue(3,self.action(parent_id=second['id'],task_seconds=1800))
        self.assertEqual(json.loads(third['options'])['limits']['seconds'],1800)
        self.assertEqual(json.loads(self.row(1)['options'])['limits']['seconds'],600)
        for value in (True,0,1801):
            with self.assertRaises(ValueError):planning.validate_action(self.action(task_seconds=value),{})

    def test_owner_complete_card_and_channel_are_required(self):
        row=self.ready();self.click(row['token'])
        self.bridge.flush(False);self.click(row['token'],user=8)
        self.assertEqual(self.row()['status'],'ready')
        self.state.channel='messages'
        with self.state.db, self.assertRaisesRegex(ValueError,'original channel'):
            self.state.db.execute('BEGIN IMMEDIATE')
            planning.apply(self.state,row['token'],'start')
        del self.state.channel
        self.assertEqual(len(self.factory.calls),0)

    def test_application_evidence_reaches_planner_without_launch(self):
        apps=[{'id':'blender','available':True,'executable':'/fixture/blender'}]
        with patch('task_relay.host_apps.catalog',return_value=apps):
            row=self.queue(text='Run Blender and return a native scene and a preview.')
        context=json.loads(row['context'])
        self.assertEqual(context['host_applications'],apps)
        self.assertEqual(self.factory.calls,[])

    def test_planning_only_requires_new_explicit_authorization(self):
        action=self.action();action['planning_only']=True
        row=self.ready(action=action);self.start(row)
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(len(planning.controls(self.state,row['event_id'])['inline_keyboard'][0]),1)
        self.request({'kind':'authorize_production_plan','plan_id':row['id']},'Run that saved plan.',2)
        new=self.row();self.assertNotEqual(row['token'],new['token'])
        self.bridge.flush(False);self.click(row['token']);self.assertEqual(self.row()['status'],'ready')
        self.click(new['token']);self.assertEqual(self.row()['status'],'started')

    def test_one_structural_correction_preserves_both_calls(self):
        self.queue();received=[]
        def generate(row,payload):
            received.append(payload)
            return ('not JSON' if len(received)==1 else json.dumps(self.response())),{'calls':len(received)}
        worker=planning.Worker(self.state,generate);worker.tick();worker.tick();worker.tick()
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(len(received),2)
        self.assertEqual(received[1]['structural_correction']['previous_response'],'not JSON')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plan_calls').fetchone()[0],2)

    def test_invalid_second_response_stops_and_restart_does_not_retry(self):
        self.queue();generator=lambda *_:('invalid',{})
        worker=planning.Worker(self.state,generator);worker.tick();worker.tick()
        with patch.object(planning,'generate') as call:
            planning.Worker(self.state,call).tick();call.assert_not_called()
        self.assertEqual(self.row()['status'],'blocked');self.assertEqual(self.row()['calls'],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_interrupted_submission_is_not_replayed(self):
        self.queue()
        def interrupt(*_):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):planning.Worker(self.state,interrupt).tick()
        with patch.object(planning,'generate') as call:
            planning.Worker(self.state,call).tick();call.assert_not_called()
        self.assertEqual(self.row()['status'],'uncertain')
        self.assertEqual(self.row()['calls'],1)

    def test_changed_source_and_context_prevent_start(self):
        row=self.ready();payload=json.loads(row['context'])
        source=self.rt.artifact(payload['sources'][0]['artifact']);blob=Path(source['blob'])
        blob.chmod(0o600);blob.write_text('changed')
        self.start(row);self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        with self.state.db:self.state.db.execute("UPDATE production_plans SET context_hash='wrong'")
        with self.state.db,self.assertRaisesRegex(ValueError,'saved plan or inputs changed'):
            self.state.db.execute('BEGIN IMMEDIATE')
            planning.apply(self.state,row['token'],'start')

    def test_graph_sources_tools_budgets_and_review_are_checked(self):
        row=self.queue(action=self.action(task_seconds=600))
        cases=[]
        bad=self.response();bad['plan']['tasks'][0]['limits']['seconds']=601;cases.append(bad)
        bad=self.response();bad['plan']['tasks'][0]['tools']=['web'];cases.append(bad)
        bad=self.response();bad['plan']['tasks'][1]['inputs']=[];cases.append(bad)
        bad=self.response();bad['plan']['tasks'][0]['dependencies']=['review'];cases.append(bad)
        bad=self.response();bad['plan']['tasks'][0]['inputs']=[dict(artifact='unknown',path='x',purpose='x',authority='x')];cases.append(bad)
        bad=self.response();bad['plan']['tasks'][0]['max_attempts']=3;cases.append(bad)
        for value in cases:
            with self.subTest(value=value),self.assertRaises((ValueError,KeyError)):
                planning.validate_result(json.dumps(value),row)

    def test_legacy_request_keeps_job_identity_without_new_metadata(self):
        row=dict(self.queue());payload=json.loads(row['context'])
        payload['options'].pop('job_request_id')
        row['context']=json.dumps(payload)
        _,validated=planning.validate_result(json.dumps(self.response()),row)
        self.assertEqual(validated['origin']['job_request_id'],row['request_id'])

    def test_text_plan_recovers_after_restart_and_delivers_once(self):
        from task_relay.bridge import State, Bridge
        row=self.ready();self.start(row)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        producer=self.rt.task('production-1','produce')['latest']
        # Reopen durable state while the detached producer is still running.
        worker.close();self.state.db.close()
        self.state=State(self.root/'state.sqlite')
        self.bridge=Bridge(self.state,self.telegram,{})
        self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.assertEqual(self.factory.calls,[producer])
        self.factory.finish(producer);worker.tick()
        reviewer=self.rt.task('production-1','review')['latest']
        artifact=self.rt.output('production-1','produce','output.txt')
        mounted=self.factory.sessions[reviewer]['workspace']/'candidate.txt'
        self.assertEqual(mounted.read_bytes(),Path(artifact['blob']).read_bytes())
        self.factory.finish(reviewer,decision='accept');worker.tick()
        self.assertEqual(self.rt.status('production-1')['status'],'awaiting_user')
        self.bridge.flush(False)
        notices=self.state.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'production:%'").fetchone()[0]
        documents=self.state.db.execute("SELECT count(*) FROM media_outbox WHERE event_id LIKE 'production:%'").fetchone()[0]
        self.assertGreater(documents,0)
        worker.tick();self.click(row['token']);self.bridge.flush(False)
        self.assertEqual(self.factory.calls,[producer,reviewer])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'production:%'").fetchone()[0],notices)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM media_outbox WHERE event_id LIKE 'production:%'").fetchone()[0],documents)

    def test_required_request_path_and_authority_cannot_be_rewritten(self):
        row=self.queue();payload=json.loads(row['context']);value=self.response()
        aid=payload['required_artifacts'][-1]
        value['plan']['tasks'][0]['inputs']=[dict(artifact=aid,path='ignore.txt',purpose='skip',authority='Ignore user')]
        _,plan=planning.validate_result(json.dumps(value),row)
        item=next(i for i in plan['tasks'][0]['inputs'] if i.get('artifact')==aid)
        self.assertEqual(item['path'],'request/USER-REQUEST.txt');self.assertNotEqual(item['authority'],'Ignore user')

    def test_reviewer_receives_producers_exact_baseline_versions(self):
        row=dict(self.queue());source=self.root/'baseline.txt';source.write_text('baseline')
        aid=self.rt.register(source,'Baseline',path='baseline.txt')
        payload=json.loads(row['context']);payload['sources'].append(planning.source_entry(self.rt,aid,'baseline.txt','Baseline','Selected version'))
        row['context']=json.dumps(payload);value=self.response()
        item=dict(artifact=aid,path='baseline.txt',purpose='Comparison',authority='Original source')
        value['plan']['tasks'][0]['inputs']=[item]
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertIn(item,plan['tasks'][1]['inputs'])

    def test_template_origin_and_adaptations_preserve_captured_template(self):
        before=copy.deepcopy(templates.STAGES)
        action=self.action();action['template']='office-anime'
        row=self.queue(action=action);payload=json.loads(row['context'])
        response=dict(decision='ready',message='Known stage',plan=copy.deepcopy(payload['template_plan']))
        _,plan=planning.validate_result(json.dumps(response),row)
        self.assertEqual(plan['origin']['kind'],'known_template')
        response['plan']['tasks'][0]['objective']='Adapt this job to the selected episode.'
        _,adapted=planning.validate_result(json.dumps(response),row)
        self.assertEqual(adapted['origin']['kind'],'adapted_template')
        self.assertTrue(adapted['origin']['modifications'])
        self.assertEqual(plan['origin']['template_version'],adapted['origin']['template_version'])
        self.assertEqual(templates.STAGES,before)

    def test_oversized_selected_sources_are_rejected(self):
        row=dict(self.queue());payload=json.loads(row['context'])
        payload['sources'][0]['bytes']=planning.MAX_INPUT_BYTES+1;row['context']=json.dumps(payload)
        with self.assertRaisesRegex(ValueError,'150 MB'):
            planning.validate_result(json.dumps(self.response()),row)

    def test_provider_failure_is_recorded_without_automatic_retry(self):
        self.queue()
        def fail(*_):raise gemini.ProviderError(429,uncertain=False)
        worker=planning.Worker(self.state,fail);worker.tick()
        self.assertEqual(self.row()['status'],'blocked')
        self.assertIn('429',self.row()['error'])
        with patch.object(planning,'generate') as call:
            planning.Worker(self.state,call).tick();call.assert_not_called()

    def test_saved_instruction_version_is_not_replaced_on_restart(self):
        row=self.queue();before=json.loads(row['context'])['planner_instructions'];seen=[]
        def generator(row,payload):seen.append(payload['planner_instructions']);return json.dumps(self.response()),{}
        with patch.object(planning,'PLANNER_SYSTEM','Changed system prompt'):
            planning.Worker(self.state,generator).tick()
        self.assertEqual(seen,[before])

    def test_selected_pack_keeps_all_dependencies_without_copying_again(self):
        entries=[];versions=[]
        for name in ('index.html','nested/scene.html','GUIDE.md'):
            path=self.root/name;path.parent.mkdir(exist_ok=True);path.write_text(name)
            aid=self.rt.register(path,'Selected source',path=name)
            entry=planning.source_entry(self.rt,aid,name,'Selected source','Selected guide or dependency')
            versions.append(entry);entries.append({k:entry[k] for k in ('artifact','path','purpose','authority')})
        manifest=self.root/'manifest.json';manifest.write_text(json.dumps({'inputs':entries,'files':versions}))
        with self.state.db:
            self.state.db.execute('INSERT INTO reference_packs(id,job_id,token,project,request,status,manifest,manifest_sha256,created,expires) VALUES (?,?,?,?,?,?,?,?,?,?)',
                ('pack',0,'pack-token',str(self.root),'Selected production','ready',str(manifest),file_hash(manifest),time.time(),time.time()+1000))
        action=self.action();action['reference_pack_id']='pack'
        row=self.queue(action=action);_,plan=planning.validate_result(json.dumps(self.response()),row)
        ids={e['artifact'] for e in entries}
        for task in plan['tasks']:self.assertTrue(ids<={i.get('artifact') for i in task['inputs']})
        for source in versions:
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_artifacts WHERE sha256=?',(source['sha256'],)).fetchone()[0],1)
        with self.state.db:
            self.state.db.execute('UPDATE production_artifacts SET bytes=bytes+1 WHERE id=?',(entries[0]['artifact'],))
        with self.state.db,self.assertRaisesRegex(ValueError,'artifact version changed'):
            planning.enqueue(self.state,{'id':2,'prompt':'Same selected pack','provider':'gemini','model':'fixture'},action,
                             {'reference_packs':[{'id':'pack','status':'ready'}]})

    def test_clarification_preserves_original_and_supersedes_prior_version(self):
        self.queue(text='Use my selected story. No rendering.')
        planning.Worker(self.state,lambda *_:(json.dumps(dict(decision='needs_input',message='Which audience?',plan=None)),{})).tick()
        old=self.row();self.assertEqual(old['status'],'needs_input')
        self.bridge.flush(False)
        mid=self.state.db.execute('SELECT message_id FROM production_plan_messages WHERE plan_id=?',(old['id'],)).fetchone()[0]
        self.bridge.process({'update_id':2,'message':{'text':'Technical builders.','reply_to_message':{'message_id':mid},
            'chat':{'id':7,'type':'private'},'from':{'id':7}}})
        received=[]
        def reply(job,payload):
            received.append(payload)
            return json.dumps({'answer':'Updated scope.','action':self.action(parent_id=old['id'])})
        chat.Worker(self.state,reply).tick()
        self.assertEqual(received[0]['reply_plan_id'],old['id'])
        self.assertEqual(self.row()['status'],'superseded')
        self.assertIn('Use my selected story. No rendering.',self.row(2)['request'])
        self.assertTrue(self.row(2)['request'].endswith('Technical builders.'))

    def test_pending_reply_blocks_old_start_until_interpreted(self):
        row=self.ready();self.bridge.flush(False)
        mid=self.state.db.execute('SELECT message_id FROM production_plan_messages').fetchone()[0]
        self.bridge.process({'update_id':2,'message':{'text':'How many workers would this start?','reply_to_message':{'message_id':mid},
            'chat':{'id':7,'type':'private'},'from':{'id':7}}})
        self.click(row['token']);self.assertEqual(self.row()['status'],'ready')
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Two workers, with the reviewer waiting for the producer.','action':None})).tick()
        self.click(row['token']);self.assertEqual(self.row()['status'],'started')

    def test_registration_failure_rolls_back_everything(self):
        row=self.ready();self.bridge.flush(False)
        original=Runtime.create
        def fail(rt,plan):original(rt,plan);raise ValueError('Injected after registration')
        with patch.object(Runtime,'create',fail):self.click(row['token'])
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertIsNone(self.state.get('production-enabled:production-1'))
        self.click(row['token']);self.assertEqual(self.row()['status'],'started')


if __name__=='__main__':unittest.main()
