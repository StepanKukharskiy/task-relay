"""Small data/transport fixtures; real encoding is the explicit qualification script."""
import copy
import json
from pathlib import Path
import tempfile
import os
import sys
import time
import subprocess
import unittest
from unittest.mock import patch

from orchestrator import contracts,execution,reel_contract as contract,reel_document as document,worker_capabilities as workers,executors
from orchestrator.runtime import Runtime,file_hash
from task_relay import media_host,production_planning as planning
from tests import test_mixed_execution as mixed,test_production_planning as planning_fixture
from tests.test_orchestrator import plan


def fixture():
    return dict(version=1,width=320,height=568,fps=15,background='#102030',foreground='#ffffff',accent='#82cfff',audio=None,
        scenes=[dict(duration=2,title='Relay',body='A bounded scene.',image=None,entrance='up',narration='')])


def operation(inputs,**kwargs):
    spec=execution.REGISTRY['media.compose']
    return dict(id='render',role='procedure',objective='Render a reel',instruction='Compose the reviewed scene specification.',
        execution=dict(capability='media.compose',version=1,parameters={}),inputs=inputs,
        outputs=[dict(path=p,media_type=m,purpose='Reel delivery') for p,m in contract.OUTPUTS.items()],
        criteria=copy.deepcopy(spec['criteria']),user_gate='Visually review and select this reel',**kwargs)


class ContractTests(unittest.TestCase):
    def test_rejects_code_urls_traversal_unknown_assets_and_bad_pacing(self):
        changes=[lambda v:v.update(html='<script/>'),lambda v:v.update(width=True),lambda v:v.update(fps=60),
            lambda v:v.update(background='red;url(https://example.com)'),lambda v:v['scenes'][0].update(duration=float('nan')),
            lambda v:v['scenes'][0].update(duration=.51),lambda v:v['scenes'][0].update(image='../photo.png'),
            lambda v:v['scenes'][0].update(image='https://example.com/photo.png'),lambda v:v['scenes'][0].update(image='assets/photo.png'),
            lambda v:v['scenes'][0].update(narration='one '*7),lambda v:v['scenes'][0].update(body='one '*8)]
        for change in changes:
            value=fixture();change(value)
            with self.subTest(value=value),self.assertRaises(ValueError):contract.validate(value)
        with self.assertRaisesRegex(ValueError,'Duplicate'):contract.load('{"version":1,"version":1}')

    def test_declared_assets_and_pacing_are_data_not_execution(self):
        value=fixture();value['scenes'][0].update(image='assets/p.png',narration='one two three four five six')
        self.assertEqual(contract.validate(value,{'assets/p.png':'image/png'}),value)
        inp=dict(artifact='spec',path='reel.json',media_type='application/json',authority='Reviewed',purpose='Scene specification')
        contracts.assignment(operation([inp]))
        for alter in (lambda t:t['inputs'].append(inp),lambda t:t['outputs'].pop(),lambda t:t.update(max_attempts=2),
                      lambda t:t['execution'].update(parameters={'command':'render'}),lambda t:t.update(tools=['shell'])):
            task=operation([copy.deepcopy(inp)]);alter(task)
            with self.assertRaises(ValueError):contracts.assignment(task)

    def test_compile_escapes_markup_and_has_no_remote_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);font=root/'font';font.write_bytes(b'fixture font')
            value=fixture();value['scenes'][0].update(title='</script><img onerror=alert(1)>',body='')
            document.compile_project(value,root,root/'project',{'paths':{'font':str(font)}})
            html=(root/'project/index.html').read_text()
            self.assertIn('&lt;/script&gt;',html);self.assertNotIn('src="https:',html)
            self.assertIn('data-no-timeline',html);self.assertIn('.pause()',html)

    def test_probe_rejects_wrong_codec_frames_duration_and_audio(self):
        probe={'streams':[dict(codec_type='video',codec_name='h264',width=320,height=568,avg_frame_rate='15/1',nb_frames='30')],
            'format':{'duration':'2.0'}}
        self.assertEqual(document.verify_probe(probe,fixture())['frames'],30)
        for key,value in [('width',1080),('codec_name','vp9'),('nb_frames','29'),('avg_frame_rate','30/1')]:
            bad=copy.deepcopy(probe);bad['streams'][0][key]=value
            with self.assertRaises(ValueError):document.verify_probe(bad,fixture())
        bad=copy.deepcopy(probe);bad['streams'].append({'codec_type':'audio'})
        with self.assertRaisesRegex(ValueError,'audio'):document.verify_probe(bad,fixture())

    def test_same_provider_can_author_and_review_without_shell(self):
        catalog=[workers.entry(dict(type=p+'-code',model='fixture',runtime='a'*64)) for p in executors.PROVIDERS]
        catalog += [workers.entry(dict(type=p+'-agent',model='fixture')) for p in executors.PROVIDERS]
        for provider in executors.PROVIDERS:
            default=dict(type=provider+'-agent',model='fixture')
            author={'worker':{'requires':['files.text']},'outputs':[{'path':'reel.json','media_type':'application/json'}]}
            reviewer={'worker':{'requires':['files.binary','code.execute']},'inputs':[{'path':p,'media_type':m} for p,m in contract.OUTPUTS.items()]}
            workers.resolve(author,catalog,default);workers.resolve(reviewer,catalog,default)
            self.assertEqual(author['worker']['executor'],provider+'-agent')
            self.assertEqual(reviewer['worker']['executor'],provider+'-code')
            self.assertNotIn('shell',reviewer['tools'])
        locked={'worker':{'requires':['files.binary']},'inputs':[{'path':'candidate.mp4','media_type':'video/mp4'}]}
        with self.assertRaisesRegex(ValueError,'No eligible'):workers.resolve(locked,[workers.entry(default)],default)

    def test_clean_environment_has_no_provider_secrets(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'OPENAI_API_KEY':'never-copy','ANTHROPIC_API_KEY':'never-copy'}):
            env=media_host.environment({'paths':{k:'/usr/bin/fixture' for k in media_host.KEYS}},Path(folder))
            self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('never-copy',env.values())
            self.assertEqual(env['DO_NOT_TRACK'],'1')

    def test_unqualified_or_changed_runtime_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'config.json'
            with patch.object(media_host,'config_path',return_value=config),self.assertRaisesRegex(ValueError,'not configured'):
                media_host.available()
            config.write_text(json.dumps(dict(qualified=True,runtime={'paths':{},'version':'old'},implementation={'old':'hash'})))
            with patch.object(media_host,'config_path',return_value=config),patch.object(media_host,'identity',return_value={'paths':{},'version':'new'}):
                with self.assertRaisesRegex(ValueError,'changed'):media_host.available()

    def test_missing_render_receipt_stays_uncertain_after_supervisor_exit(self):
        from orchestrator.adapters import RegisteredFactory
        from orchestrator.workers import CodexFactory
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media-intent.json').write_text('{}')
            session={'control':folder,'execution':{'capability':'media.compose','version':1,'parameters':{}}}
            with patch.object(CodexFactory,'inspect',return_value={'status':'finished'}):
                result=RegisteredFactory().inspect(session)
            self.assertEqual(result['status'],'uncertain');self.assertEqual(result['external_outcome'],'unknown')


class RuntimeTests(unittest.TestCase):
    tearDown=mixed.Tests.tearDown
    def setUp(self):
        mixed.Tests.setUp(self)
        self.runtime={'adapter':'fixture','paths':{}}
        for target in (patch.object(media_host,'available',return_value=self.runtime),patch.object(document,'available',return_value=self.runtime)):
            target.start();self.addCleanup(target.stop)
        source=self.root/'reel.json';source.write_text(json.dumps(fixture()))
        aid=self.rt.register(source,'Scene plan',path='reel.json')
        self.scene=dict(artifact=aid,path='reel.json',purpose='Reel scene plan',authority='Reviewed fixture',media_type='application/json')

    def render_fixture(self,value,workspace,work,out,runtime,seconds,maximum):
        for name in ('reel.mp4','project.zip','contact-sheet.png'):(out/name).write_bytes(b'text fixture, not media')
        return {'visual_review':'not_performed','files':{n:file_hash(out/n) for n in ('reel.mp4','project.zip','contact-sheet.png')}}

    def test_registered_dispatch_keeps_identity_receipt_and_selection_gate(self):
        self.rt.create(plan([operation([self.scene])]))
        with patch.object(document,'render',side_effect=self.render_fixture) as render:
            self.rt.tick('demo');self.rt.tick('demo');self.rt.tick('demo')
        status=self.rt.status('demo');self.assertEqual(status['status'],'awaiting_user',status)
        self.assertEqual(render.call_count,1);self.assertEqual(len(status['attempts']),1)
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE run=?',('demo',)).fetchone()[0]);self.assertEqual(frozen['media_runtime'],self.runtime)
        receipt=json.loads(Path(self.rt.output('demo','render','delivery/verification.json')['blob']).read_text())
        self.assertFalse(receipt['selected']);self.assertTrue(receipt['passed'])
        self.assertEqual(receipt['input_versions'][0]['artifact'],self.scene['artifact'])

    def test_partial_render_failure_retains_evidence_and_never_replays(self):
        def fail(*args):
            (args[3]/'reel.mp4').write_bytes(b'partial')
            raise ValueError('encoding failed')
        self.rt.create(plan([operation([self.scene])]))
        with patch.object(document,'render',side_effect=fail) as render:
            self.rt.tick('demo');self.rt.tick('demo');self.rt.tick('demo')
        status=self.rt.status('demo');self.assertEqual(status['status'],'blocked',status);self.assertEqual(render.call_count,1)
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE run=?',('demo',)).fetchone()[0]);workspace=Path(frozen['workspace'])
        self.assertFalse((workspace/'.relay/result.json').exists())
        receipt=json.loads((workspace/'delivery/verification.json').read_text());self.assertFalse(receipt['passed'])
        self.assertIn('encoding failed',receipt['error'])
        self.assertEqual((workspace/'delivery/reel.mp4').read_bytes(),b'partial')

    def test_runtime_drift_blocks_before_render_and_does_not_consume_retry(self):
        self.rt.create(plan([operation([self.scene])]))
        # Claim freezes one runtime, child observes a different one.
        with patch.object(document,'available',return_value={'adapter':'changed'}),patch.object(document,'render') as render:
            self.rt.tick('demo');self.rt.tick('demo');self.rt.tick('demo')
        self.assertFalse(render.called)
        status=self.rt.status('demo');self.assertEqual(status['status'],'blocked');self.assertEqual(len(status['attempts']),1)

    def test_output_budget_failure_marks_partial_delivery_unapproved(self):
        self.rt.create(plan([operation([self.scene],limits={'output_bytes':50})]))
        with patch.object(document,'render',side_effect=self.render_fixture):
            self.rt.tick('demo');self.rt.tick('demo')
        status=self.rt.status('demo');self.assertEqual(status['status'],'blocked')
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE run=?',('demo',)).fetchone()[0])
        receipt=json.loads((Path(frozen['workspace'])/'delivery/verification.json').read_text())
        self.assertFalse(receipt['passed']);self.assertIn('byte budget',receipt['error'])


class PlanningTests(unittest.TestCase):
    tearDown=planning_fixture.Tests.tearDown
    request=planning_fixture.Tests.request
    action=planning_fixture.Tests.action
    queue=planning_fixture.Tests.queue
    row=planning_fixture.Tests.row
    response=planning_fixture.Tests.response

    def setUp(self):
        planning_fixture.Tests.setUp(self)
        p=patch.object(document,'available',return_value={'adapter':'fixture'});p.start();self.addCleanup(p.stop)

    def reel_response(self):
        result=self.response();producer,reviewer=result['plan']['tasks'];producer.pop('user_gate',None)
        producer['outputs']=[dict(path='reel.json',purpose='Scene plan',media_type='application/json')]
        reviewer['inputs']=[dict(from_task='produce',output='reel.json',path='reel.json',purpose='Review scene plan',authority='Candidate',media_type='application/json')]
        render=contracts.assignment(operation([dict(from_task='produce',output='reel.json',path='reel.json',purpose='Render plan',authority='Reviewed',media_type='application/json')],dependencies=['produce','review']))
        check=copy.deepcopy(reviewer);check.update(id='render-review',review_of='render',dependencies=['render'],criteria=render['criteria'].copy(),
            inputs=[dict(from_task='render',output=o['path'],path='candidate/'+o['path'],purpose='Review delivery',authority='Candidate',media_type=o['media_type']) for o in render['outputs']])
        result['plan']['tasks'] += [render,check]
        return result

    def test_planner_captures_contract_and_requires_review_before_and_after_render(self):
        row=dict(self.queue(action=self.action(step_capabilities=['media.compose'])))
        _,resolved=planning.validate_result(json.dumps(self.reel_response()),row)
        self.assertEqual(resolved['tasks'][2]['execution']['capability'],'media.compose')
        sources=json.loads(row['context'])['sources']
        self.assertTrue(any(s['path']=='operation-support/media.compose/contract.json' for s in sources))
        for change in (lambda ts:ts[2].pop('user_gate'),lambda ts:ts.pop(),lambda ts:ts[2].update(dependencies=['produce'])):
            result=self.reel_response();change(result['plan']['tasks'])
            with self.assertRaises(ValueError):planning.validate_result(json.dumps(result),row)

    def test_each_provider_keeps_text_authorship_and_binary_review_on_its_own_profiles(self):
        row=dict(self.queue(action=self.action(step_capabilities=['media.compose'])))
        catalog=[workers.entry(dict(type=p+'-code',model='fixture',runtime='a'*64)) for p in executors.PROVIDERS]
        catalog += [workers.entry(dict(type=p+'-agent',model='fixture')) for p in executors.PROVIDERS]
        for provider in executors.PROVIDERS:
            options=json.loads(row['options']);payload=json.loads(row['context'])
            options.update(backend=dict(type=provider+'-agent',model='fixture'),worker_catalog=catalog,tools=['files'])
            payload['options']=options
            source={'artifact':'photo','path':'assets/photo.png','purpose':'Full source screenshot','authority':'User source',
                    'media_type':'image/png','sha256':'f'*64,'bytes':100,'visual_reference':True}
            payload['sources'].append(source);payload['required_artifacts'].append('photo')
            candidate={**row,'options':json.dumps(options),'context':json.dumps(payload)}
            result=self.reel_response()
            result['plan']['tasks'][2]['inputs'].append({k:source[k] for k in ('artifact','path','purpose','authority','media_type')})
            for task in result['plan']['tasks']:
                if task.get('execution'):continue
                task.pop('tools',None);task['worker']={'requires':['files.binary','code.execute'] if task.get('review_of')=='render' else ['files.text']}
            _,resolved=planning.validate_result(json.dumps(result),candidate)
            with self.subTest(provider=provider):
                self.assertEqual(resolved['tasks'][0]['worker']['executor'],provider+'-agent')
                self.assertEqual(resolved['tasks'][1]['worker']['executor'],provider+'-agent')
                self.assertEqual(resolved['tasks'][3]['worker']['executor'],provider+'-code')
                self.assertFalse(any(i.get('artifact')=='photo' for i in resolved['tasks'][0]['inputs']))
                self.assertTrue(any(i.get('artifact')=='photo' for i in resolved['tasks'][2]['inputs']))


@unittest.skipUnless(sys.platform=='darwin','macOS rendering guardian')
class HostTests(unittest.TestCase):
    def test_owner_death_closes_lifetime_pipe_and_stops_command(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();pidfile=root/'owned.txt'
            runtime={'paths':{k:str(Path(sys.executable).resolve()) for k in media_host.KEYS}}
            code='from pathlib import Path;import os,time;Path('+repr(str(pidfile))+').write_text(str(os.getpid()));time.sleep(60)'
            owner_code=('from task_relay import media_host\nfrom pathlib import Path\nmedia_host.run('
                +repr(runtime)+',Path('+repr(str(root/'command'))+'),'+repr([sys.executable,'-c',code])
                +',Path('+repr(str(root))+'),60,1000000)')
            owner=subprocess.Popen([sys.executable,'-c',owner_code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+5
                while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(pidfile.exists());pid=int(pidfile.read_text())
                owner.kill();owner.wait(timeout=5)
                outcome=root/'command/outcome.json';deadline=time.monotonic()+5
                while not outcome.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertIn('owner exited',json.loads(outcome.read_text())['error'])
                with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            finally:
                if owner.poll() is None:owner.kill()
                owner.wait(timeout=5)

    def test_timeout_stops_detached_descendant_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();script=root/'fixture.py';pidfile=root/'child.txt'
            script.write_text('import subprocess,sys,time\nfrom pathlib import Path\n'
                'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True)\n'
                'Path('+repr(str(pidfile))+').write_text(str(p.pid))\ntime.sleep(60)\n')
            runtime={'paths':{k:str(Path(sys.executable).resolve()) for k in media_host.KEYS}}
            with self.assertRaisesRegex(ValueError,'deadline'):
                media_host.run(runtime,root/'command',[sys.executable,str(script)],root,1,1000000)
            pid=int(pidfile.read_text());deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                try:os.kill(pid,0)
                except ProcessLookupError:break
                time.sleep(.05)
            else:self.fail('Detached media descendant survived timeout')
            self.assertIn('deadline',json.loads((root/'command/outcome.json').read_text())['error'])

    def test_guard_monitors_delivery_outside_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();work=root/'work';work.mkdir();out=root/'delivery';out.mkdir()
            runtime={'paths':{k:str(Path(sys.executable).resolve()) for k in media_host.KEYS}}
            code='from pathlib import Path;import time;Path('+repr(str(out/'partial.mp4'))+').write_bytes(b"x"*200000);time.sleep(60)'
            with self.assertRaisesRegex(ValueError,'working-file limit'):
                media_host.run(runtime,work/'command',[sys.executable,'-c',code],work,3,100000,output_root=out)
            self.assertTrue((out/'partial.mp4').is_file())
