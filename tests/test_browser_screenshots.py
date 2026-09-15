"""Capture authority, byte delivery and recovery; tiny generated PNG fixtures."""
from contextlib import nullcontext
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from orchestrator import contracts as c,executors,worker_capabilities as workers
from orchestrator.browser_contract import png_info,validate_captures
from orchestrator.browser_worker import run
from orchestrator.gemini_worker import Files
from orchestrator.runtime import Runtime
from orchestrator.workers import atomic
from task_relay.general_browser import Session
from task_relay.browser_journal import UncertainAction
from task_relay.filesystem import FILES
from tests.test_general_browser import Driver,policy,browser_graph
from tests.test_gemini_executor import CONFIG,report
from tests.test_orchestrator import FakeFactory


def png():
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\xff\0\0'*2+b'\0'+b'\0\xff\0'*2))+chunk(b'IEND',b'')


class CaptureDriver(Driver):
    def __init__(self):super().__init__();self.captures=0
    def screenshot(self,tab):
        if self.before:self.before()
        self.captures+=1
        if self.fail:raise OSError('Screenshot response lost')
        return png()


def capture_graph():
    value=browser_graph();producer=value['tasks'][0]
    producer['browser']=policy(interaction_scope='',screenshots=['map.png'])
    producer['outputs']=[dict(path='map.png',purpose='User reviews captured viewport',media_type='image/png'),
                         dict(path='map.png.json',purpose='Capture provenance',media_type='application/json')]
    producer['limits']=executors.limits_for(value['backend'])
    reviewer=value['tasks'][1]
    reviewer['inputs']=[dict(from_task=producer['id'],output=o['path'],path='candidate/'+o['path'],
                           purpose=o['purpose'],authority='Unaccepted candidate',media_type=o['media_type']) for o in producer['outputs']]
    return value


class CaptureClient:
    def __init__(self,frozen,provider):self.frozen=frozen;self.provider=provider;self.calls=[]
    def request(self,endpoint,payload,**kwargs):
        self.calls.append(copy.deepcopy(payload));n=len(self.calls)
        if n==1:name,args='browser_open',{'url':self.frozen['browser']['origins'][0]+'/fixture'}
        elif n==2:
            if self.provider=='gemini':previous=payload['contents'][-1]['parts'][0]['functionResponse']['response']
            else:previous=json.loads(payload['input'][-1]['output'] if self.provider=='openai' else payload['messages'][-1]['content'])
            name,args='browser_screenshot',dict(tab=previous['tab'],observation=previous['observation'],path='map.png',purpose='Capture the requested fixture viewport')
        else:name,args='finish',report(self.frozen)
        if self.provider=='gemini':return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        call=dict(name=name,arguments=json.dumps(args))
        if self.provider=='openai':return {'id':str(n),'status':'completed','output':[dict(type='function_call',call_id=str(n),**call)]}
        return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[dict(id=str(n),type='function',function=call)]}}]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.ws=self.root/'workspace';self.ws.mkdir();(self.ws/'.relay').mkdir()
        self.frozen=c.assignment(capture_graph()['tasks'][0]);self.frozen.update(assignment_id='capture-job',workspace=str(self.ws),backend=capture_graph()['backend'])
        self.db=sqlite3.connect(':memory:');self.driver=CaptureDriver();self.files=Files(self.frozen)
        self.session=Session(self.db,'capture-job',self.frozen['browser'],self.driver,self.files)
        self.page=self.session.call('open','browser_open',{'url':'https://example.test/map'})
    def tearDown(self):self.db.close();self.temp.cleanup()
    def args(self):return dict(tab=self.page['tab'],observation=self.page['observation'],path='map.png',purpose='Save the requested view')

    def test_capture_writes_exact_bytes_provenance_and_duplicate_returns_without_recapture(self):
        def before():
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(self.session.journal.pending('fixture')[0]['status'],'intent')
        self.driver.before=before
        result=self.session.call('capture','browser_screenshot',self.args())
        self.assertEqual((self.ws/'map.png').read_bytes(),png())
        receipt=json.loads((self.ws/'map.png.json').read_text())
        self.assertEqual(receipt['url'],'https://example.test/map');self.assertFalse(receipt['visual_content_inspected'])
        self.assertEqual(receipt['sha256'],hashlib.sha256(png()).hexdigest())
        validate_captures(self.frozen,self.ws)
        reopened=Session(self.db,'capture-job',self.frozen['browser'],CaptureDriver(),self.files)
        self.assertEqual(reopened.call('capture','browser_screenshot',self.args()),result)
        self.assertEqual(self.driver.captures,1)
        with self.assertRaisesRegex(ValueError,'already written'):self.session.call('again','browser_screenshot',self.args())
        (self.ws/'map.png.json').write_text(json.dumps({**receipt,'sha256':'changed'}))
        with self.assertRaisesRegex(ValueError,'provenance'):validate_captures(self.frozen,self.ws)
        (self.ws/'map.png.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'provenance'):validate_captures(self.frozen,self.ws)

    def test_stale_origin_and_missing_grants_fail_before_capture(self):
        for path in ('../map.png','other.png'):
            with self.assertRaisesRegex(ValueError,'grant'):self.session.call('bad','browser_screenshot',{**self.args(),'path':path})
        self.driver.pages[self.page['tab']]['url']='https://outside.test'
        with self.assertRaisesRegex(ValueError,'changed'):self.session.call('bad','browser_screenshot',self.args())
        self.assertEqual(self.driver.captures,0)

    def test_failed_capture_and_interrupted_pair_preserve_uncertainty_without_replay(self):
        original=FILES.write
        def fail_receipt(grant,path,raw,**kwargs):
            if path.endswith('.json'):raise OSError('Disk full')
            return original(grant,path,raw,**kwargs)
        with patch.object(FILES,'write',side_effect=fail_receipt):
            with self.assertRaises(UncertainAction):self.session.call('capture','browser_screenshot',self.args())
        self.assertEqual((self.ws/'map.png').read_bytes(),png())
        self.assertFalse((self.ws/'map.png.json').exists())
        with self.assertRaises(UncertainAction):self.session.call('capture','browser_screenshot',self.args())
        self.assertEqual(self.driver.captures,1)

    def test_capture_timeout_cannot_be_retried_under_another_action_id(self):
        self.driver.fail=True
        with self.assertRaises(UncertainAction):self.session.call('capture','browser_screenshot',self.args())
        self.page=self.session.call('read','browser_read',{'tab':self.page['tab']})
        self.driver.fail=False
        with self.assertRaises(UncertainAction):self.session.call('new-id','browser_screenshot',self.args())
        self.assertEqual(self.driver.captures,1);self.assertFalse((self.ws/'map.png').exists())

    def test_output_budget_and_existing_file_refused(self):
        self.frozen['limits']['output_bytes']=1
        with self.assertRaisesRegex(ValueError,'budget'):self.files.write_capture('map.png',png(),{})
        self.assertFalse((self.ws/'map.png').exists())
        self.frozen['limits']['output_bytes']=100000
        (self.ws/'map.png').write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):self.files.write_capture('map.png',png(),{})
        self.assertEqual((self.ws/'map.png').read_bytes(),b'preserve')

    def test_reserved_outputs_cannot_be_fabricated_by_text_tools_or_symlinks(self):
        for path in ('map.png','map.png.json'):
            with self.assertRaisesRegex(ValueError,'browser_screenshot'):self.files.call('file_write',dict(path=path,text='fake'))
        target=self.root/'untouched';target.write_bytes(b'preserve');(self.ws/'map.png').symlink_to(target)
        with self.assertRaises(ValueError):self.files.write_capture('map.png',png(),{})
        self.assertEqual(target.read_bytes(),b'preserve')

    def test_png_input_is_metadata_only_and_text_executor_stays_text_only(self):
        raw=png();(self.ws/'input.png').write_bytes(raw)
        f=copy.deepcopy(self.frozen);f['inputs']=[dict(path='input.png',media_type='image/png',sha256=hashlib.sha256(raw).hexdigest())]
        info=Files(f).call('file_read',dict(path='input.png',offset=0,limit=100))
        self.assertEqual((info['width'],info['height']),(2,2));self.assertNotIn('text',info)
        f['backend']['type']='gemini-agent';f['tools']=['files'];f.pop('browser')
        with self.assertRaises(UnicodeError):Files(f)
        with self.assertRaises(ValueError):png_info(raw[:-1])

    def test_contract_and_worker_resolution_accept_only_granted_png_exception(self):
        p=capture_graph();c.plan(p)
        t=p['tasks'][0];t['worker']={'requires':['browser.use','browser.capture']}
        workers.resolve(t,[workers.entry(p['backend'])],p['backend']);c.plan(p)
        for change in ('grant','sidecar','type','download'):
            p=capture_graph();t=p['tasks'][0]
            if change=='grant':t['browser'].pop('screenshots')
            elif change=='sidecar':t['outputs'].pop()
            elif change=='type':t['outputs'][0]['media_type']='application/pdf'
            else:t['browser']['downloads']=['map.png']
            with self.assertRaises(ValueError):c.plan(p)

    def test_all_provider_loops_deliver_png_without_transmitting_pixels(self):
        for provider in ('gemini','openai','qwen'):
            with self.subTest(provider=provider):
                ws=self.root/provider;ws.mkdir();(ws/'.relay').mkdir();control=ws/'control';control.mkdir()
                f=copy.deepcopy(self.frozen);f['workspace']=str(ws);f['backend']={'type':provider+'-browser','model':'fixture-model'}
                config=CONFIG if provider=='gemini' else {'api_key':'fixture-only','model':'fixture-model'}
                atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,f['backend'])})
                client=CaptureClient(f,provider)
                with sqlite3.connect(':memory:') as db:
                    result=run(f,control,db,self.root,client=client,config_reader=lambda:(config,f['backend']),driver_context=nullcontext(CaptureDriver()))
                self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.calls),3)
                self.assertEqual((ws/'map.png').read_bytes(),png());validate_captures(f,ws)
                import base64
                self.assertNotIn(base64.b64encode(png()).decode(),json.dumps(client.calls))

    def test_runtime_collects_png_and_freezes_exact_reviewer_input(self):
        factory=FakeFactory();rt=Runtime(self.root/'runtime',factory)
        try:
            rt.create(capture_graph());rt.tick('demo');aid=rt.task('demo','produce')['latest']
            record=factory.sessions[aid];f=record['frozen'];driver=CaptureDriver()
            with sqlite3.connect(':memory:') as db:
                session=Session(db,f['assignment_id'],f['browser'],driver,Files(f))
                page=session.call('open','browser_open',{'url':'https://example.test/map'})
                session.call('capture','browser_screenshot',dict(tab=page['tab'],observation=page['observation'],path='map.png',purpose='Fixture capture'))
            atomic(Path(f['workspace'])/'.relay/result.json',report(f))
            record['status']={'status':'finished','exit_code':0}
            rt.tick('demo')
            artifact=rt.output('demo','produce','map.png');self.assertEqual(Path(artifact['blob']).read_bytes(),png())
            reviewer=factory.sessions[rt.task('demo','review')['latest']]['frozen']
            files=Files(reviewer);info=files.call('file_read',dict(path='candidate/map.png',offset=0,limit=100))
            self.assertEqual(info['sha256'],artifact['sha256']);self.assertFalse(info['visual_content_inspected'])
        finally:rt.db.close()

    def test_cli_preparation_declares_capture_pairs_without_dispatch(self):
        from task_relay.browser_cli import prepare
        rt=Runtime(self.root/'prepared');request=self.root/'request.txt';request.write_text('Capture the public fixture map.')
        try:
            plan=prepare(rt,'maps',request,self.frozen['backend'],self.frozen['browser'])
            producer,reviewer=plan['tasks']
            self.assertEqual(producer['selection_outputs'],['map.png','map.png.json'])
            self.assertEqual(reviewer['browser']['screenshots'],[])
            self.assertTrue(any(i.get('media_type')=='image/png' for i in reviewer['inputs']))
            self.assertEqual(rt.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
        finally:rt.db.close()


from tests import test_executor_planning as planning_fixtures


class PlanningTests(unittest.TestCase):
    setUp=planning_fixtures.Tests.setUp;tearDown=planning_fixtures.Tests.tearDown
    request=planning_fixtures.Tests.request;action=planning_fixtures.Tests.action;queue=planning_fixtures.Tests.queue
    row=planning_fixtures.Tests.row;response=planning_fixtures.Tests.response;click=planning_fixtures.Tests.click;start=planning_fixtures.Tests.start

    def test_capture_plan_freezes_png_outputs_scope_and_review_inputs(self):
        import production_planning as planning
        backend={'type':'gemini-agent','model':'fixture-model'}
        with patch.object(executors,'configured',return_value=(CONFIG,backend)),patch.object(executors,'available'):
            self.queue(action=self.action(executor='gemini-browser'),text='Capture one viewport of https://example.test/map as map.png. I will review the image.')
            response=self.response();response['plan']['tasks']=capture_graph()['tasks']
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
            row=self.row()
            if row['status']!='ready':raise AssertionError(row['error'])
            self.assertIn('map.png',planning.preview(row));self.start(row)
            plan=json.loads(self.state.db.execute('SELECT plan FROM production_runs').fetchone()[0])
            self.assertEqual(plan['tasks'][0]['browser']['screenshots'],['map.png'])
            self.assertEqual(plan['tasks'][1]['inputs'][0]['media_type'],'image/png')


if __name__=='__main__':unittest.main()
