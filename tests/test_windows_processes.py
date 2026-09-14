"""Small process fixtures; native tests are never substituted by macOS mocks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from task_relay import host_windows as windows
from task_relay.host import HOST


def eventually(check, seconds=15):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        value=check()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Fixture did not reach the expected state')


class Contracts(unittest.TestCase):
    def test_unported_pipe_transport_rejects_before_launch(self):
        from task_relay.codex_app_server import Client
        from task_relay.host import UnsupportedHost
        with patch.object(HOST,'platform','win32'),patch.object(HOST,'spawn') as spawn:
            with self.assertRaisesRegex(UnsupportedHost,'pipe transport'):
                with Client(command=['never.exe']):pass
            spawn.assert_not_called()

    def test_pre_windows_10_rejected_before_loading_native_api(self):
        with patch.object(windows.sys,'platform','win32'), \
             patch.object(windows.sys,'getwindowsversion',create=True,return_value=Mock(major=6)):
            with self.assertRaisesRegex(OSError,'Windows 10 or newer'):windows.require_native()

    def test_shell_wrappers_and_invalid_arguments_rejected(self):
        for command in ('python -c code', [], ['worker.exe','bad\x00arg'], [b'worker.exe']):
            with self.assertRaises(ValueError):windows.command_line(command)
        for executable in ('worker.cmd','worker.bat','script.py'):
            with patch.object(windows.shutil,'which',return_value=executable):
                with self.assertRaisesRegex(ValueError,'native Windows executable'):
                    windows.command_line([executable])

    def test_environment_does_not_silently_replace_case_collisions(self):
        for env in ({'Path':'one','PATH':'two'}, {'A=B':'value'}, {'A':'bad\x00value'}):
            with self.assertRaises(ValueError):windows.environment_block(env)
        block=windows.environment_block({'Z':'literal $HOME & value','A':'café'})
        self.assertEqual(block[:len('A=café\x00Z=literal $HOME & value\x00\x00')],
                         'A=café\x00Z=literal $HOME & value\x00\x00')

    def test_job_configuration_failure_never_starts_worker(self):
        lib=Mock();lib.CreateJobObjectW.return_value=101
        lib.SetInformationJobObject.side_effect=OSError('job setup denied')
        with patch.object(windows,'require_native'), patch.object(windows,'kernel',return_value=lib), \
             patch.object(windows,'command_line',return_value=(['worker.exe'],'worker.exe','worker.exe')), \
             patch.dict(sys.modules,{'msvcrt':Mock()}):
            with self.assertRaisesRegex(OSError,'job setup denied'):windows.spawn(['worker.exe'])
        lib.CreateProcessW.assert_not_called();lib.CloseHandle.assert_called_once_with(101)

    def test_pipe_close_failure_still_releases_owned_job(self):
        lib=Mock();lib.CloseHandle.return_value=1
        info=windows.PROCESS_INFORMATION();info.process=10;info.pid=20
        stream=Mock();stream.close.side_effect=OSError('broken pipe')
        process=windows.Process(lib,info,11,[],[stream,None,None])
        with self.assertRaisesRegex(OSError,'broken pipe'):process.close()
        self.assertEqual([call.args[0] for call in lib.CloseHandle.call_args_list],[11,10])

    def test_reused_pid_or_missing_identity_is_not_reconnected(self):
        expected={'pid':123,'created':10,'executable':'python.exe'}
        with patch.object(windows,'identity',return_value={**expected,'created':11}) as probe:
            self.assertFalse(windows.matches(123,None));probe.assert_not_called()
            self.assertFalse(windows.matches(123,expected))
        with patch.object(windows,'identity',side_effect=OSError('query denied')):
            with self.assertRaises(OSError):windows.matches(123,expected)

    def test_changed_frozen_native_support_prevents_dispatch(self):
        from orchestrator.workers import atomic, prepare_supervisor, supervisor_support
        from task_relay import host
        with tempfile.TemporaryDirectory() as folder:
            control=Path(folder);marker=control/'should-not-exist'
            # Copy the real adapter; no Win32 API is invoked by this integrity test.
            with patch.object(HOST,'platform','win32'),patch.object(HOST,'require_processes'):
                digest=prepare_supervisor(control,{})
                support=supervisor_support(control)
                self.assertEqual((control/'host_windows.py').read_bytes(),Path(host.__file__).with_name('host_windows.py').read_bytes())
            atomic(control/'launch.json',{'token':'fixture','host_support_sha256':digest,
                'host_support_files':support,'registered_command':[sys.executable,'-c',
                    'import pathlib,sys;pathlib.Path(sys.argv[1]).touch()',str(marker)]})
            with (control/'host_windows.py').open('a') as stream:stream.write('\n# modified\n')
            result=subprocess.run([sys.executable,'-B',str(control/'supervisor.py'),str(control),'fixture'],
                capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Frozen native host support changed',result.stderr)
            self.assertFalse(marker.exists());self.assertFalse((control/'started.json').exists())


@unittest.skipUnless(sys.platform=='win32','Requires native Windows 10+; not qualified by mocks')
class NativeWindows(unittest.TestCase):
    def test_unicode_arguments_environment_and_pipes(self):
        with tempfile.TemporaryDirectory(prefix='Relay space ') as folder:
            args=['café','two words','quote"literal','trailing\\','& echo untouched','']
            code="import json,os,sys;print(json.dumps([sys.argv[1:],sys.stdin.read(),os.environ['RELAY_FIXTURE'],os.getcwd()]))"
            process=HOST.spawn([sys.executable,'-B','-X','utf8','-c',code,*args],cwd=folder,
                env={**os.environ,'RELAY_FIXTURE':'literal $HOME %PATH%'},
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                process.stdin.write('hello café');process.stdin.close();self.assertEqual(process.wait(15),0)
                result=json.loads(process.stdout.read())
                self.assertEqual(result[:3],[args,'hello café','literal $HOME %PATH%'])
                self.assertEqual(Path(result[3]).resolve(),Path(folder).resolve())
            finally:process.close()

    def descendants(self, parent_exits):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);heartbeat=root/'heartbeat'
            child="import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile True:\n p.write_text(str(time.monotonic()))\n time.sleep(.03)"
            parent="import subprocess,sys,time;subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],sys.argv[2]]);time.sleep(float(sys.argv[3]))"
            process=HOST.spawn([sys.executable,'-B','-c',parent,child,str(heartbeat),'0' if parent_exits else '30'])
            try:
                eventually(heartbeat.exists)
                if parent_exits:process.wait(15)
                HOST.stop_tree(process)
                time.sleep(.2);last=heartbeat.read_bytes();time.sleep(.25)
                self.assertEqual(heartbeat.read_bytes(),last,'Descendant survived job cancellation')
            finally:process.terminate();process.wait(15);process.close()

    def test_cancellation_stops_entire_tree(self):self.descendants(False)
    def test_cancellation_after_parent_exit_stops_descendants(self):self.descendants(True)

    def test_owner_crash_closes_job_without_inherited_job_handle(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);heartbeat=root/'heartbeat'
            owner=root/'owner.py'
            owner.write_text('''import os,sys,time
from pathlib import Path
from task_relay.host import HOST
child="import pathlib,sys,time\\np=pathlib.Path(sys.argv[1])\\nwhile True:\\n p.write_text(str(time.monotonic()))\\n time.sleep(.03)"
proc=HOST.spawn([sys.executable,'-B','-c',child,sys.argv[1]])
until=time.monotonic()+10
while not Path(sys.argv[1]).exists() and time.monotonic()<until:time.sleep(.02)
os._exit(17)
''',encoding='utf-8')
            env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
            process=subprocess.Popen([sys.executable,'-B',str(owner),str(heartbeat)],env=env)
            try:
                self.assertEqual(process.wait(15),17);self.assertTrue(heartbeat.exists())
                time.sleep(.2);last=heartbeat.read_bytes();time.sleep(.25)
                self.assertEqual(heartbeat.read_bytes(),last)
            finally:
                if process.poll() is None:process.kill();process.wait(15)

    def test_cross_process_lock_is_released_when_owner_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);lock=root/'lock';ready=root/'ready'
            owner="import sys,time;from pathlib import Path;from task_relay.host import HOST;f=open(sys.argv[1],'w+b');HOST.lock(f);Path(sys.argv[2]).touch();time.sleep(30)"
            contender="import sys;from task_relay.host import HOST\nf=open(sys.argv[1],'r+b')\ntry:HOST.lock(f)\nexcept BlockingIOError:sys.exit(23)"
            process=subprocess.Popen([sys.executable,'-B','-c',owner,str(lock),str(ready)])
            try:
                eventually(ready.exists)
                self.assertEqual(subprocess.run([sys.executable,'-B','-c',contender,str(lock)],timeout=15).returncode,23)
                process.kill();process.wait(15)
                self.assertEqual(subprocess.run([sys.executable,'-B','-c',contender,str(lock)],timeout=15).returncode,0)
            finally:
                if process.poll() is None:process.kill();process.wait(15)

    def test_supervisor_survives_scheduler_exit_and_reconnects_without_replay(self):
        from orchestrator.workers import CodexFactory, atomic
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);control=root/'control';control.mkdir();marker=root/'runs'
            scheduler='''import os,sys,time
from pathlib import Path
from orchestrator.workers import CodexFactory,atomic,prepare_supervisor,supervisor_support
control=Path(sys.argv[1]);marker=sys.argv[2]
digest=prepare_supervisor(control,{})
atomic(control/'launch.json',{'token':'fixture','created':time.time(),'host_support_sha256':digest,
 'host_support_files':supervisor_support(control),'limits':{'seconds':15,'tool_calls':1},
 'registered_command':[sys.executable,'-B','-c',"import pathlib,sys,time;p=pathlib.Path(sys.argv[1]);p.open('a').write('started\\\\n');time.sleep(30)",marker]})
(control/'prompt.txt').write_text('fixture')
CodexFactory().submit({'control':str(control),'id':'fixture'})
os._exit(0)
'''
            parent=subprocess.Popen([sys.executable,'-B','-c',scheduler,str(control),str(marker)])
            session={'control':str(control),'id':'fixture'};factory=CodexFactory();started=None
            try:
                self.assertEqual(parent.wait(15),0)
                eventually(marker.exists)
                started=json.loads((control/'started.json').read_text())
                self.assertEqual(factory.inspect(session)['status'],'running')
                changed=json.loads(json.dumps(started));changed['supervisor_identity']['created']+=1
                atomic(control/'started.json',changed)
                self.assertEqual(factory.inspect(session)['status'],'uncertain')
                atomic(control/'started.json',started)
                factory.cancel(session)
                eventually((control/'done.json').exists)
                result=factory.inspect(session)
                self.assertEqual((result['status'],result['reason']),('finished','cancelled'))
                self.assertEqual(marker.read_text().count('started'),1)
                self.assertEqual(factory.inspect(session)['status'],'finished')
            finally:
                atomic(control/'cancel.json',{'token':'fixture'})
                if parent.poll() is None:parent.kill();parent.wait(15)
                if started:
                    eventually(lambda:not windows.matches(started['supervisor_pid'],started['supervisor_identity']),20)


if __name__=='__main__':unittest.main()
