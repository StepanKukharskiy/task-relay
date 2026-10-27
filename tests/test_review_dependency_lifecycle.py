"""Collected inspection evidence across rejection/correction/review and export.

Opaque documents contain small text; registered previews are tiny synthetic PNGs.
Scripted judgments qualify handoffs, never native applications or visual quality.
"""
import copy,hashlib,io,json,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from orchestrator import execution,job_owner,step_runner,executors,contracts as c
from orchestrator.operation_adapters import Adapter,object_schema
from orchestrator.operation_execution import Result
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from tests import lifecycle_fixture as life
from tests.test_operation_session import Script,CONFIG
from tests.test_owner_intents import worker


def inspect_fixture(ctx):
    raw=(ctx.workspace/ctx.frozen['inputs'][0]['path']).read_bytes()
    output=io.BytesIO();Image.new('RGB',(4,4),tuple(hashlib.sha256(raw).digest()[:3])).save(output,format='PNG')
    return Result(output.getvalue())


class ReviewDependency(life.Lifecycle,unittest.TestCase):
    def setUp(self):
        base=copy.deepcopy(execution.REGISTRY['text.bundle'])
        build={**base,'outputs':{'delivery/candidate.txt':'application/x-fixture'},'output_type':None,
               'companions':{'fixture.inspect':'independent-review-evidence'}}
        inspect={**base,'input_types':['application/x-fixture'],'outputs':{'delivery/preview.png':'image/png'},'output_type':None,'review_evidence':True}
        adapter=Adapter(object_schema({}),handler='orchestrator.operation_execution:text_bundle',handoffs=dict(version=1,default='declared-context-or-native-file',ports=[]),worker_tool=True)
        import dataclasses
        for target,value in [(execution.REGISTRY,{'fixture.build':build,'fixture.inspect':inspect}),
            (execution.ADAPTERS,{'fixture.build':adapter,'fixture.inspect':dataclasses.replace(adapter,handler=__name__+':inspect_fixture')})]:
            p=patch.dict(target,value);p.start();self.addCleanup(p.stop)
        original=life.grant
        def grant():
            g=original();g['operations']=['fixture.build','fixture.inspect'];g['deliverables']={'document':'application/x-fixture','missing':'application/pdf'}
            from orchestrator.worker_capabilities import entry
            g['workers'].append(entry(dict(type='gemini-code',model='fixture',runtime='a'*64)))
            return g
        with patch.object(life,'grant',side_effect=grant):super().setUp()
        p=patch('task_relay.code_runtime.available',return_value={'tools':{}});p.start();self.addCleanup(p.stop)

    def run_steps(self,ident,steps,decision='delivered'):
        self.rt.tick('job');a=self.rt.task('job',ident)['latest'];self.assertIsNotNone(a,ident+' did not dispatch')
        s=self.factory.sessions[a];f=s['frozen'];control=Path(s['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,f['backend'])))
        report=dict(summary='Scripted exact candidate inspection and disclosed target gap.',decision=decision,
            instruction='Correct the factual defect; retain evidence and target gap.' if decision=='revise' else '',findings=[],
            checks={f'c{i}':dict(passed=decision!='revise',evidence='Exact fixture read and synthetic pixels supplied') for i in range(1,len(f['criteria'])+1)})
        if f.get('review_followup'):
            follow=f['review_followup'];report['checks']['c'+str(follow['criterion'])]=dict(passed=decision!='revise',evidence={
                key:dict(verdict='unresolved' if decision=='revise' else 'resolved',reason='Scripted literal correction checked',inspected=[dict(path=p,location='Complete fixture') for p in follow['candidates']]) for key in follow['findings']})
        for number,binding in f.get('final_quality',{}).get('checks',{}).items():
            from orchestrator.final_quality import DIMENSIONS
            report['checks']['c'+number]=dict(passed=decision!='revise',evidence={
                dimension:dict(verdict='defect' if decision=='revise' else 'satisfied',
                    reason='Scripted fixture judgment only; not live semantic or visual qualification',
                    inspected=[dict(path=p,location='Exact fixture and all synthetic page representations')
                        for p in dict.fromkeys([binding['candidate'],*binding['inspection_inputs'],
                            *([i['path'] for i in f['inputs'] if i.get('visual_reference')] if dimension=='reference_fit' else [])])]) for dimension in DIMENSIONS})
        script=Script(steps(f)+[('finish',dict(report_json=c.encoded(report)))])
        with patch('orchestrator.worker_tools.execute_local',side_effect=lambda sub,folder,*a,**kw:step_runner.execute(sub,folder)),patch('orchestrator.gemini_worker.emit'):
            execute(f,control,script,lambda:(CONFIG,f['backend']))
        s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');return f

    def reads(self,f):
        return [('image_view',dict(path=i['path'],members=[])) if i.get('media_type')=='image/png' else ('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]

    def judge(self,ident,decision):
        rid=next(t['id'] for t in self.rt.status('job')['tasks'] if self.rt.spec(self.rt.task('job',t['id'])).get('review_of')==ident)
        f=self.run_steps(rid,lambda f:[('image_view',dict(path=i['path'],members=[])) if i.get('media_type')=='image/png' else ('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision)
        candidate=self.rt.output('job',ident,'outputs/work-build/candidate.txt')
        self.assertEqual(f['review_target'],candidate['attempt']);return f

    def make(self,ident,text,prior=None):
        inputs=[{'artifact':self.evidence['artifact']}]
        if prior:inputs.append({'artifact':prior['id']})
        prep=worker('prepare_'+ident,inputs)
        self.delegate('prepare_'+ident,[prep,dict(id='prepare_'+ident+'_review',objective='Review prepared fixture',review_of='prepare_'+ident)])
        self.run_steps('prepare_'+ident,lambda f:self.reads(f)+[('file_write',dict(path=f['outputs'][0]['path'],text=text))])
        self.run_steps('prepare_'+ident+'_review',self.reads,decision='accept')
        data=self.rt.output('job','prepare_'+ident,'outputs/result.txt')
        self.delegate('build_'+ident,[dict(id=ident,objective='Build corrected fixture, preserving historical evidence',data={'artifact':data['id']},work=dict(operation='fixture.build',mode='execute',parameters={}))])
        self.run_steps(ident,lambda f:[('work_run',dict(step='build',request_key='build')),('work_run',dict(step='inspect',request_key='inspect')),('image_view',dict(path='outputs/work-inspect/preview.png',members=[]))])
        return self.rt.output('job',ident,'outputs/work-build/candidate.txt')

    def test_rejected_inline_evidence_two_corrections_restart_final_review_partial_export(self):
        first=self.make('v1','Price: 99; target 3, supported 1, gap 2.');self.judge('v1','revise');first_state=self.rt.task('job','v1')['status'];raw=Path(first['blob']).read_bytes()
        self.restart();second=self.make('v2','Price: 10; target 3, supported 1; gap not disclosed.',first)
        review=self.judge('v2','revise');second_state=self.rt.task('job','v2')['status']
        self.assertNotIn('v1',review['dependencies'])
        self.restart();third=self.make('v3','Price: 10; target 3, supported 1, gap 2.',second);final=self.judge('v3','accept')
        self.assertNotIn('v1',final['dependencies']);self.assertNotIn('v2',final['dependencies'])
        self.assertEqual(self.rt.task('job','v1')['status'],first_state);self.assertEqual(self.rt.task('job','v2')['status'],second_state);self.assertNotEqual(first_state,'completed');self.assertNotEqual(second_state,'completed')
        self.assertEqual(self.rt.task('job','v3')['status'],'completed');self.assertEqual(Path(first['blob']).read_bytes(),raw)
        self.assertNotEqual(first['sha256'],second['sha256']);self.assertNotEqual(second['sha256'],third['sha256'])
        self.delegate('peers',[worker('unknown'),worker('slow')]);aid=self.rt.task('job','unknown')['latest']
        self.factory.sessions[aid]['status']=dict(status='uncertain',reason='Controlled missing external receipt');self.rt.tick('job')
        calls=list(self.factory.calls);self.work('slow','Available unreviewed peer.');delivery=self.export_partial(third)
        self.assertEqual(self.factory.calls,calls);labels={x['artifact']:x['review_status'] for x in delivery['candidates']}
        self.assertEqual(labels[first['id']],'requires_attention');self.assertEqual(labels[third['id']],'reviewed');self.assertIn('missing',delivery['missing_formats'])
        self.assertFalse(any(self.rt.spec(self.rt.task('job',t['id'])).get('execution') for t in self.rt.status('job')['tasks']))

    def inspection_task(self,artifact,dependencies=None):
        return dict(id='probe_review',review_of='new_candidate',instruction='Inspect historical evidence',outputs=[],dependencies=list(dependencies or []),
            inputs=[dict(artifact=artifact['id'],path='old/candidate.txt',media_type='application/x-fixture',purpose='Historical candidate',authority='Evidence, not approval')])

    def test_exact_attempt_binding_preserves_explicit_dependencies_and_equal_byte_identities(self):
        from orchestrator.review_inspection import bind
        first=self.make('v1','Price: 99; target 3, supported 1, gap 2.');self.judge('v1','revise')
        preview=self.rt.output('job','v1','outputs/work-inspect/preview.png')
        saved=dict(self.rt.task('job','v1'))
        # Historical reference cannot silently follow a changed task head.
        with self.rt.transaction():self.rt.db.execute("update production_tasks set latest=NULL where run='job' and id='v1'")
        task=self.inspection_task(first,['v1']);before=copy.deepcopy(task['inputs'])
        rows=bind([task],job_owner.original(self.rt,'job')['job_owner'],self.rt,'job')
        self.assertEqual(task['dependencies'],['v1']);self.assertEqual(task['inputs'][0],before[0])
        self.assertEqual(rows[0]['collected_attempt'],first['attempt'])
        self.assertTrue(any(i.get('artifact')==preview['id'] for i in task['inputs']))
        self.assertFalse(any(i.get('from_task')=='v1' for i in task['inputs']))
        with self.rt.transaction():self.rt.db.execute("update production_tasks set latest=? where run='job' and id='v1'",(saved['latest'],))
        # Another identity with identical bytes is not the same inspection export.
        path=self.home/'duplicate.png';path.write_bytes(Path(preview['blob']).read_bytes());duplicate=self.rt.register(path,'Synthetic ambiguous export')
        with self.rt.transaction():self.rt.db.execute('update production_artifacts set attempt=?,path=? where id=?',(first['attempt'],preview['path'],duplicate))
        with self.assertRaisesRegex(ValueError,'ambiguous'):bind([self.inspection_task(first)],job_owner.original(self.rt,'job')['job_owner'],self.rt,'job')

    def test_uncertain_pending_missing_and_tampered_inspections_never_replay(self):
        from orchestrator.review_inspection import bind
        first=self.make('v1','Price: 99; target 3, supported 1, gap 2.');self.judge('v1','revise')
        grant=job_owner.original(self.rt,'job')['job_owner'];attempt=dict(self.rt.db.execute('select * from production_attempts where id=?',(first['attempt'],)).fetchone());calls=list(self.factory.calls)
        for state,receipt in [('uncertain',json.loads(attempt['receipt'])),('running',json.loads(attempt['receipt'])),('completed',dict(status='finished',pending_requests=['unknown']))]:
            with self.rt.transaction():self.rt.db.execute('update production_attempts set state=?,receipt=? where id=?',(state,json.dumps(receipt),first['attempt']))
            with self.subTest(state=state),self.assertRaisesRegex(ValueError,'conclusive'):bind([self.inspection_task(first)],grant,self.rt,'job')
        with self.rt.transaction():self.rt.db.execute('update production_attempts set state=?,receipt=? where id=?',(attempt['state'],attempt['receipt'],first['attempt']))
        control=Path(json.loads(attempt['session'])['control']);p=next(p for p in (control/'work-operations').glob('*/outcome.json') if json.loads(p.with_name('intent.json').read_text())['step']=='inspect');raw=p.read_bytes()
        try:
            p.unlink()
            with self.assertRaisesRegex(ValueError,'uncertain'):bind([self.inspection_task(first)],grant,self.rt,'job')
            p.write_bytes(raw);bad=json.loads(raw);next(iter(bad['outputs'].values()))['sha256']='0'*64;p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'differs'):bind([self.inspection_task(first)],grant,self.rt,'job')
        finally:p.write_bytes(raw)
        self.assertEqual(self.factory.calls,calls);self.assertNotEqual(self.rt.task('job','v1')['status'],'completed')
