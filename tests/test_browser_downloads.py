"""Original image transfers, exact handoff and no replay; no live accounts."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock,patch

from orchestrator import contracts as c,executors
from orchestrator.browser_worker import run
from orchestrator.agent_loop import Files
from orchestrator.browser_contract import validate_captures
from orchestrator.runtime import Runtime
from orchestrator.workers import atomic
from task_relay.browser_journal import UncertainAction
from task_relay.filesystem import FILES
from task_relay.general_browser import Session,PlaywrightDriver
from tests.test_browser_screenshots import capture_graph,png,CaptureClient
from tests.test_general_browser import Driver
from tests.test_gemini_executor import report,CONFIG
from tests.test_orchestrator import FakeFactory


def graph():
    value=capture_graph();task=value['tasks'][0]
    task['browser'].update(screenshots=[],downloads=['map.png'],interaction_scope='Download the selected original image once')
    return value


class DownloadDriver(Driver):
    def act(self,tab,element,operation,args,files):
        super().act(tab,element,operation,args,files)
        return png()


class DownloadClient(CaptureClient):
    def request(self,*args,**kwargs):
        value=super().request(*args,**kwargs)
        if len(self.calls)==2:
            if self.provider=='gemini':call=value['candidates'][0]['content']['parts'][0]['functionCall']
            elif self.provider=='openai':call=value['output'][0]
            else:call=value['choices'][0]['message']['tool_calls'][0]['function']
            call['name']='browser_download'
            if self.provider=='gemini':call['args']['ref']='1'
            else:call['arguments']=json.dumps({**json.loads(call['arguments']),'ref':'1'})
        return value


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.ws=self.root/'workspace';self.ws.mkdir()
        self.frozen=c.assignment(graph()['tasks'][0]);self.frozen.update(assignment_id='download-job',workspace=str(self.ws),backend=graph()['backend'])
        self.db=sqlite3.connect(':memory:');self.driver=DownloadDriver();self.files=Files(self.frozen)
        self.session=Session(self.db,'download-job',self.frozen['browser'],self.driver,self.files)
        self.page=self.session.call('open','browser_open',{'url':'https://example.test/result'})

    def tearDown(self):self.db.close();self.temp.cleanup()

    def args(self):
        return dict(tab=self.page['tab'],observation=self.page['observation'],ref='1',path='map.png',purpose='Download the original fixture image')

    def test_download_commits_identity_and_reopen_returns_receipt_without_replay(self):
        def before():
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(self.session.journal.pending('fixture')[0]['status'],'intent')
        self.driver.before=before
        result=self.session.call('download','browser_download',self.args())
        self.assertEqual((self.ws/'map.png').read_bytes(),png())
        self.assertEqual(result['download']['sha256'],hashlib.sha256(png()).hexdigest())
        receipt=json.loads((self.ws/'map.png.json').read_text())
        self.assertEqual(receipt['schema'],'relay.browser-download.v1')
        self.assertEqual(receipt['url'],'https://example.test/result')
        validate_captures(self.frozen,self.ws)
        reopened=Session(self.db,'download-job',self.frozen['browser'],DownloadDriver(),self.files)
        self.assertEqual(reopened.call('download','browser_download',self.args()),result)
        self.assertEqual(len(self.driver.actions),1)
        self.page=self.session.call('read','browser_read',{'tab':self.page['tab']})
        with self.assertRaisesRegex(ValueError,'already written'):
            self.session.call('new-id','browser_download',self.args())
        self.assertEqual(len(self.driver.actions),1)
        (self.ws/'map.png.json').write_text(json.dumps({**receipt,'mode':'viewport'}))
        with self.assertRaisesRegex(ValueError,'provenance'):validate_captures(self.frozen,self.ws)

    def test_interrupted_pair_retains_image_and_blocks_other_action_ids(self):
        original=FILES.write
        def fail(grant,path,raw,**kwargs):
            if path.endswith('.json'):raise OSError('Fixture disk full')
            return original(grant,path,raw,**kwargs)
        with patch.object(FILES,'write',side_effect=fail),self.assertRaises(UncertainAction):
            self.session.call('download','browser_download',self.args())
        self.assertEqual((self.ws/'map.png').read_bytes(),png())
        self.assertFalse((self.ws/'map.png.json').exists())
        reopened=Session(self.db,'download-job',self.frozen['browser'],DownloadDriver(),Files(self.frozen))
        with self.assertRaises(UncertainAction):reopened.call('download','browser_download',self.args())
        self.assertEqual(len(self.driver.actions),1)

    def test_lost_download_remains_uncertain_under_new_id(self):
        self.driver.fail=True
        with self.assertRaises(UncertainAction):self.session.call('download','browser_download',self.args())
        self.driver.fail=False;self.page=self.session.call('read','browser_read',{'tab':self.page['tab']})
        with self.assertRaises(UncertainAction):self.session.call('new-id','browser_download',self.args())
        self.assertEqual(len(self.driver.actions),1)

    def test_existing_or_undeclared_output_blocks_before_click(self):
        (self.ws/'map.png').write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError,'exists'):self.session.call('download','browser_download',self.args())
        with self.assertRaisesRegex(ValueError,'grant'):
            self.session.call('other','browser_download',{**self.args(),'path':'other.png'})
        self.assertFalse(self.driver.actions)
        self.assertEqual((self.ws/'map.png').read_bytes(),b'preserve')

    def test_malformed_png_and_budget_reject_without_output(self):
        with self.assertRaises(ValueError):self.files.write_download('map.png',b'not PNG',{})
        self.frozen['limits']['output_bytes']=len(png())
        with self.assertRaisesRegex(ValueError,'budget'):self.files.write_download('map.png',png(),{})
        self.assertFalse((self.ws/'map.png').exists())

    def test_contract_requires_provenance_and_text_cannot_forge_pair(self):
        for change in ('missing','transferred','jpeg'):
            task=copy.deepcopy(graph()['tasks'][0])
            if change=='missing':task['outputs'].pop()
            elif change=='transferred':task['browser']['downloads'].append('map.png.json')
            else:task['outputs'][0]['media_type']='image/jpeg'
            with self.assertRaises(ValueError):c.assignment(task)
        for path in ('map.png','map.png.json'):
            with self.assertRaisesRegex(ValueError,'browser_download'):
                self.files.call('file_write',dict(path=path,text='fabricated'))

    def test_transport_returns_original_bytes_and_text_stays_compatible(self):
        temporary=self.root/'received';temporary.write_bytes(png())
        driver=object.__new__(PlaywrightDriver);page=MagicMock();element=MagicMock()
        driver.page=lambda tab:page
        download=page.expect_download.return_value.__enter__.return_value.value
        download.path.return_value=str(temporary)
        raw=driver.interact('tab',element,'download',self.args(),self.files)
        self.assertEqual(raw,png());element.click.assert_called_once();download.delete.assert_called_once()
        text=copy.deepcopy(self.frozen);text['outputs']=[dict(path='result.txt',purpose='Text download')]
        text['browser']['downloads']=['result.txt'];files=Files(text)
        files.write_download('result.txt',b'Original text',{})
        self.assertEqual((self.ws/'result.txt').read_bytes(),b'Original text')
        with self.assertRaises(UnicodeDecodeError):files.write_download('result.txt',b'\xff\xfe',{})
        self.assertEqual((self.ws/'result.txt').read_bytes(),b'Original text')

    def test_runtime_handoff_preserves_original_image_and_provenance(self):
        factory=FakeFactory();rt=Runtime(self.root/'runtime',factory)
        try:
            rt.create(graph());rt.tick('demo');aid=rt.task('demo','produce')['latest']
            record=factory.sessions[aid];f=record['frozen'];driver=DownloadDriver()
            session=Session(rt.db,f['assignment_id'],f['browser'],driver,Files(f))
            page=session.call('open','browser_open',{'url':'https://example.test/result'})
            session.call('download','browser_download',dict(tab=page['tab'],observation=page['observation'],ref='1',path='map.png',purpose='Download fixture'))
            atomic(Path(f['workspace'])/'.relay/result.json',report(f))
            record['status']={'status':'finished','exit_code':0};rt.tick('demo')
            artifact=rt.output('demo','produce','map.png')
            self.assertEqual(Path(artifact['blob']).read_bytes(),png())
            reviewer=factory.sessions[rt.task('demo','review')['latest']]['frozen']
            info=Files(reviewer).call('file_read',dict(path='candidate/map.png',offset=0,limit=100))
            self.assertEqual(info['sha256'],artifact['sha256'])
            self.assertFalse(info['visual_content_inspected'])
            evidence=next(i for i in reviewer['inputs'] if i['path'].startswith('browser-evidence/'))
            pack=json.loads((Path(reviewer['workspace'])/evidence['path']).read_text())
            self.assertEqual(pack['actions'][-1]['result']['download']['sha256'],artifact['sha256'])
        finally:rt.db.close()

    def test_provider_loops_return_file_identity_without_implicit_pixel_upload(self):
        import base64
        for provider in ('gemini','openai','qwen'):
            with self.subTest(provider=provider):
                ws=self.root/provider;ws.mkdir();(ws/'.relay').mkdir();control=ws/'control';control.mkdir()
                f=copy.deepcopy(self.frozen);f['workspace']=str(ws);f['backend']={'type':provider+'-browser','model':'fixture-model'}
                config=CONFIG if provider=='gemini' else {'api_key':'fixture-only','model':'fixture-model'}
                atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,f['backend'])})
                client=DownloadClient(f,provider)
                with sqlite3.connect(':memory:') as db:
                    result=run(f,control,db,self.root,client=client,config_reader=lambda:(config,f['backend']),driver_context=nullcontext(DownloadDriver()))
                self.assertEqual(result['decision'],'delivered');validate_captures(f,ws)
                self.assertEqual((ws/'map.png').read_bytes(),png())
                self.assertNotIn(base64.b64encode(png()).decode(),json.dumps(client.calls))


if __name__=='__main__':unittest.main()
