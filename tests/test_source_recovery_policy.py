"""Synthetic reads and real compilation/collection; no browser, API or media."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator.source_fallback import candidates,collect,extends
from orchestrator import owner_intents,worker_tools
from orchestrator.runtime import Runtime
from tests.test_evidence_workload import page,pack
from tests import test_browser_fallback_lifecycle as lifecycle
from tests import test_owner_intents as owner


def fixture():
    return pack([dict(query='unresolved '+str(i),target_ids=[],pages=[],grounding=[
        dict(url='https://p'+str(j)+'.example/item-'+str(i)) for j in range(5)]) for i in range(4)])


def denied(url,*_):
    return dict(page(url,'Access denied'),retrieval_status='blocked',retrieval_reason='HTTP 403')


class Policy(unittest.TestCase):
    def test_untagged_queries_share_reads_and_prefer_other_publishers(self):
        source=fixture();source['entries'][0]['retrievals']=[dict(url=source['entries'][0]['grounding'][0]['url'],outcome='failed')]
        chosen=candidates(source,[])[:4]
        self.assertEqual({c['entry'] for c in chosen},{0,1,2,3})
        self.assertNotEqual(chosen[0]['url'],source['entries'][0]['retrievals'][0]['url'])
        self.assertGreater(len({c['url'].split('/')[2] for c in chosen}),1)

    def test_attempt_caps_survive_reader_parameter_changes_and_multiple_recoveries(self):
        source=fixture();source['entries']=source['entries'][:1]
        source['entries'][0]['grounding']=source['entries'][0]['grounding'][:1]
        original=copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as root:
            for name,policy in [('isolated',None),('native',{'max_observations':2})]:
                source=json.loads(collect(source,[],1,Path(root)/name,denied,read_policy=policy)[0])
            self.assertEqual(len(source['rendered_fallback']['reads']),2)
            self.assertEqual(candidates(source,[],{'max_observations':8,'binding':{'helper':'different'}}),[])
            self.assertEqual(candidates(source,[]),[])
        self.assertEqual(source['entries'][:1],original['entries'])

    def test_url_total_cap_and_publisher_cap_retain_all_failures(self):
        source=fixture();url=source['entries'][0]['grounding'][0]['url']
        source['entries'][0]['retrievals']=[dict(url=url,outcome='failed')]*3
        self.assertNotIn(url,[c['url'] for c in candidates(source,[])])
        # Four distinct recovery reads at one publisher survive across batches.
        source=pack([dict(query=str(i),target_ids=[],pages=[],grounding=[dict(url='https://only.example/'+str(i))]) for i in range(8)])
        with tempfile.TemporaryDirectory() as root:
            for i in range(2):source=json.loads(collect(source,[],12,Path(root)/str(i),denied)[0])
        self.assertEqual(len(source['rendered_fallback']['reads']),4)
        self.assertEqual(candidates(source,[],{'max_observations':2}),[])

    def test_legacy_skew_prioritizes_other_items_and_preserves_literal_evidence(self):
        source=fixture();source['rendered_fallback']=dict(reads=[dict(url=c['url'],outcome='unavailable') for c in source['entries'][0]['grounding'][:3]])
        source['entries'][0]['pages']=[page('https://prior.example/a','Exact useful dimension 24')]
        original=copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as root:
            out=json.loads(collect(source,[],3,root,lambda url,*_:page(url,'New evidence'))[0])
        self.assertEqual({c['entry'] for c in candidates(source,[])[:3]},{1,2,3})
        self.assertTrue(extends(source,out));self.assertEqual(out['entries'][:4],original['entries'])
        out['entries'][0]['pages'][0]['text']='Lost original';self.assertFalse(extends(source,out))


class Handoff(unittest.TestCase):
    create=owner.Tests.create
    source=owner.Tests.source
    session=owner.Tests.session
    invoke=owner.Tests.invoke
    run_worker=owner.Tests.run_worker
    execute_operation=lifecycle.Tests.execute_operation
    tearDown=lifecycle.retain_evidence

    def setUp(self):
        lifecycle.Tests.setUp(self)
        self.grant.update(worker_tools_version=3,max_tasks=20)
        self.grant['task_limits'].update(tool_calls=30,provider_requests=24,output_bytes=3000000)

    def begin(self,inline=False,repeat=False):
        source=fixture();ref=self.source(json.dumps(source),'sources.json','application/json')
        self.create(inputs=[ref]);self.rt.tick('job')
        first=dict(id='read',objective='Read selected evidence',data={'artifact':ref['artifact']},operation='web.sources.rendered',parameters=dict(domains=[],max_pages=2))
        if inline:
            first=dict(id='read',objective='Read selected evidence',work=dict(operation='web.sources.rendered',mode='execute',data={'artifact':ref['artifact']},parameters=dict(domains=[],max_pages=2)))
        self.invoke([('job_delegate',dict(request_id='first',tasks=[first]))])
        if inline:
            from orchestrator import step_runner
            with patch('orchestrator.worker_tools.execute_local',side_effect=lambda sub,folder,*a,**kw:step_runner.execute(sub,folder)),patch('task_relay.source_browser.render',side_effect=lambda url,*_:page(url,'Retained observation')) as reader,patch('task_relay.source_browser.read_http',new=reader):
                f,_=self.run_worker('read',lambda f:[('work_run',dict(step='build',request_key='read'))]+(
                    [('work_run',dict(step='build',request_key='different-key'))] if repeat else []),decision='blocked')
            self.assertEqual(reader.call_count,2)
            self.assertEqual(self.rt.task('job','read')['status'],'blocked')
            artifact=self.rt.output('job','read','outputs/work-build/source-pack.json')
        else:
            self.execute_operation('read',lambda url,*_:page(url,'Retained observation'))
            artifact=self.rt.output('job','read','delivery/source-pack.json')
        return ref,artifact

    def compile_next(self,ref,inline=False):
        task=dict(id='recover',objective='Resolve remaining evidence',operation='web.sources.rendered',data=ref,parameters=dict(domains=[],max_pages=2))
        if inline:task=dict(id='recover',objective='Resolve remaining evidence',work=dict(operation='web.sources.rendered',mode='execute',data=ref,parameters=dict(domains=[],max_pages=2)))
        return owner_intents.compile(self.session(),dict(request_id='recovery',tasks=[task]))[0]

    def test_standalone_recovery_binds_richer_committed_candidate_after_restart(self):
        ref,artifact=self.begin();original=Path(self.rt.artifact(ref['artifact'])['blob']).read_bytes()
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        next_task=self.compile_next({'artifact':ref['artifact']})
        self.assertEqual(next_task['inputs'][0]['artifact'],artifact['id'])
        self.assertEqual(Path(self.rt.artifact(ref['artifact'])['blob']).read_bytes(),original)
        receipt=json.loads(self.rt.db.execute("SELECT data FROM production_events WHERE kind='evidence_recovery_bound'").fetchone()[0])
        self.assertEqual(receipt['original_artifact'],ref['artifact']);self.assertFalse(receipt['acceptance'])

    def test_worker_block_after_commit_does_not_discard_evidence(self):
        ref,artifact=self.begin(inline=True,repeat=True)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        next_task=self.compile_next({'artifact':ref['artifact']},inline=True)
        self.assertEqual(next_task['inputs'][0]['artifact'],artifact['id'])
        self.assertEqual(next_task['work_tools']['intent']['data'],next_task['inputs'][0]['path'])

    def test_tampered_committed_evidence_cannot_be_selected_or_silently_dropped(self):
        ref,artifact=self.begin()
        attempt=self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
        f=json.loads(attempt['frozen']);(Path(f['workspace'])/artifact['path']).write_text('{}')
        with self.assertRaisesRegex(Exception,'materialization|committed output'):
            self.compile_next({'artifact':ref['artifact']})

    def test_uncertain_producer_is_not_promoted(self):
        ref,artifact=self.begin()
        self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(artifact['attempt'],))
        # Task state is deliberately left completed to isolate receipt proof:
        # an uncertain attempt alone still cannot promote its candidate.
        spec=self.compile_next({'artifact':ref['artifact']})
        self.assertEqual(spec['inputs'][0]['artifact'],ref['artifact'])
        self.assertFalse(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='evidence_recovery_bound'").fetchone())

    def test_task_reference_advances_to_exact_descendant_without_rewriting_original(self):
        ref,first=self.begin()
        task=dict(id='second',objective='Read remaining evidence',operation='web.sources.rendered',data={'artifact':first['id']},parameters=dict(domains=[],max_pages=2))
        self.session().delegate(dict(request_id='second',tasks=[task]))
        self.execute_operation('second',lambda url,*_:page(url,'Second retained observation'))
        latest=self.rt.output('job','second','delivery/source-pack.json')
        spec=self.compile_next(dict(task='read',output='source-pack'))
        self.assertEqual(spec['inputs'][0]['artifact'],latest['id'])

    def test_model_authored_append_and_foreign_candidates_do_not_gain_authority(self):
        ref,first=self.begin()
        # Even a byte-identical local artifact without a producer receipt is
        # not an append-only execution result. Remove the real producer from
        # eligibility and keep the model-supplied copy in this run.
        fake=self.root/'fake.json';fake.write_bytes(Path(first['blob']).read_bytes())
        self.rt.register(fake,'Unproven copy',run='job',path='unproven.json')
        self.rt.db.execute("UPDATE production_attempts SET state='running' WHERE id=?",(first['attempt'],))
        spec=self.compile_next({'artifact':ref['artifact']})
        self.assertEqual(spec['inputs'][0]['artifact'],ref['artifact'])

    def test_duplicate_readers_are_rejected_atomically_but_other_lineages_are_independent(self):
        ref,first=self.begin()
        session=self.session()
        one=dict(id='one',objective='Read remaining sources',operation='web.sources.rendered',data={'artifact':ref['artifact']},parameters=dict(domains=[],max_pages=1))
        two=copy.deepcopy(one);two['id']='two'
        before=self.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'one continuation'):
            session.delegate(dict(request_id='duplicate',tasks=[one,two]))
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0],before)
        session.delegate(dict(request_id='single',tasks=[one]))
        with self.assertRaisesRegex(ValueError,'already pending'):
            session.delegate(dict(request_id='concurrent',tasks=[two]))
        independent=fixture();independent['entries'][0]['query']='Different scope'
        other=self.source(json.dumps(independent),'independent.json','application/json')
        # Register this independent input as a same-run artifact, without
        # changing the original intake authorization of the first lineage.
        self.rt.db.execute('UPDATE production_artifacts SET run=? WHERE id=?',('job',other['artifact']))
        two['data']={'artifact':other['artifact']}
        # A source without a task descriptor is not a compiled same-run output;
        # use the original owner's bound intake path for independent input.
        session.frozen['inputs'].append(other)
        session.delegate(dict(request_id='independent',tasks=[two]))
        self.assertEqual(self.rt.task('job','two')['status'],'queued')

    def test_duplicate_future_output_reads_cannot_bypass_pending_lineage(self):
        ref,first=self.begin();session=self.session()
        one=dict(id='one',objective='Read remaining sources',operation='web.sources.rendered',data={'artifact':first['id']},parameters=dict(domains=[],max_pages=1))
        session.delegate(dict(request_id='one',tasks=[one]))
        future=copy.deepcopy(one);future.update(id='future',data=dict(task='one',output='source-pack'))
        session.delegate(dict(request_id='future',tasks=[future]))
        duplicate=copy.deepcopy(future);duplicate['id']='duplicate'
        with self.assertRaisesRegex(ValueError,'already pending'):
            session.delegate(dict(request_id='duplicate',tasks=[duplicate]))
