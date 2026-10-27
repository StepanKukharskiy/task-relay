"""Incomplete owner proposals through common compilation, execution and recovery.

All inputs/models are synthetic. No paid requests or production state changes.
"""
import copy,json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from orchestrator import job_owner,working_context,contracts as c,worker_capabilities
from orchestrator.owner_compilation import label
from tests import test_owner_intents as old
from tests.test_operation_session import Script

class Tests(unittest.TestCase):
    create=old.Tests.create
    source=old.Tests.source
    session=old.Tests.session
    invoke=old.Tests.invoke
    run_worker=old.Tests.run_worker
    def setUp(self):
        old.Tests.setUp(self);self.grant.pop('delegation_version')

    def content(self,count=3,maximum=None,provenance=True):
        refs=[self.source(json.dumps(dict(items=[dict(id='s'+str(i),label='Subject '+str(i)) for i in range(count)])),'subjects.json','application/json'),
              self.source(json.dumps(dict(version=1,entries=[])),'sources.json','application/json')]
        if provenance:
            a=self.rt.artifact(refs[1]['artifact']);receipt=dict(status='finished',operation=dict(output_sha256=a['sha256'],validation=dict(fetched=0)))
            self.rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',('captured','prior','sources','prior','completed',None,c.encoded(dict(execution=dict(capability='web.sources'))),'{}',c.encoded(receipt),None))
            self.rt.db.execute('UPDATE production_artifacts SET attempt=?,path=? WHERE id=?',('captured','delivery/source-pack.json',a['id']))
        task=dict(id='collect',objective='Collect supported alternatives; disclose missing options',content=dict(family='collection.options',
            sources=dict(inventory_path={'artifact':refs[0]['artifact']},source_pack_path={'artifact':refs[1]['artifact']}),
            parameters=dict(field_definitions={'name':'text'},identity_field='name',options_per_item=2,count_policy='target',max_records=maximum or count)))
        return refs,task

    def test_default_compiler_auto_review_actual_delivery_and_idempotent_retry(self):
        self.create();self.rt.tick('job');s=self.session();args=dict(request_id='one',tasks=[old.worker('write')]);before=copy.deepcopy(s.grant)
        first=s.delegate(args);self.assertEqual(first,s.delegate(args));self.assertEqual(s.grant,before)
        self.assertEqual(set(first['queued']),{'write',label('write','review')})
        self.assertEqual(len(self.factory.calls),1)
        with self.assertRaisesRegex(ValueError,'different intent'):s.delegate({**args,'tasks':[old.worker('other')]})
        self.run_worker('write',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='A complete synthetic report.'))])
        self.run_worker(label('write','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=1000)) for i in f['inputs']]+[('file_write',dict(path=f['outputs'][0]['path'],text='Independently inspected.'))],decision='accept')
        artifact=self.rt.output('job','write','outputs/result.txt')
        s.complete(dict(deliverables_json=json.dumps(dict(report=artifact['id'])),summary='Complete exact report'))
        self.assertTrue(s.completed)

    def test_registered_workload_uses_actual_subjects_and_expands_required_review(self):
        refs,task=self.content(count=3,maximum=40);self.create(inputs=refs);self.rt.tick('job');s=self.session()
        receipt=s.delegate(dict(request_id='collect',tasks=[task]));self.assertEqual(len(receipt['queued']),2)
        spec=self.rt.spec(self.rt.task('job','collect'));review=self.rt.spec(self.rt.task('job',label('collect','review')))
        self.assertEqual(spec['operation_contract']['parameters']['max_records'],40)
        self.assertEqual(spec['operation_contract']['parameters']['record_range'],[0,3])
        decisions=json.loads(self.rt.db.execute("SELECT data FROM production_events WHERE kind='owner_compilation_evidence'").fetchone()[0])['decisions']
        workload=next(d for d in decisions if d.get('kind')=='registered_workload')
        self.assertEqual((workload['declared_bound'],workload['actual_units']),(40,3))
        self.assertEqual(workload['sha256'],self.rt.artifact(refs[0]['artifact'])['sha256'])
        self.assertEqual(review['operation_contract']['id'],'collection.review')
        self.assertLessEqual(spec['limits']['provider_requests'],s.grant['task_limits']['provider_requests'])
        self.assertEqual(len(self.factory.calls),1)

    def test_large_workload_partitions_with_existing_compiler_and_frozen_grant(self):
        refs,task=self.content(count=8);self.grant['operations']=['records.merge'];self.create(inputs=refs);self.rt.tick('job');s=self.session()
        receipt=s.delegate(dict(request_id='parts',tasks=[task]));self.assertEqual(len(receipt['queued']),5)
        specs=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id']!='owner']
        merge=next(t for t in specs if t.get('execution'));self.assertEqual(merge['execution']['capability'],'records.merge')
        ranges=[t['operation_contract']['parameters']['record_range'] for t in specs if t.get('operation_contract',{}).get('id')=='collection.options']
        self.assertEqual(ranges,[[0,4],[4,8]])
        self.assertEqual(len([t for t in specs if t.get('review_of')]),2)
        self.assertEqual(s.delegate(dict(request_id='parts',tasks=[task])),receipt)

    def test_partition_workers_reviews_restart_and_native_merge_complete(self):
        from orchestrator.runtime import Runtime
        from orchestrator.step_runner import execute
        refs,task=self.content(count=6);self.grant['operations']=['records.merge'];self.create(inputs=refs);self.rt.tick('job')
        session=self.session();session.delegate(dict(request_id='merge-flow',tasks=[task]))
        specs=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id']!='owner']
        chunks=[t for t in specs if t.get('operation_contract',{}).get('id')=='collection.options']
        for chunk in chunks:
            bounds=chunk['operation_contract']['parameters']['record_range']
            self.run_worker(chunk['id'],lambda f:[('operation_submit',dict(request_key='item'+str(n),revision=n-bounds[0],records=[dict(item='s'+str(n),options=[],gap='No supported option in these captured sources')])) for n in range(*bounds)])
            judge=next(t for t in specs if t.get('review_of')==chunk['id'])
            def review_steps(f):
                catalog=json.loads((Path(f['workspace'])/f['operation_contract']['parameters']['catalog_path']).read_text())
                return [('operation_submit',dict(request_key='review'+str(n),revision=n,records=[dict(item=item['id'],item_sha256=c.digest(item),verdict='supported',reason='No options claimed; explicit source limitation verified')])) for n,item in enumerate(catalog['items'])]
            self.run_worker(judge['id'],review_steps,decision='accept')
        self.rt.close();self.rt=Runtime(self.root,self.factory);self.rt.tick('job')
        state=self.factory.sessions[self.rt.task('job','collect')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        self.assertEqual(execute(f,control)['outcome'],'completed')
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');artifact=self.rt.output('job','collect','delivery/catalog.json');doc=json.loads(Path(artifact['blob']).read_text())
        self.assertEqual([i['id'] for i in doc['items']],['s'+str(n) for n in range(6)])
        self.assertTrue(all(not i['options'] and i['gap'] for i in doc['items']))
        self.assertEqual(self.rt.task('job','collect')['attempts'],1)

    def test_final_partitioned_json_retains_whole_candidate_review(self):
        refs,task=self.content(count=6);self.grant['operations']=['records.merge'];self.grant['deliverables']={'catalog':'application/json'}
        self.create(inputs=refs);self.rt.tick('job');s=self.session();s.delegate(dict(request_id='final',tasks=[task]))
        final=self.rt.spec(self.rt.task('job',label('collect','review')))
        self.assertEqual(final['review_of'],'collect')
        self.assertTrue(any(i.get('from_task')=='collect' and i['output']=='delivery/catalog.json' for i in final['inputs']))
        self.assertEqual(len([t for t in self.rt.status('job')['tasks'] if self.rt.spec(t).get('review_of')]),3)

    def test_missing_merge_authority_never_expands_capacity_or_partial_admission(self):
        refs,task=self.content(count=30);self.create(inputs=refs);self.rt.tick('job');s=self.session()
        with self.assertRaisesRegex(ValueError,'frozen allowance'):
            s.delegate(dict(request_id='too-large',tasks=[task]))
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(self.rt.task('job','owner')['attempts'],1)

    def test_text_only_repetition_is_bounded_without_acceptance_or_tools(self):
        self.create();self.rt.tick('job')
        response=dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(text='Finished')]))])
        with self.assertRaisesRegex(ValueError,'unchanged observation'):
            self.invoke([response]*3)
        aid=self.rt.task('job','owner')['latest'];control=Path(self.factory.sessions[aid]['session']['control'])
        self.assertEqual(len(list(control.glob('api-*.response.json'))),3)
        self.assertEqual(len(list(control.glob('tool-*.json'))),0)
        self.assertFalse((control/'owner-session.json').exists())

    def test_terminal_deck_gets_preview_then_final_review_without_dependency_deadlock(self):
        from orchestrator.document_authoring import PPTX
        self.grant['workers'].append(worker_capabilities.entry(dict(type='gemini-code',model='fixture',runtime='a'*64)))
        self.grant['operations']=['pptx.create','pptx.render'];self.grant['deliverables']={'deck':PPTX,'preview':'application/pdf'}
        self.create();self.rt.tick('job');s=self.session()
        s.delegate(dict(request_id='visual',tasks=[old.worker('content',media='application/json'),old.native('build','pptx.create',[dict(task='content',output='result')])]))
        specs=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id']!='owner']
        render=next(t for t in specs if t.get('execution',{}).get('capability')=='pptx.render');review=next(t for t in specs if t.get('review_of'))
        self.assertEqual(review['review_of'],render['id']);self.assertFalse(any(t.get('review_of')=='build' for t in specs))
        self.assertTrue({'files.binary','images.view'}<=set(review['worker']['requires']))
        self.assertIn('final_quality',review)
        self.assertTrue(any(i.get('from_task')=='build' for i in review['inputs']))
        self.assertEqual(len(specs),4)

    def test_expanded_graph_insufficient_capacity_is_atomic_and_no_ungranted_merge(self):
        refs,task=self.content(count=8);self.grant['operations']=['records.merge'];self.grant['max_tasks']=4
        self.create(inputs=refs);self.rt.tick('job');s=self.session()
        with self.assertRaisesRegex(ValueError,'frozen graph size|remaining job slots'):s.delegate(dict(request_id='too-many',tasks=[task]))
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(len(self.factory.calls),1)
        self.assertFalse(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='future_tasks_added'").fetchone())

    def test_admission_and_dispatch_share_source_provenance_validation(self):
        refs,task=self.content(1,provenance=False);self.create(inputs=refs);self.rt.tick('job');s=self.session()
        with self.assertRaisesRegex(ValueError,'exact completed native source-pack receipt'):
            s.delegate(dict(request_id='unproven',tasks=[task]))
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(len(self.factory.calls),1)

    def test_last_owner_invocation_cannot_launch_work_it_cannot_finalize(self):
        self.grant['owner_turns']=1;self.create();self.rt.tick('job');s=self.session()
        with self.assertRaisesRegex(ValueError,'remaining owner invocation'):
            s.delegate(dict(request_id='last',tasks=[old.worker('write')]))
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(len(self.factory.calls),1)

    def test_effective_capacity_matches_compiler_and_grant_is_not_rewritten(self):
        self.grant['task_limits'].update(tool_calls=60,provider_requests=24)
        self.create();self.rt.tick('job');s=self.session();value=s.call('job_catalog',dict(records=True))
        self.assertEqual(value['effective_request_ceiling'],24)
        self.assertEqual(value['content']['collection.options']['capacity']['single_task_units'],10)
        self.assertEqual(s.grant['task_limits']['provider_requests'],24)
        historical=job_owner.original(self.rt,'job')
        historical['job_owner']['task_limits']['provider_requests']=60
        job_owner.validate_plan(historical)  # New admission checks never invalidate saved grants.

    def test_expanded_admission_rolls_back_on_interruption_and_retries_exactly_once(self):
        self.create();self.rt.tick('job');s=self.session();args=dict(request_id='atomic',tasks=[old.worker('write')]);event=s.rt.event
        def interrupted(run,task,attempt,kind,data):
            if kind=='owner_intents_compiled':raise RuntimeError('interrupted')
            return event(run,task,attempt,kind,data)
        with patch.object(s.rt,'event',side_effect=interrupted),self.assertRaisesRegex(RuntimeError,'interrupted'):
            s.delegate(args)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        receipt=s.delegate(args);self.assertEqual(receipt,s.delegate(args))
        self.assertEqual(len(self.rt.status('job')['tasks']),3);self.assertEqual(len(self.factory.calls),1)

    def test_discovery_exposes_limits_and_untyped_evidence_without_inventing_contract(self):
        ref=self.source('{"items":[],"contract":{"id":"collection.options","version":1,"made_up":true}}','legacy.json','application/json')
        self.grant['operations']=['images.products'];self.create(inputs=[ref]);self.rt.tick('job');s=self.session()
        value=s.call('job_catalog',dict(operations=['images.products'],records=True))
        self.assertEqual(value['limits'],s.grant['task_limits'])
        self.assertIsNone(value['artifacts'][0]['contract'])
        self.assertEqual(value['input_roles']['images.products']['content_roles'][0]['compatible_artifacts'],[])
        self.assertEqual(self.rt.artifact(ref['artifact'])['sha256'],s.artifact(ref['artifact'])[0]['sha256'])

    def test_selected_data_role_removes_ambiguous_context_and_preserves_worker_inputs(self):
        refs,unused=self.content(1);self.grant['operations']=['pptx.create'];self.create(inputs=refs);self.rt.tick('job');s=self.session()
        preparation=old.worker('layout',[dict(artifact=r['artifact']) for r in refs],media='application/json')
        consumer=old.native('build','pptx.create',[dict(task='layout',output='result'),*[dict(artifact=r['artifact']) for r in refs]])
        consumer['data']=dict(task='layout',output='result')
        s.delegate(dict(request_id='roles',tasks=[preparation,consumer]))
        producer=self.rt.spec(self.rt.task('job','layout'));native=self.rt.spec(self.rt.task('job','build'))
        self.assertEqual(producer['operation_contract']['id'],'document.layout');self.assertEqual(len(producer['inputs']),2)
        self.assertEqual(len([i for i in native['inputs'] if i['media_type']=='application/json']),1)

    def test_unchanged_read_stops_early_without_wake_but_new_evidence_does_not(self):
        self.create();self.rt.tick('job')
        with self.assertRaisesRegex(ValueError,'unchanged observation'):
            self.invoke([('job_catalog',{})]*3)
        aid=self.rt.task('job','owner')['latest'];control=Path(self.factory.sessions[aid]['session']['control'])
        hold=json.loads((control/'owner-no-progress.json').read_text());self.assertEqual(hold['requests'],3)
        self.assertFalse((control/'owner-session.json').exists())

class HistoryTests(unittest.TestCase):
    def test_readable_archives_and_retained_history_keep_opaque_protocol_out_of_text(self):
        from tests.test_owner_context_retention import ContextTests
        helper=ContextTests()
        for provider in ('gemini','openai','openrouter'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as root:
                view=working_context.WorkingView(Path(root),semantic=True)
                chunk=helper.group(provider,'job_delegate',dict(objective='Useful work'),dict(error='Exact failure',payload={'thoughtSignature':'Legitimate user data'}),1)
                before=copy.deepcopy(chunk);ident=view.archive(chunk);read=view.read(dict(context=ident,offset=0));doc=json.loads(read['text'])
                self.assertEqual(json.loads((view.folder/(doc['raw_journal']+'.json')).read_text()),before)
                self.assertNotIn('sig1',view.read(dict(context=doc['raw_journal'],offset=0))['text']);self.assertNotIn('opaque1',view.read(dict(context=doc['raw_journal'],offset=0))['text'])
                self.assertIn('Legitimate user data',read['text']);self.assertNotIn('sig1',read['text']);self.assertNotIn('opaque1',read['text'])
                retained=view.retained(chunk,provider);self.assertNotIn('sig1',json.dumps(retained));self.assertEqual(chunk,before)
                raw=view.folder/(ident+'.json');raw.write_text('{}')
                with self.assertRaisesRegex(ValueError,'changed'):view.read(dict(context=ident,offset=0))


class CorrectionTests(unittest.TestCase):
    from tests.test_review_followup import Tests as Fixture
    create=Fixture.create
    invoke=Fixture.invoke
    session=Fixture.session
    source=Fixture.source
    finish=Fixture.finish
    test_rejected_disclaimer_repair_restart_independent_review_and_delivery=Fixture.test_rejected_disclaimer_repair_restart_independent_review_and_delivery
    def setUp(self):
        self.Fixture.setUp(self);self.grant['delegation_version']=3
    def delegate(self,ident):
        self.rt.tick('job')
        self.invoke([('job_delegate',dict(request_id=ident,tasks=[old.worker(ident)]))]);self.rt.tick('job')
    def finish(self,tid,*args,**kwargs):
        if tid.endswith('_review'):tid=label(tid[:-7],'review')
        return self.Fixture.finish(self,tid,*args,**kwargs)

    def test_generated_reviewer_keeps_old_and_new_candidates_at_distinct_paths(self):
        from orchestrator.owner_compilation import reviewer
        producer=dict(id='repair',objective='Repair the cited factual defect',dependencies=[],criteria=['Exact correction'],
            inputs=[dict(artifact='old-candidate',path='candidate/outputs/result.md',purpose='Original rejected version',authority='Unaccepted prior candidate',media_type='text/markdown')],
            outputs=[dict(path='outputs/result.json',purpose='Corrected records',media_type='application/json'),
                     dict(path='outputs/result.md',purpose='Corrected summary',media_type='text/markdown')])
        before=copy.deepcopy(producer);review=reviewer(producer,self.grant)
        self.assertEqual(reviewer(producer,self.grant),review)
        worker_capabilities.resolve(review,self.grant['workers'],self.grant['workers'][0]['backend'])
        c.assignment(review)
        old=next(i for i in review['inputs'] if i.get('artifact')=='old-candidate')
        current=next(i for i in review['inputs'] if i.get('output')=='outputs/result.md')
        self.assertNotEqual(old['path'],current['path'])
        self.assertEqual(current['path'],'candidate/outputs/result.md')
        self.assertEqual(old['artifact'],'old-candidate')
        self.assertEqual(producer,before)
