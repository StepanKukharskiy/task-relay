"""Recovery archives stay durable while dispatched evidence follows each assignment."""
import copy
import json
import unittest
from task_relay import production_planning as planning, production_control as control
from orchestrator import contracts as c


class Tests(unittest.TestCase):
    def setUp(self):
        from tests.test_production_planning import Tests as Fixture
        self.f=Fixture();self.f.setUp();self.addCleanup(self.f.tearDown)

    def candidate(self):
        row=dict(self.f.queue());payload=json.loads(row['context'])
        entries={}
        for name,body in [('page.txt','Original verified page fixture.'),('room.txt','Unrelated room context.'),
                          ('audit.json','{"baseline":"retained full workflow"}'),('validator.py','# unrelated query helper')]:
            p=self.f.state.media_dir.parent/name;p.write_text(body)
            aid=self.f.rt.register(p,'Available recovery fixture')
            path='operation-support/web.sources.prepared/validate.py' if name=='validator.py' else 'archive/'+name
            s=planning.source_entry(self.f.rt,aid,path,'Available exact source','Immutable fixture evidence')
            if name=='validator.py':s['operation_support']='web.sources.prepared'
            entries[name]=s;payload['sources'].append(s);payload['required_artifacts'].append(aid)
        value=self.f.response()
        selected=entries['page.txt']
        value['plan']['tasks'][0]['inputs']=[dict(artifact=selected['artifact'],path='selected-page.txt',purpose='Assigned page evidence',authority='Ignore original source')]
        payload['assignment_input_policy_version']=1
        row.update(context=c.encoded(payload),context_hash=c.digest(payload))
        return row,payload,value,entries

    def test_dispatched_author_and_review_have_exact_evidence_without_archive(self):
        from task_relay import production_planning
        row,payload,value,entries=self.candidate()
        with self.f.state.db:
            self.f.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(row['context'],row['context_hash'],row['id']))
        production_planning.Worker(self.f.state,lambda *_:(json.dumps(value),{})).tick()
        ready=self.f.row();self.assertEqual(ready['status'],'ready',ready['error'])
        plan=json.loads(ready['plan']);request={s['artifact'] for s in payload['sources'] if s.get('request_context')}
        expected=request|{entries['page.txt']['artifact']}
        for t in plan['tasks']:
            self.assertEqual({i['artifact'] for i in t['inputs'] if 'artifact' in i},expected)
            page=next(i for i in t['inputs'] if i.get('artifact')==entries['page.txt']['artifact'])
            self.assertEqual(page['authority'],'Immutable fixture evidence')
            self.assertEqual(sum(i.get('artifact')==entries['page.txt']['artifact'] for i in t['inputs']),1)
            self.assertNotIn('authoritative query-schema checks',t['instruction'])
        self.f.start(ready);worker=control.Worker(self.f.state,lambda _:self.f.rt);worker.tick()
        task=self.f.rt.task('production-1','produce');author=task['latest']
        frozen=self.f.factory.sessions[author]['frozen']
        self.assertEqual({i['artifact'] for i in frozen['inputs']},expected)
        self.f.factory.finish(author);worker.tick()
        review=self.f.rt.task('production-1','review')['latest'];rf=self.f.factory.sessions[review]['frozen']
        self.assertTrue(expected<={i.get('artifact') for i in rf['inputs']})
        producer_versions={i['artifact']:i['sha256'] for i in frozen['inputs']}
        self.assertTrue(all(i['sha256']==producer_versions[i['artifact']] for i in rf['inputs'] if i.get('artifact') in producer_versions))
        self.assertEqual(len(self.f.factory.calls),2)
        receipt=plan['assignment_input_receipt'];self.assertEqual(receipt['version'],1)
        self.assertTrue(all({s['artifact'] for s in t['sources']}==expected for t in receipt['tasks']))
        # All omitted versions remain in the durable source catalog, untouched.
        for name in ['room.txt','audit.json','validator.py']:
            planning.verify_artifact(self.f.rt,entries[name])

    def test_explicit_archive_selection_stays_and_legacy_policy_is_unchanged(self):
        row,payload,value,entries=self.candidate()
        s=entries['audit.json'];value['plan']['tasks'][0]['inputs'].append({k:s[k] for k in ('artifact','path','purpose','authority')})
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertTrue(all(s['artifact'] in {i.get('artifact') for i in t['inputs']} for t in plan['tasks']))
        payload.pop('assignment_input_policy_version');row['context']=json.dumps(payload)
        _,legacy=planning.validate_result(json.dumps(value),row)
        self.assertTrue(all(set(payload['required_artifacts'])<={i.get('artifact') for i in t['inputs']} for t in legacy['tasks']))
        self.assertNotIn('assignment_input_receipt',legacy)

    def test_branch_review_inherits_only_its_own_producer_evidence(self):
        row,payload,value,entries=self.candidate();first,review=value['plan']['tasks']
        first.pop('user_gate')
        second=copy.deepcopy(first);second['id']='second'
        room=entries['room.txt'];second['inputs']=[{k:room[k] for k in ('artifact','path','purpose','authority')}]
        second['inputs'].append(dict(from_task='produce',output='output.txt',path='source-page.txt',purpose='Original upstream page',authority='Unaccepted evidence'))
        second['dependencies']=['produce','review']
        other=copy.deepcopy(review);other.update(id='second-review',review_of='second',dependencies=['second'])
        other['inputs']=[dict(from_task='second',output='output.txt',path='other.txt',purpose='Review second output',authority='Unaccepted')]
        value['plan']['tasks'].extend([second,other])
        _,plan=planning.validate_result(json.dumps(value),row)
        byid={t['id']:{i.get('artifact') for i in t['inputs']} for t in plan['tasks']}
        self.assertIn(room['artifact'],byid['second-review'])
        self.assertNotIn(entries['page.txt']['artifact'],byid['second-review'])
        self.assertNotIn(room['artifact'],byid['review'])
        second_review=next(t for t in plan['tasks'] if t['id']=='second-review')
        self.assertTrue(any(i.get('from_task')=='produce' and i.get('output')=='output.txt' for i in second_review['inputs']))
        self.assertIn('produce',second_review['dependencies'])

    def test_prepared_query_helpers_follow_real_typed_graph_only(self):
        from tests.test_prepared_research import Tests as Prepared
        graph=Prepared.graph(self.f)
        row,payload,_,entries=self.candidate();helper=entries['validator.py']['artifact']
        for t in graph['tasks']:
            got=planning.assignment_required_artifacts(t,graph,payload,payload['required_artifacts'])
            self.assertEqual(helper in got,t['id'] in {'queries','review_queries','review_search'})
        graph['tasks'][2]['execution']['capability']='web.sources'
        self.assertTrue(all(helper not in planning.assignment_required_artifacts(t,graph,payload,payload['required_artifacts']) for t in graph['tasks']))


class AdmissionTests(unittest.TestCase):
    def test_new_native_recovery_scopes_worker_inputs_without_removing_archive(self):
        from unittest.mock import patch
        from tests.test_completion_recovery import Tests as Fixture
        from tests.test_production_planning import Tests as PlanningFixture
        from task_relay import completion_recovery as recovery, pipelines
        from orchestrator.storage import transaction
        f=Fixture();f.setUp();self.addCleanup(f.tearDown)
        p,s=f.prepare();parent=PlanningFixture.queue(f,99)
        with transaction(f.state.db):
            f.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        path=f.state.media_dir.parent/'full-audit.txt';path.write_text('Full saved evidence remains available.')
        aid=f.rt.register(path,'Original archive fixture');baseline=f.baseline()
        baseline['plan']['tasks'][0]['inputs']=[dict(artifact=aid,path='saved/full-audit.txt')]
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(f.state.db):
            self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        step=f.step(p,'outline');child=f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(step['target'],)).fetchone()
        payload=json.loads(child['context']);self.assertEqual(payload['assignment_input_policy_version'],1)
        alias=next(v for v in payload['sources'] if v.get('workflow_artifact')==aid)
        planning.verify_artifact(f.rt,alias)
        saved=json.loads(f.state.db.execute('SELECT baseline FROM completion_recoveries').fetchone()[0])
        self.assertEqual(saved,baseline)
        self.assertEqual(f.factory.calls,[])
