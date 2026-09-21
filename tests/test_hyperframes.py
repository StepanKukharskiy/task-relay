"""Small source/receipt fixtures; real media is qualified separately."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from orchestrator import contracts,execution,corrections,executors,worker_capabilities as workers
from orchestrator import hyperframes_contract as contract,hyperframes_project as project
from orchestrator.runtime import file_hash
from task_relay import media_host,production_planning as planning
from scripts.qualify_hyperframes import fixture
from tests import test_mixed_execution as mixed,test_production_planning as pf
from tests.test_orchestrator import plan,pair


def operation(inputs,cap='hyperframes.preview',**kwargs):
    spec=execution.REGISTRY[cap]
    return dict(id='preview' if cap.endswith('preview') else 'render',role='procedure',objective='Execute authored project',
        instruction='Execute the exact authored source.',execution=dict(capability=cap,version=1,parameters={}),inputs=inputs,
        outputs=[dict(path=p,media_type=m,purpose='Project delivery') for p,m in spec['outputs'].items()],
        criteria=copy.deepcopy(spec['criteria']),user_gate='Visually review this exact candidate',
        selection_outputs=list(spec['outputs']),**kwargs)


def graph():
    g=pair(max_attempts=2);author,review=g['tasks'];author.pop('user_gate',None)
    author['outputs']=[dict(path='project.json',media_type='application/json',purpose='Full authored source')]
    source=dict(from_task='produce',output='project.json',path='project.json',media_type='application/json',purpose='Source',authority='Candidate')
    review['inputs']=[source.copy()]
    preview=contracts.assignment(operation([source.copy()],dependencies=['produce','review']))
    final=copy.deepcopy(review);final.update(id='preview-review',review_of='preview',dependencies=['preview'],criteria=preview['criteria'].copy(),
        inputs=[dict(from_task='preview',output=o['path'],path='candidate/'+o['path'],purpose='Review delivery',authority='Candidate',media_type=o['media_type']) for o in preview['outputs']])
    g['tasks'] += [preview,final]
    return g


class ContractTests(unittest.TestCase):
    def test_full_frontend_is_preserved_and_execution_config_rejected(self):
        original=fixture();self.assertEqual(contract.validate(original,{}),original)
        for name in ('../outside.js','/tmp/source.js','.hidden.js','package.json','hyperframes.json','node_modules/lib.js','relay-project.json'):
            bad=fixture();bad['files'][name]='anything'
            with self.subTest(name=name),self.assertRaises(ValueError):contract.validate(bad)
        for change in (lambda v:v['files'].update({'INDEX.html':'collision'}),lambda v:v['files'].update({'motion.js/child.js':'collision'}),
                       lambda v:v.update(samples=[1,.5]),lambda v:v.update(duration=3),lambda v:v['assets'].update({'assets/a.png':'missing.png'})):
            bad=fixture();change(bad)
            with self.assertRaises(ValueError):contract.validate(bad,{})

    def test_bundle_roundtrip_exact_sources_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);font=root/'font.ttf';font.write_bytes(b'font fixture')
            value=fixture();files=project.materialize(value,root,root/'source',{'paths':{'font':str(font)}})
            bundle=root/'project.zip';project.archive(root/'source',bundle)
            receipt=dict(capability='hyperframes.preview',passed=True,checks=dict(project_sha256=file_hash(bundle),project_files=files))
            self.assertEqual(project.restore(bundle,receipt,root/'restored'),value)
            self.assertEqual((root/'restored/motion.js').read_text(),value['files']['motion.js'])
            project.envelope(root/'source',root/'execution')
            self.assertEqual((root/'source/index.html').read_text(),value['files']['index.html'])
            self.assertIn('Content-Security-Policy',(root/'execution/index.html').read_text())
            receipt['checks']['project_files']['motion.js']='0'*64
            with self.assertRaisesRegex(ValueError,'hash changed'):project.restore(bundle,receipt,root/'bad')
            receipt['checks']['project_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'exact project'):project.restore(bundle,receipt,root/'bad-hash')

    def test_zip_traversal_fails_even_with_matching_archive_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);bundle=root/'bad.zip'
            with zipfile.ZipFile(bundle,'w') as z:z.writestr('../outside.txt','bad')
            receipt=dict(capability='hyperframes.preview',passed=True,checks=dict(project_sha256=file_hash(bundle),project_files={'../outside.txt':'0'*64}))
            with self.assertRaises(ValueError):project.restore(bundle,receipt,root/'restored')
            self.assertFalse((root/'outside.txt').exists())

    def test_render_needs_registered_exact_hashes(self):
        inputs=[dict(artifact='a',path='project.zip',media_type='application/zip',purpose='Exact project',authority='Selected'),
                dict(artifact='b',path='verification.json',media_type='application/json',purpose='Exact preview',authority='Selected')]
        t=operation(inputs,'hyperframes.render');t['execution']['parameters']={'project_sha256':'a'*64,'preview_sha256':'b'*64}
        contracts.assignment(t)
        for change in (lambda t:t['execution']['parameters'].update(project_sha256='wrong'),
                       lambda t:t['inputs'][0].update(from_task='author',output='project.zip'),lambda t:t['outputs'].pop()):
            bad=copy.deepcopy(t);change(bad)
            with self.assertRaises(ValueError):contracts.assignment(bad)

    def test_unfinished_intent_is_uncertain(self):
        from orchestrator.adapters import RegisteredFactory
        from orchestrator.workers import CodexFactory
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'hyperframes-intent.json').write_text('{}')
            session=dict(control=folder,execution=dict(capability='hyperframes.preview',version=1,parameters={}))
            with patch.object(CodexFactory,'inspect',return_value={'status':'finished'}):result=RegisteredFactory().inspect(session)
            self.assertEqual(result['status'],'uncertain')


class RuntimeTests(unittest.TestCase):
    tearDown=mixed.Tests.tearDown
    def setUp(self):
        mixed.Tests.setUp(self)
        font=self.root/'font.ttf';font.write_bytes(b'font fixture')
        self.runtime={'adapter':'fixture','paths':{'font':str(font)}}
        for p in (patch.object(media_host,'available',return_value=self.runtime),patch.object(project,'available',return_value=self.runtime)):
            p.start();self.addCleanup(p.stop)
        path=self.root/'project.json';path.write_text(json.dumps(fixture()));aid=self.rt.register(path,'Full source',path='project.json')
        self.source=dict(artifact=aid,path='project.json',media_type='application/json',purpose='Full project source',authority='Selected fixture')

    def run_fixture(self,value,source,work,out,runtime,seconds,maximum,**kwargs):
        for name in ('reel.mp4',) if kwargs.get('render') else ('frames.zip',):(out/name).write_bytes(b'text fixture, not media')
        (out/'contact-sheet.png').write_bytes(b'text fixture, not image')
        return dict(project_files=project.inventory(source),visual_review='not_performed')

    def test_preview_and_exact_registered_render_keep_source_and_receipts(self):
        self.rt.create(plan([operation([self.source])]))
        with patch.object(project,'run_project',side_effect=self.run_fixture):
            self.rt.tick('demo');self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')
        preview=self.rt.output('demo','preview','delivery/verification.json');bundle=self.rt.output('demo','preview','delivery/project.zip')
        receipt=json.loads(Path(preview['blob']).read_text());self.assertTrue(receipt['passed']);self.assertFalse(receipt['selected'])
        inputs=[dict(artifact=a['id'],path=n,media_type=m,purpose='Selected preview',authority='Exact approved fixture') for a,n,m in
                [(bundle,'project.zip','application/zip'),(preview,'verification.json','application/json')]]
        t=operation(inputs,'hyperframes.render');t['execution']['parameters']=dict(project_sha256=bundle['sha256'],preview_sha256=preview['sha256'])
        g=plan([t]);g['id']='encode';self.rt.create(g)
        with patch.object(project,'run_project',side_effect=self.run_fixture) as call:
            self.rt.tick('encode');self.rt.tick('encode');self.rt.tick('encode')
        self.assertEqual(self.rt.status('encode')['status'],'awaiting_user');self.assertEqual(call.call_count,1)
        self.assertEqual(self.rt.output('encode','render','delivery/project.zip')['sha256'],bundle['sha256'])

    def test_runtime_change_stops_before_frontend_execution(self):
        self.rt.create(plan([operation([self.source])]))
        with patch.object(project,'available',return_value={'adapter':'changed'}),patch.object(project,'run_project') as call:
            for _ in range(3):self.rt.tick('demo')
        self.assertFalse(call.called);self.assertEqual(self.rt.status('demo')['status'],'blocked')
        self.assertEqual(len(self.rt.status('demo')['attempts']),1)

    def test_independent_preview_revision_routes_to_source_author(self):
        g=graph();corrections.compile(g['tasks']);self.rt.create(g);self.rt.tick('demo')
        with patch.object(project,'run_project',side_effect=self.run_fixture):
            first=self.finish_source();self.rt.tick('demo');self.rt.tick('demo')
            review=self.rt.task('demo','preview-review')['latest']
            self.agent.finish(review,decision='revise')
            self.rt.tick('demo');self.rt.tick('demo')
        current=self.rt.task('demo','produce')['latest'];self.assertNotEqual(first,current)
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(current,)).fetchone()[0])
        self.assertIn('Correct the stated criterion',frozen['revision']['instruction'])
        self.assertTrue(any('preview-review' in i['path'] for i in frozen['inputs']))

    def test_failed_preview_preserves_partial_and_does_not_replay(self):
        self.rt.create(plan([operation([self.source])]))
        with patch.object(project,'run_project',side_effect=ValueError('runtime layout error')) as call:
            for _ in range(3):self.rt.tick('demo')
        self.assertEqual(call.call_count,1);self.assertEqual(self.rt.status('demo')['status'],'blocked')
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts').fetchone()[0]);ws=Path(frozen['workspace'])
        self.assertFalse(json.loads((ws/'delivery/verification.json').read_text())['passed'])
        self.assertTrue((ws/'delivery/project.zip').exists());self.assertFalse((ws/'.relay/result.json').exists())

    def finish_source(self):
        aid=self.rt.task('demo','produce')['latest'];self.agent.finish(aid)
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(aid,)).fetchone()[0])
        (Path(frozen['workspace'])/'project.json').write_text(json.dumps(fixture()))
        self.rt.tick('demo');review=self.rt.task('demo','review')['latest'];self.agent.finish(review,decision='accept');self.rt.tick('demo')
        return aid

    def test_confirmed_failure_routes_back_to_author_as_new_attempt(self):
        g=graph();corrections.compile(g['tasks']);self.rt.create(g);self.rt.tick('demo')
        with patch.object(project,'run_project',side_effect=ValueError('card overflows at 1.6 seconds')):
            first=self.finish_source();self.rt.tick('demo');self.rt.tick('demo')
        current=self.rt.task('demo','produce')['latest'];self.assertNotEqual(current,first)
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(current,)).fetchone()[0])
        self.assertIn('card overflows',frozen['revision']['instruction'])
        self.assertTrue(any(i.get('previous_delivery') for i in frozen['inputs']))
        with patch.object(project,'run_project',side_effect=self.run_fixture):
            self.finish_source();self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','preview-review')['status'],'running')
        self.assertEqual(self.rt.task('demo','preview')['attempts'],2)
        self.assertEqual(self.rt.db.execute('SELECT state FROM production_attempts WHERE id=?',(first,)).fetchone()[0],'completed')


class PlanningTests(unittest.TestCase):
    tearDown=pf.Tests.tearDown;request=pf.Tests.request;action=pf.Tests.action;queue=pf.Tests.queue;row=pf.Tests.row;response=pf.Tests.response
    def setUp(self):
        pf.Tests.setUp(self)
        p=patch.object(project,'available',return_value={'adapter':'fixture'});p.start();self.addCleanup(p.stop)
    def project_response(self):
        result=self.response();result['plan']['tasks']=[contracts.assignment(t) for t in graph()['tasks']];return result
    def test_plan_previews_and_defers_encoding_until_selection(self):
        row=dict(self.queue(action=self.action(step_capabilities=['hyperframes.preview','hyperframes.render'])))
        result=self.project_response();result['deferred_operations']={'hyperframes.render':'Render the exact selected preview in a separately approved continuation.'}
        _,resolved=planning.validate_result(json.dumps(result),row)
        self.assertEqual(resolved['tasks'][2]['execution']['capability'],'hyperframes.preview')
        sources=json.loads(row['context'])['sources'];self.assertTrue(any(s['path']=='operation-support/hyperframes.preview/contract.json' for s in sources))
        for alter in (lambda ts:ts[2].pop('user_gate'),lambda ts:ts[2].update(selection_outputs=['delivery/project.zip']),
                      lambda ts:ts[2].update(dependencies=['produce']),lambda ts:ts.pop()):
            bad=copy.deepcopy(result);alter(bad['plan']['tasks'])
            with self.assertRaises(ValueError):planning.validate_result(json.dumps(bad),row)
    def test_every_provider_authors_source_and_uses_own_binary_reviewer(self):
        row=dict(self.queue(action=self.action(step_capabilities=['hyperframes.preview'])))
        catalog=[workers.entry(dict(type=p+'-code',model='fixture',runtime='a'*64)) for p in executors.PROVIDERS]
        catalog += [workers.entry(dict(type=p+'-agent',model='fixture')) for p in executors.PROVIDERS]
        for provider in executors.PROVIDERS:
            options=json.loads(row['options']);payload=json.loads(row['context'])
            options.update(backend=dict(type=provider+'-agent',model='fixture'),worker_catalog=catalog,tools=['files']);payload['options']=options
            candidate={**row,'options':json.dumps(options),'context':json.dumps(payload)};result=self.project_response()
            for task in result['plan']['tasks']:
                if task.get('execution'):continue
                task.pop('tools',None);task['worker']={'requires':['files.binary','code.execute'] if task.get('review_of')=='preview' else ['files.text']}
            _,resolved=planning.validate_result(json.dumps(result),candidate)
            self.assertEqual(resolved['tasks'][0]['worker']['executor'],provider+'-agent')
            self.assertEqual(resolved['tasks'][3]['worker']['executor'],provider+'-code')


@unittest.skipUnless(sys.platform=='darwin','macOS host isolation')
class HostTests(unittest.TestCase):
    def test_frontend_runtime_cannot_read_or_write_outside_scoped_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();work=root/'work';work.mkdir();private=root/'private.txt';private.write_text('fixture canary')
            executable=str(Path(sys.executable).resolve());runtime={'paths':{k:executable for k in media_host.KEYS}}
            code=('from pathlib import Path\n'
                  'for path,mode in [('+repr(str(private))+',"r"),('+repr(str(root/'outside.txt'))+',"w")]:\n'
                  '    try:open(path,mode)\n'
                  '    except PermissionError:pass\n'
                  '    else:raise RuntimeError("scope escaped")\n'
                  'Path("inside.txt").write_text("allowed")\nprint("scoped access verified")')
            result=media_host.run(runtime,work/'command',[executable,'-c',code],work,10,10000000,isolated=True)
            self.assertIn('scoped access verified',result);self.assertEqual((work/'inside.txt').read_text(),'allowed')
            self.assertFalse((root/'outside.txt').exists());self.assertEqual(private.read_text(),'fixture canary')


if __name__=='__main__':unittest.main()
