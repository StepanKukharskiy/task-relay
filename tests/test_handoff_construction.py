"""Shared construction, exact inspection reuse and bounded paths; no live calls."""
import copy,json,unittest
from pathlib import Path
from orchestrator import owner_intents as intents,handoff_closure as closure,contracts as c
from orchestrator.runtime import Runtime
from tests import test_compiler_intent_scope as scope,test_navigation_inspection as inspection
from tests import test_owner_intents as owner
from tests.test_browser_fallback_lifecycle import retain_evidence

class References(unittest.TestCase):
    create=scope.Routing.create;source=scope.Routing.source;session=scope.Routing.session
    setUp=scope.Routing.setUp;start=scope.Routing.start;doc=scope.Routing.doc;request=scope.Routing.request
    tearDown=retain_evidence
    def test_outer_reference_compiles_once_retains_original_and_restart(self):
        data=self.source(self.doc(),'saved.json','application/json');session=self.start([data])
        args=self.request('execute');args['tasks'][0]['data']={'artifact':data['artifact']};raw=copy.deepcopy(args)
        result=session.delegate(args);self.assertEqual(args,raw)
        self.assertEqual(session.delegate(args),result)
        spec=self.rt.spec(self.rt.task('job','make'));route=spec['work_tools']['intent'];self.assertEqual(route['mode'],'execute')
        self.assertEqual(next(i['artifact'] for i in spec['inputs'] if i['path']==route['data']),data['artifact'])
        self.assertIsNone(spec['work_tools']['preparation'])
        event=json.loads(self.rt.db.execute("select data from production_events where kind='owner_intents_compiled'").fetchone()[0]);self.assertEqual(event['intent'],raw)
        self.rt.close();self.rt=Runtime(self.root,self.factory);self.rt.tick('job')
        frozen=self.factory.sessions[self.rt.task('job','make')['latest']]['frozen'];self.assertEqual(frozen['work_tools']['intent'],route)
        self.assertEqual((Path(frozen['workspace'])/route['data']).read_text(),self.doc())
        self.assertEqual(sum(x['frozen']['id']=='make' for x in self.factory.sessions.values()),1)
    def test_conflicting_references_and_wrong_modes_commit_nothing(self):
        left=self.source(self.doc(),'left.json','application/json');right=self.source(self.doc(),'right.json','application/json');session=self.start([left,right])
        variants=[]
        x=self.request('execute',data={'artifact':left['artifact']});x['tasks'][0]['data']={'artifact':right['artifact']};variants.append(x)
        x=self.request('create');x['tasks'][0]['data']={'artifact':left['artifact']};variants.append(x)
        x=self.request('execute');x['tasks'][0]['baseline']={'artifact':left['artifact']};variants.append(x)
        for n,args in enumerate(variants):
            args['request_id']='bad'+str(n)
            with self.subTest(n=n),self.assertRaises(ValueError):session.delegate(args)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        # Equal bytes are not permission to choose between distinct identities.
        self.assertEqual(Path(self.rt.artifact(left['artifact'])['blob']).read_bytes(),Path(self.rt.artifact(right['artifact'])['blob']).read_bytes())
    def test_identical_dual_reference_and_explicit_baseline_are_lossless(self):
        ref={'artifact':'exact'}
        for name,mode in [('data','execute'),('baseline','revise')]:
            args=self.request(mode,**{name:ref});args['tasks'][0][name]=ref
            original=copy.deepcopy(args);intents.validate_delegation(args,4)
            built=intents.construct_delegation(args,4);self.assertNotIn(name,built['tasks'][0]);self.assertEqual(built['tasks'][0]['work'][name],ref);self.assertEqual(args,original)
        with self.assertRaises(ValueError):intents.validate_delegation(args,3)

class Reviews(unittest.TestCase):
    setUp=inspection.Review.setUp;create=inspection.Review.create;source=inspection.Review.source
    session=inspection.Review.session;invoke=inspection.Review.invoke;run_worker=inspection.Review.run_worker
    execute_native=inspection.Review.execute_native;tearDown=retain_evidence
    def test_downstream_review_reuses_inherited_collected_inspection_after_restart(self):
        self.grant['deliverables']['report']='text/plain'
        ref=self.source('Small fixture, not a native document.');self.create(inputs=[ref]);self.rt.tick('job')
        self.session().delegate(dict(request_id='first',tasks=[owner.native('build','fixture.build',[dict(artifact=ref['artifact'])]),dict(id='judge',objective='Review exact candidate',review_of='build')]))
        reader=next(t['id'] for t in self.rt.status('job')['tasks'] if t['id'].startswith('inspection_'))
        self.execute_native('build');self.execute_native(reader)
        self.run_worker('judge',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        candidate=self.rt.output('job','build','delivery/candidate.txt');review=self.rt.output('job','judge','outputs/review.md');proof=self.rt.output('job',reader,'delivery/inspection.txt')
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        args=dict(request_id='downstream',tasks=[owner.worker('summary',[{'artifact':candidate['id']},{'artifact':review['id']}]),dict(id='final-review',objective='Review exact summary and native evidence',review_of='summary')])
        self.session().delegate(args)
        compiled=self.rt.spec(self.rt.task('job','final-review'))
        identities=[closure.resolved_key(i,self.rt,'job',{'summary'}) for i in compiled['inputs']]
        self.assertEqual(identities.count(('artifact',proof['id'])),1)
        self.assertEqual(len({i['path'] for i in compiled['inputs']+compiled['outputs']}),len(compiled['inputs'])+len(compiled['outputs']))
        self.assertEqual(sum(t['id'].startswith('inspection_') for t in self.rt.status('job')['tasks']),1)
        self.run_worker('summary',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Exact fixture summary with retained inspection.'))])
        final,_=self.run_worker('final-review',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        self.assertTrue(any(i['artifact']==proof['id'] for i in final['inputs']))
        spec=self.rt.spec(self.rt.task('job','summary'));self.assertEqual(spec['limits'],self.grant['task_limits'])
    def test_generated_evidence_collision_keeps_both_exact_identities(self):
        first=dict(artifact='first',path='inspection/reader/same.txt',purpose='Earlier evidence',authority='Fixture')
        second=dict(artifact='second',path=first['path'],purpose='Required inspection',authority='Fixture')
        task=dict(inputs=[copy.deepcopy(first)],outputs=[dict(path='outputs/review.md')]);one=closure.add_evidence(task,second)
        self.assertNotEqual(one['path'],first['path']);self.assertEqual(task['inputs'][0],first)
        self.assertIs(closure.add_evidence(task,second),one);self.assertEqual(len(task['inputs']),2)
        # Reserve the generated alias too; construction remains deterministic.
        occupied=copy.deepcopy(task);occupied['inputs'][1]['artifact']='third'
        two=closure.add_evidence(occupied,second);self.assertNotEqual(two['path'],one['path']);self.assertEqual(len(occupied['inputs']),3)
