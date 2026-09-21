"""Persistent Rhino sessions preserve documents and cannot replay uncertain code."""
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock,patch
from task_relay import rhino_host as host
from orchestrator import rhino_worker as worker


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.temp=patch('tempfile.gettempdir',return_value=str(self.root));self.temp.start();self.addCleanup(self.temp.stop)
        self.request={'token':'fixture','mode':'startup','rhino_major':8}
        self.path=self.root/'request.json';self.path.write_text(json.dumps(self.request))
        self.connection={'pid':123,'pipe':'rhinocode_remotepipe_123','cli':'/fixture/rhinocode'}

    def run_shared(self):return host.run_shared(self.connection,self.root/'launch.py',self.path,self.request,2)

    def test_connection_requires_exact_process_and_single_session(self):
        app=self.root/'Rhino 8.app/Contents';exe=app/'MacOS/Rhinoceros';cli=app/'Resources/bin/rhinocode'
        cli.parent.mkdir(parents=True);cli.write_text('fixture')
        entry={'processId':123,'processVersion':'8.35','pipeId':'rhinocode_remotepipe_123'}
        with patch.object(host.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps([entry]),'')):
            self.assertEqual(host.script_connection(exe,[123],'darwin')['pid'],123)
            for existing in ([456],[123,456]):
                with self.assertRaisesRegex(ValueError,'one connected'):host.script_connection(exe,existing,'darwin')

    def test_slow_discovery_can_connect_without_script_submission(self):
        app=self.root/'Rhino 8.app/Contents';exe=app/'MacOS/Rhinoceros';cli=app/'Resources/bin/rhinocode'
        cli.parent.mkdir(parents=True);cli.write_text('fixture')
        entry={'processId':123,'processVersion':'8.35','pipeId':'rhinocode_remotepipe_123'}
        def slow_reply(argv,**kwargs):
            if kwargs['timeout']<8:raise subprocess.TimeoutExpired(argv,kwargs['timeout'])
            return subprocess.CompletedProcess(argv,0,json.dumps([entry]),'')
        with patch.object(host.subprocess,'run',side_effect=slow_reply) as run:
            self.assertEqual(host.script_connection(exe,[123],'darwin')['pid'],123)
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args[0],[str(cli.resolve()),'list','--json'])

    def test_discovery_failures_keep_the_actual_reason_and_never_retry(self):
        app=self.root/'Rhino 8.app/Contents';exe=app/'MacOS/Rhinoceros';cli=app/'Resources/bin/rhinocode'
        cli.parent.mkdir(parents=True);cli.write_text('fixture')
        for error,reason in [(subprocess.TimeoutExpired('list',20),'did not finish'),
                             (subprocess.CalledProcessError(7,'list'),'exit 7'),
                             (PermissionError('denied'),'PermissionError')]:
            with self.subTest(reason=reason),patch.object(host.subprocess,'run',side_effect=error) as run:
                with self.assertRaisesRegex(ValueError,reason) as caught:host.script_connection(exe,[123],'darwin')
                self.assertNotIn('run StartScriptServer',str(caught.exception))
                run.assert_called_once()
        for output in ('not json','{}','null'):
            with patch.object(host.subprocess,'run',return_value=subprocess.CompletedProcess([],0,output,'')):
                with self.assertRaisesRegex(ValueError,'unreadable connection list'):host.script_connection(exe,[123],'darwin')
        with patch.object(host.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'[]','')):
            with self.assertRaisesRegex(ValueError,'run StartScriptServer'):host.script_connection(exe,[123],'darwin')

    def test_timeout_stops_client_only_and_blocks_another_submission(self):
        with patch.object(host.subprocess,'Popen') as spawn:
            client=spawn.return_value;client.wait.return_value=0;client.poll.return_value=None;client.returncode=-9
            client.kill.side_effect=lambda:setattr(client.poll,'return_value',-9)
            result=self.run_shared()
            self.assertTrue(result['timeout']);self.assertFalse(result['passed']);self.assertFalse(result['launched'])
            client.kill.assert_called_once()
            self.assertEqual(spawn.call_args.args[0][0],'/fixture/rhinocode')
            with self.assertRaisesRegex(ValueError,'earlier Rhino script'):self.run_shared()
            spawn.assert_called_once()

    def test_wrong_receipt_cannot_unlock_session(self):
        with patch.object(host.subprocess,'Popen') as spawn:
            client=spawn.return_value;client.wait.return_value=0;client.poll.return_value=0;client.returncode=0
            self.path.with_suffix('.result.json').write_text(json.dumps(dict(self.request,pid=999,passed=True)))
            result=self.run_shared();self.assertFalse(result['passed'])
            with self.assertRaisesRegex(ValueError,'no completion receipt'):self.run_shared()
            spawn.assert_called_once()

    def test_matching_terminal_receipt_releases_session_without_exiting_rhino(self):
        with patch.object(host.subprocess,'Popen') as spawn:
            client=spawn.return_value;client.poll.return_value=0;client.returncode=0
            def done(**kwargs):self.path.with_suffix('.result.json').write_text(json.dumps(dict(self.request,pid=123,passed=True)))
            with patch.object(host.time,'sleep',side_effect=lambda _:done()):
                self.assertTrue(self.run_shared()['passed'])
            client.kill.assert_not_called()
            self.assertFalse((self.root/('task-relay-rhino-'+str(host.os.getuid()))/'123.json').exists())

    def test_shared_worker_never_exits_on_success_or_failure(self):
        system=types.SimpleNamespace(Diagnostics=types.SimpleNamespace(Process=types.SimpleNamespace(GetCurrentProcess=lambda:types.SimpleNamespace(Id=123))))
        self.path.with_suffix('.owner.json').write_text(json.dumps({'pid':123,'token':'fixture','shared':True}))
        for error in (None,ValueError('model failure')):
            self.path.with_suffix('.started.json').unlink(missing_ok=True);self.path.with_suffix('.result.json').unlink(missing_ok=True)
            exit_process=Mock()
            with patch.dict('sys.modules',{'System':system}),patch.object(worker,'shared_perform',side_effect=error,return_value={}),patch.object(worker,'perform') as owned:
                worker.main(self.path,exit_process)
                exit_process.assert_not_called();owned.assert_not_called()
            receipt=json.loads(self.path.with_suffix('.result.json').read_text())
            self.assertEqual(receipt['passed'],error is None)

    def test_cleanup_restores_user_document_even_if_model_raises(self):
        user=object();context=object();doc=types.SimpleNamespace(Path='/fixture/preview.3dm',Modified=True,RuntimeSerialNumber=55)
        rhino=types.SimpleNamespace(RhinoDoc=types.SimpleNamespace(ActiveDoc=user),RhinoApp=types.SimpleNamespace(RunScript=Mock(return_value=True)))
        sc=types.SimpleNamespace(doc=context)
        def failed(request):
            request['_owned_visible_docs'].append(doc);rhino.RhinoDoc.ActiveDoc=doc;sc.doc=doc
            raise ValueError('model failure')
        with patch.dict('sys.modules',{'Rhino':rhino,'scriptcontext':sc}),patch.object(worker,'perform',side_effect=failed):
            with self.assertRaisesRegex(ValueError,'model failure'):worker.shared_perform(self.request)
        self.assertIs(rhino.RhinoDoc.ActiveDoc,user);self.assertIs(sc.doc,context)
        rhino.RhinoApp.RunScript.assert_called_once_with(55,'_-Close "/fixture/preview.3dm" _Enter',False)

    def test_preview_refuses_reusing_an_existing_document(self):
        rhino=types.SimpleNamespace(RhinoDoc=types.SimpleNamespace(OpenDocuments=lambda:[types.SimpleNamespace(Path='/fixture/model.3dm')],Open=Mock()))
        with patch.dict('sys.modules',{'Rhino':rhino}):
            with self.assertRaisesRegex(ValueError,'already open'):worker.open_visible('/fixture/model.3dm',[])
        rhino.RhinoDoc.Open.assert_not_called()
