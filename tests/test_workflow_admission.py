"""Compatible graph admission and confirmed generation failures; no live providers."""
import copy,io,json,unittest
from pathlib import Path
from contextlib import redirect_stdout
from orchestrator import contracts as c,report_builder
from orchestrator.workers import atomic
from orchestrator.storage import transaction
from task_relay import production_planning as planning,planning_contract,completion_recovery as recovery
from task_relay import workflow_admission as admission
from tests.test_contract_builders import BindingTests
from tests import test_gemini_executor as gemini_fixture
from tests import test_review_budget_recovery as recovery_fixture
from tests import test_desktop_sourcing_delivery as delivery_fixture


class AdmissionTests(unittest.TestCase):
    def fixture(self):
        f=BindingTests();f.setUp();self.addCleanup(f.tearDown);return f

    def test_saved_compact_annotations_and_inconsistent_reviews_compile_without_rewriting_reply(self):
        f=self.fixture();row=f.queue();payload=json.loads(row['context']);source=payload['sources'][0]
        v=f.compact();v['plan']['tasks'][0]['input_bindings']=[dict(source=source['artifact'],role='asset')]
        v['plan']['tasks'][0]['max_attempts']=2;v['plan']['tasks'][1]['max_attempts']=1
        raw=c.encoded(v);_,plan=planning.validate_result(raw,row)
        self.assertEqual(c.encoded(v),raw)
        self.assertEqual(plan['tasks'][1]['max_attempts'],2)
        self.assertTrue(any(i.get('artifact')==source['artifact'] for i in plan['tasks'][0]['inputs']))
        self.assertEqual(f.factory.calls,[])
        self.assertTrue(any(b.get('before')=='asset' for b in plan['origin']['planner_field_bindings']))

    def test_capacity_contract_is_independent_of_record_schema_and_keeps_ceiling(self):
        from tests.test_orchestrator import pair
        for version in (None,1,2,99):
            with self.subTest(record_schema=version):
                plan=pair(max_attempts=2);plan['tasks'][1]['max_attempts']=1
                scope=dict(record_interfaces_version=version,planner_budget_binding_version=2)
                original=copy.deepcopy(plan)
                with self.assertRaisesRegex(ValueError,'frozen attempt allowance'):
                    admission.review_capacity(plan,scope,dict(max_attempts=1))
                self.assertEqual(plan,original)
                admission.review_capacity(plan,scope,dict(max_attempts=2))
                self.assertEqual([t['max_attempts'] for t in plan['tasks']],[2,2])
                c.plan(plan)

    def test_new_or_changed_adapter_invalidates_saved_proposal_recheck_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runtime';root.mkdir();(root/'compiler.py').write_text('version=1')
            before=admission.implementation_identity([root])
            (root/'adapter.py').write_text('version=1')
            added=admission.implementation_identity([root]);self.assertNotEqual(added,before)
            (root/'adapter.py').write_text('version=2')
            changed=admission.implementation_identity([root]);self.assertNotEqual(changed,added)
            (root/'notes.txt').write_text('Not executable compiler data')
            self.assertEqual(admission.implementation_identity([root]),changed)

    def test_generic_schema_does_not_offer_host_asset_role_or_metadata_override(self):
        from task_relay.artifact_bindings import schema
        for ref in (dict(source='exact',role='asset'),dict(source='exact',authority='trusted')):
            with self.assertRaises(ValueError):planning_contract.validate(ref,schema())
        planning_contract.validate(dict(source='exact',role='asset'),schema(asset_roles=True))
        value=dict(plan=dict(tasks=[dict(execution=dict(capability='any.native'),input_bindings=[dict(source='exact',role='asset')])]))
        before=copy.deepcopy(value);self.assertEqual(admission.normalize(value,dict(record_interfaces_version=1,planner_budget_binding_version=2),{}),[]);self.assertEqual(before,value)

    def test_explicit_response_ceiling_is_retained_and_legacy_scope_not_upgraded(self):
        f=self.fixture();row=f.queue();v=f.compact()
        for t in v['plan']['tasks']:t['limits']['response_tokens']=1024
        _,plan=planning.validate_result(c.encoded(v),row)
        self.assertTrue(all(t['limits']['response_tokens']==1024 for t in plan['tasks']))
        self.assertFalse(admission.enabled(dict(record_interfaces_version=2,planner_budget_binding_version=1)))


class FragmentTests(unittest.TestCase):
    def test_real_worker_discards_partial_calls_then_builds_report_from_small_checks(self):
        f=gemini_fixture.Tests();f.setUp();self.addCleanup(f.tearDown)
        f.frozen['review_of']='producer';f.frozen['outputs']=[dict(path='review.md',purpose='Independent report')]
        f.input('candidate.txt','Exact inspected candidate',from_task='producer')
        f.frozen['report_contract']=report_builder.freeze(f.frozen)
        values=[]
        for key in f.frozen['report_contract']['schema']['properties']['checks']['properties']:
            values.append(('report_check',dict(check=key,value_json=json.dumps(dict(passed=True,evidence='Exact candidate.txt inspected')))))
        values.insert(0,('report_check',dict(check='c1',value_json=json.dumps(dict(passed=False,evidence='Discard this partial judgment')))))
        final=dict(summary='Candidate inspected',decision='accept',instruction='',findings=[],checks={})
        values.append(('finish',dict(report_json=json.dumps(final))))
        class Client:
            def request(self,*_,**__):
                name,args=values.pop(0);reason='MAX_TOKENS' if args.get('value_json','').find('Discard')>=0 else 'STOP'
                return dict(candidates=[dict(finishReason=reason,content=dict(role='model',parts=[dict(functionCall=dict(name=name,args=args))]))])
        with redirect_stdout(io.StringIO()):result=gemini_fixture.execute(f.frozen,f.control,Client(),lambda:(gemini_fixture.CONFIG,gemini_fixture.BACKEND))
        self.assertEqual(result['decision'],'accept');self.assertTrue(all(v['passed'] for v in result['checks']))
        self.assertNotIn('Discard',(f.control/'report-checks.json').read_text())
        self.assertTrue((f.ws/'review.md').exists())
        from orchestrator.report_fragments import Store
        changed={**f.frozen,'review_target':'different'}
        with self.assertRaisesRegex(ValueError,'changed'):Store(changed,f.control)


class GenerationTests(unittest.TestCase):
    def fixture(self):
        f=recovery_fixture.Tests();f.setUp();self.addCleanup(f.tearDown);return f

    def stopped(self,f):
        from tests.test_orchestrator import pair
        p,s=f.prepare();graph=pair(max_attempts=2);graph['id']='parent';graph['backend']=dict(type='gemini-agent',model='fixture')
        for t in graph['tasks']:t.update(tools=['files'],limits=dict(seconds=600,tool_calls=18,provider_requests=18,output_bytes=200000))
        f.rt.create(graph);f.rt.tick('parent');source=f.rt.task('parent','produce')['latest'];f.factory.finish(source)
        f.factory.sessions[source]['status'].update(external_outcome='no_pending_response',pending_requests=[])
        f.rt.tick('parent');aid=f.rt.task('parent','review')['latest'];control=f.rt.root/'workers'/aid;control.mkdir(parents=True,exist_ok=True)
        atomic(control/'api-01.request.json',dict(provider='gemini',model='fixture',payload={}))
        atomic(control/'api-01.response.json',dict(candidates=[dict(finishReason='MAX_TOKENS')]))
        atomic(control/'api-01.recovery.json',dict(kind='generation_output_limit',continued=False,executed_calls=0))
        f.factory.sessions[aid]['status']=dict(status='finished',token=aid,exit_code=1,
            reason='ValueError: Provider generation output limit reached; incomplete response retained without executing its tools. Bounded recovery unavailable or exhausted.',
            external_outcome='no_pending_response',pending_requests=[],api_requests=1,tool_calls=0)
        f.rt.tick('parent');f.state.db.execute('UPDATE completion_recovery_grants SET policy=? WHERE pipeline=?',(recovery.encoded(recovery.DELIVERY_POLICY),p['id']));f.state.db.commit()
        return p,s,source,aid,control

    def test_confirmed_review_uses_remaining_attempt_after_commit_without_candidate_replay(self):
        f=self.fixture();p,s,source,aid,control=self.stopped(f);calls=list(f.factory.calls)
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        self.assertEqual(calls,f.factory.calls);self.assertEqual(f.rt.task('parent','review')['attempts'],1)
        f.rt.tick('parent');new=f.rt.task('parent','review')['latest'];self.assertNotEqual(new,aid)
        self.assertEqual(f.factory.sessions[new]['frozen']['review_target'],source)
        self.assertEqual(f.rt.task('parent','produce')['attempts'],1)
        self.assertEqual(f.factory.sessions[new]['frozen']['limits'],json.loads(f.state.db.execute('select frozen from production_attempts where id=?',(aid,)).fetchone()[0])['limits'])
        f.factory.finish(new,decision='accept');f.rt.tick('parent');self.assertEqual(f.rt.status('parent')['status'],'completed')

    def test_changed_journal_is_rejected_at_dispatch_and_uncertain_or_exhausted_review_is_held(self):
        f=self.fixture();p,s,source,aid,control=self.stopped(f)
        row=f.state.db.execute('select receipt from production_attempts where id=?',(aid,)).fetchone();receipt=json.loads(row[0])
        for change in (dict(pending_requests=['unknown']),dict(external_outcome='uncertain')):
            with transaction(f.state.db):
                f.state.db.execute('update production_attempts set receipt=? where id=?',(c.encoded({**receipt,**change}),aid));self.assertFalse(recovery.begin(f.state,p,s,'parent'))
        with transaction(f.state.db):f.state.db.execute('update production_attempts set receipt=? where id=?',(row[0],aid))
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        atomic(control/'api-01.response.json',dict(candidates=[dict(finishReason='MAX_TOKENS')],usageMetadata=dict(totalTokenCount=999)))
        calls=list(f.factory.calls);f.rt.tick('parent');self.assertEqual(calls,f.factory.calls);self.assertEqual(f.rt.task('parent','review')['status'],'blocked')


class LocalRevisionTests(unittest.TestCase):
    def stopped(self):
        f=recovery_fixture.Tests();f.setUp();self.addCleanup(f.tearDown)
        from tests.test_orchestrator import pair
        p,s=f.prepare();graph=pair(max_attempts=2);graph['id']='parent'
        f.rt.create(graph);f.rt.tick('parent');source=f.rt.task('parent','produce')['latest']
        f.factory.finish(source);f.rt.tick('parent');aid=f.rt.task('parent','review')['latest']
        f.factory.finish(aid,decision='revise');session=f.factory.sessions[aid]
        result_path=session['workspace']/'.relay/result.json';result=json.loads(result_path.read_text())
        result['findings']=[dict(category='requirements',code='missing_detail',message='Add the visible pattern',evidence='Exact candidate omits the observed pattern')]
        result_path.write_text(json.dumps(result));f.rt.tick('parent')
        f.state.db.execute('UPDATE completion_recovery_grants SET policy=? WHERE pipeline=?',(recovery.encoded(recovery.DELIVERY_POLICY),p['id']));f.state.db.commit()
        return f,p,s,source,aid

    def test_requirement_defect_uses_original_pair_then_finishes_without_planning(self):
        f,p,s,source,aid=self.stopped();calls=list(f.factory.calls)
        before=[dict(r) for r in f.state.db.execute('SELECT * FROM production_attempts')]
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        self.assertEqual(calls,f.factory.calls)
        self.assertEqual(before,[dict(r) for r in f.state.db.execute('SELECT * FROM production_attempts')])
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        f.rt.tick('parent');new=f.rt.task('parent','produce')['latest']
        frozen=f.factory.sessions[new]['frozen'];old=f.factory.sessions[source]['frozen']
        self.assertEqual(frozen['criteria'],old['criteria']);self.assertEqual(frozen['limits'],old['limits'])
        self.assertTrue(any(i['path'].startswith('previous-review/') for i in frozen['inputs']))
        f.factory.finish(new);f.rt.tick('parent');review=f.rt.task('parent','review')['latest']
        self.assertEqual(f.factory.sessions[review]['frozen']['review_target'],new)
        f.factory.finish(review,decision='accept');f.rt.tick('parent')
        self.assertEqual(f.rt.status('parent')['status'],'completed')
        self.assertEqual(f.rt.task('parent','produce')['attempts'],2)
        self.assertEqual(f.rt.task('parent','review')['attempts'],2)
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_stranded_failed_replan_is_preserved_and_rebinds_original_capacity(self):
        f,p,s,source,aid=self.stopped();baseline=recovery.snapshot(f.state,'parent',photo_recovery=True)
        from tests import test_production_planning as planning_fixture
        row=planning_fixture.Tests.queue(f,99);context=json.loads(row['context'])
        context['completion_recovery']=recovery.planner_context(dict(parent='parent',cycle=1,policy=recovery.DELIVERY_POLICY,authorization='lets try',baseline=baseline))
        with transaction(f.state.db):
            f.state.db.execute("UPDATE production_plans SET context=?,context_hash=?,status='blocked',calls=2,error='Incomplete JSON' WHERE id=?",(c.encoded(context),c.digest(context),row['id']))
            for number in (1,2):f.state.db.execute('INSERT INTO production_plan_calls(plan_id,number,request,response,usage,error,created) VALUES(?,?,?,?,?,?,?)',(row['id'],number,'{}','{"plan":','{"totalTokens":20}','Incomplete JSON',number))
            f.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',(p['id'],s['id'],'parent',1,row['request_id'],recovery.encoded(baseline)))
            f.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            f.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='plan_production',target=? WHERE pipeline=? AND id=?",(row['id'],p['id'],s['id']))
        before=dict(f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(row['id'],)).fetchone());calls=list(f.factory.calls)
        recovery.reconcile_stranded_local_revision(f.state);recovery.reconcile_stranded_local_revision(f.state)
        self.assertEqual(before,dict(f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(row['id'],)).fetchone()))
        self.assertEqual(calls,f.factory.calls);self.assertEqual(f.step(p,'outline')['target'],'parent')
        self.assertEqual(f.step(p,'outline')['target_kind'],'production_run')
        self.assertEqual(f.rt.task('parent','produce')['attempts'],1)
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
        f.rt.tick('parent');self.assertEqual(f.rt.task('parent','produce')['attempts'],2)

    def test_changed_confirmed_review_blocks_dispatch_and_remaining_capacity_is_required(self):
        f,p,s,source,aid=self.stopped();baseline=recovery.snapshot(f.state,'parent',photo_recovery=True)
        task=f.rt.task('parent','review');spec=f.rt.spec(task);spec['max_attempts']=1
        with transaction(f.state.db):
            assignment=f.rt.new_assignment('parent',spec)
            f.state.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?',(assignment,'parent','review'))
        self.assertIsNone(recovery.local_revision(f.rt,baseline))
        with transaction(f.state.db):f.state.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?',(task['assignment'],'parent','review'))
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        row=f.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(aid,)).fetchone();receipt=json.loads(row[0]);receipt['pending_requests']=['unknown']
        with transaction(f.state.db):f.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded(receipt),aid))
        calls=list(f.factory.calls);f.rt.tick('parent')
        self.assertEqual(calls,f.factory.calls);self.assertEqual(f.rt.task('parent','produce')['status'],'blocked')


class DesktopAdmissionTests(delivery_fixture.Tests):
    """Normal desktop planner correction/admission through real native PPTX delivery."""
    def proposal(self,row,context=None):
        raw,usage=super().proposal(row,context);v=json.loads(raw)
        if not getattr(self,'_malformed',False):self._malformed=True;return '{"decision":',usage
        for task in v['plan']['tasks']:
            refs=[]
            for i in task.pop('inputs'):
                refs.append(dict(source=i['artifact'],role='asset') if 'artifact' in i and not task.get('execution') else
                            dict(source=i['artifact']) if 'artifact' in i else dict(producer=i['from_task'],output=i['output']))
            task['input_bindings']=refs;task['after']=task.pop('dependencies')
            if task.get('review_of'):task['max_attempts']=1
        return c.encoded(v),usage

    def complete_agent(self,aid):
        session=self.factory.sessions[aid];frozen=session['frozen']
        if frozen['id']=='inventory_review' and not getattr(self,'_generation_failed',False):
            self._generation_failed=True;control=self.rt.root/'workers'/aid;control.mkdir(parents=True,exist_ok=True)
            atomic(control/'api-01.request.json',dict(provider='gemini',model=frozen['backend']['model'],payload={}))
            atomic(control/'api-01.response.json',dict(candidates=[dict(finishReason='MAX_TOKENS')]))
            atomic(control/'api-01.recovery.json',dict(kind='generation_output_limit',continued=False,executed_calls=0))
            session['status']=dict(status='finished',token=aid,exit_code=1,
                reason='ValueError: Provider generation output limit reached; incomplete response retained without executing its tools. Bounded recovery unavailable or exhausted.',
                external_outcome='no_pending_response',pending_requests=[],api_requests=1,tool_calls=0)
            return
        super().complete_agent(aid)
        if frozen['id']=='queries_review' and not getattr(self,'_local_revision_requested',False):
            self._local_revision_requested=True
            result_path=session['workspace']/'.relay/result.json';result=json.loads(result_path.read_text())
            result.update(decision='revise',instruction='Add the observed pattern to the query using the original target and scope.',
                findings=[dict(category='requirements',code='missing_query_detail',message='Preserve the observed pattern',evidence='Exact saved query needs the observed pattern')])
            for check in result['checks']:check['passed']=False
            result_path.write_text(c.encoded(result))
