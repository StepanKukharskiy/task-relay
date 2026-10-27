import copy
import json
import unittest
from task_relay import completion_recovery as recovery, production_planning as planning


class BindingTests(unittest.TestCase):
    def payload(self):
        return dict(options=dict(step_capabilities=['web.sources']),
                    completion_recovery=dict(completed_read_operations=[dict(attempt='read',capability='web.sources')]),
                    sources=[dict(artifact='source',sha256='a'*64,bytes=42)],
                    recorded_external_sources=[dict(artifact='source',sha256='a'*64,bytes=42,attempt='read')])

    def plan(self):
        return dict(tasks=[dict(id='write',inputs=[dict(artifact='source')]),
                           dict(id='review',review_of='write',inputs=[dict(artifact='source')])])

    def test_completed_read_reaches_both_reviewed_consumers(self):
        recovery.validate_operation_reuse(self.plan(),self.payload(),{'web.sources':['source']})

    def test_unrelated_uncertain_changed_or_unreviewed_sources_cannot_cover_operation(self):
        for mutation in ('no_recovery','other_attempt','changed_bytes','no_pages','unselected'):
            with self.subTest(mutation=mutation):
                p=self.payload()
                if mutation=='no_recovery':p.pop('completion_recovery')
                if mutation=='other_attempt':p['recorded_external_sources'][0]['attempt']='other'
                if mutation=='changed_bytes':p['sources'][0]['bytes']=43
                if mutation=='no_pages':p['recorded_external_sources']=[]
                if mutation=='unselected':p['options']['step_capabilities']=[]
                with self.assertRaises(ValueError):recovery.validate_operation_reuse(self.plan(),p,{'web.sources':['source']})
        plan=self.plan();plan['tasks'][1]['inputs']=[]
        with self.assertRaisesRegex(ValueError,'independent reviewer'):
            recovery.validate_operation_reuse(plan,self.payload(),{'web.sources':['source']})

    def test_baseline_only_exposes_current_completed_source_attempt(self):
        baseline=dict(attempts=[dict(id='read',state='completed')],tasks=[dict(id='source',status='completed',latest='read')],
                      plan=dict(tasks=[dict(id='source',execution=dict(capability='web.sources'))]))
        self.assertEqual(len(recovery.completed_read_operations(baseline)),1)
        baseline['tasks'][0]['status']='awaiting_review'
        self.assertEqual(len(recovery.completed_read_operations(baseline)),1)
        baseline['tasks'][0]['latest']='older'
        self.assertEqual(recovery.completed_read_operations(baseline),[])
        baseline['tasks'][0]['latest']='read';baseline['attempts'][0]['state']='uncertain'
        self.assertEqual(recovery.completed_read_operations(baseline),[])

    def test_prepared_read_is_reusable_but_cannot_hide_another_prepared_search(self):
        baseline=dict(attempts=[dict(id='read',state='completed')],tasks=[dict(id='source',status='awaiting_review',latest='read')],
                      plan=dict(tasks=[dict(id='source',execution=dict(capability='web.sources.prepared'))]))
        self.assertEqual(recovery.completed_read_operations(baseline),[dict(task='source',attempt='read',capability='web.sources',actual_capability='web.sources.prepared')])
        payload=self.payload();payload['completion_recovery']['completed_read_operations']=recovery.completed_read_operations(baseline)
        recovery.validate_operation_reuse(self.plan(),payload,{'web.sources':['source']})
        plan=self.plan();plan['tasks'].append(dict(id='new_read',execution=dict(capability='web.sources.prepared')))
        with self.assertRaisesRegex(ValueError,'absent selected'):
            recovery.validate_operation_reuse(plan,payload,{'web.sources':['source']})
        baseline['tasks'][0]['latest']='read';baseline['attempts'][0]['state']='uncertain'
        self.assertEqual(recovery.completed_read_operations(baseline),[])


class PlanningTests(unittest.TestCase):
    def setUp(self):
        from tests.test_production_planning import Tests
        self.fixture=Tests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)

    def candidate(self):
        row=dict(self.fixture.queue());payload=json.loads(row['context']);options=json.loads(row['options'])
        options['step_capabilities']=['web.sources'];payload['options']=options
        source=payload['sources'][0]
        payload['recorded_external_sources']=[dict(artifact=source['artifact'],sha256=source['sha256'],bytes=source['bytes'],attempt='finished-read')]
        payload['completion_recovery']=dict(completed_read_operations=[dict(task='source',attempt='finished-read',capability='web.sources')])
        row.update(context=json.dumps(payload),options=json.dumps(options))
        result=self.fixture.response();result['reused_operations']={'web.sources':[source['artifact']]}
        return row,result

    def test_file_repair_admits_without_duplicate_search_and_preserves_review(self):
        row,result=self.candidate()
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(len(plan['tasks']),2)
        self.assertFalse(any(t.get('execution') for t in plan['tasks']))
        self.assertEqual(plan['reused_operations'],result['reused_operations'])
        self.assertEqual(plan['tasks'][1]['review_of'],plan['tasks'][0]['id'])
        result.pop('reused_operations')
        with self.assertRaisesRegex(ValueError,'omitted selected operations'):
            planning.validate_result(json.dumps(result),row)

    def test_reuse_cannot_hide_missing_final_deliverable(self):
        row,result=self.candidate();options=json.loads(row['options']);options['deliverables']={'report':'Reviewed report'}
        payload=json.loads(row['context']);payload['options']=options
        row.update(options=json.dumps(options),context=json.dumps(payload))
        with self.assertRaisesRegex(ValueError,'every requested deliverable'):
            planning.validate_result(json.dumps(result),row)

    def test_explicit_prepared_selection_is_covered_only_by_prepared_receipt(self):
        row,result=self.candidate();options=json.loads(row['options']);payload=json.loads(row['context'])
        options['step_capabilities']=['web.sources.prepared'];payload['options']=options
        payload['completion_recovery']['completed_read_operations'][0]['actual_capability']='web.sources.prepared'
        row.update(options=json.dumps(options),context=json.dumps(payload))
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(len(plan['tasks']),2)
        self.assertFalse(any(t.get('execution') for t in plan['tasks']))
        # Historical contexts retain the actual operation in the frozen original plan.
        payload['completion_recovery']['completed_read_operations'][0].update(task='source')
        del payload['completion_recovery']['completed_read_operations'][0]['actual_capability']
        payload['completion_recovery']['original_plan']=dict(tasks=[dict(id='source',execution=dict(capability='web.sources.prepared'))])
        row['context']=json.dumps(payload)
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertFalse(any(t.get('execution') for t in plan['tasks']))
        payload['completion_recovery']['completed_read_operations'][0]['actual_capability']='web.sources'
        row['context']=json.dumps(payload)
        with self.assertRaisesRegex(ValueError,'completed baseline receipt'):
            planning.validate_result(json.dumps(result),row)


class StartTests(unittest.TestCase):
    def test_start_rechecks_finished_receipt_before_any_dispatch(self):
        self.check_receipt('web.sources')

    def test_prepared_start_rechecks_finished_receipt_before_any_dispatch(self):
        self.check_receipt('web.sources.prepared')

    def test_saved_proposal_recovery_keeps_original_budget_and_receipt_checks(self):
        self.check_receipt('web.sources.prepared',recovered=True)

    def check_receipt(self,capability,recovered=False):
        from unittest.mock import patch
        from orchestrator.storage import transaction
        from task_relay import external_evidence
        from tests.test_completion_recovery import Tests
        fixture=Tests();fixture.setUp();self.addCleanup(fixture.tearDown)
        p,s=fixture.prepare();baseline=fixture.baseline()
        path=fixture.state.media_dir.parent/'source.json';path.write_text('{"fixture":"fetched page"}')
        aid=fixture.rt.register(path,'Saved page',run='parent',task='source',attempt='finished-read')
        source=dict(fixture.state.db.execute('SELECT * FROM production_artifacts WHERE id=?',(aid,)).fetchone())
        source['artifact']=aid
        receipt=dict(status='finished',operation=dict(output_sha256=source['sha256'],validation=dict(fetched=1)))
        with transaction(fixture.state.db):
            fixture.state.db.execute("INSERT INTO production_attempts VALUES ('finished-read','parent','source','a','completed',NULL,?,'{}',?,NULL)",
                (json.dumps(dict(execution=dict(capability=capability))),json.dumps(receipt)))
        baseline['attempts']=[dict(id='finished-read',state='completed')]
        baseline['tasks']=[dict(id='source',status='completed',latest='finished-read')]
        baseline['plan']['tasks'].append(dict(id='source',execution=dict(capability=capability)))
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(fixture.state.db):
            self.assertTrue(recovery.begin(fixture.state,p,s,'parent'))
        request=fixture.step(p,'outline')['request_id']
        task=dict(id='write',inputs=[dict(artifact=aid)],max_attempts=1,limits=dict(seconds=600,tool_calls=24),backend=dict(type='codex-cli'))
        review=copy.deepcopy(task);review.update(id='review',review_of='write')
        plan=dict(tasks=[task,review],deliverables=baseline['plan']['deliverables'],reused_operations={'web.sources':[aid]})
        context=dict(options=dict(step_capabilities=['web.sources']),sources=[source])
        row=dict(request_id=request,plan=json.dumps(plan),context=json.dumps(context))
        if recovered:
            from orchestrator import contracts as c
            original='blocked-proposal-fixture'
            response='{"saved":"unexecuted response"}'
            with transaction(fixture.state.db):
                fixture.state.db.execute('''INSERT INTO production_plans
                    (id,request_id,channel,request,options,context,context_hash,provider,model,status,token,expires,created)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',(original,request,'telegram','Exact fixture request','{}',json.dumps(context),c.digest(context),'fixture','fixture','blocked','token',0,1))
                fixture.state.db.execute('INSERT INTO production_plan_calls VALUES (?,?,?,?,?,?,?)',(original,1,'Exact fixture request',response,'{}','old admission mismatch',1))
            context['recovered_proposal']=dict(plan_id=original,call=1,response_sha256=c.digest(response))
            context['completion_recovery']={'parent':'parent'}
            row.update(request_id=-999,parent_id=original,channel='telegram',context=json.dumps(context))
        with patch.object(recovery,'snapshot',return_value=baseline):
            recovery.check_plan(fixture.state,p,s,row)
            if recovered:
                tampered=copy.deepcopy(row);bad=json.loads(tampered['context']);bad['recovered_proposal']['response_sha256']='changed'
                tampered['context']=json.dumps(bad)
                with self.assertRaisesRegex(ValueError,'authorization baseline'):
                    recovery.check_plan(fixture.state,p,s,tampered)
            receipt['pending_requests']=['unknown']
            with transaction(fixture.state.db):
                fixture.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),'finished-read'))
            with self.assertRaisesRegex(ValueError,'completed baseline receipt'):
                recovery.check_plan(fixture.state,p,s,row)
        self.assertEqual(fixture.factory.calls,[])
