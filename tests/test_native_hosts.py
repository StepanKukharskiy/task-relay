"""Native O12 boundaries and small process/service failure fixtures; no transport."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from task_relay.host import HOST, UnsupportedHost


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'Native POSIX process tests')
class ProcessTrees(unittest.TestCase):
    def check_descendant(self, parent_exits):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); ready = root/'ready'; heartbeat = root/'heartbeat'
            grandchild = '''import pathlib,signal,sys,time
signal.signal(signal.SIGTERM,signal.SIG_IGN)
pathlib.Path(sys.argv[1]).write_text('ready')
while True:
 pathlib.Path(sys.argv[2]).write_text(str(time.monotonic()))
 time.sleep(.02)
'''
            parent = '''import pathlib,subprocess,sys,time
subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]])
while not pathlib.Path(sys.argv[2]).exists():time.sleep(.01)
if sys.argv[4]=='exit':sys.exit(0)
time.sleep(30)
'''
            process = HOST.spawn([sys.executable, '-c', parent, grandchild, str(ready), str(heartbeat),
                                  'exit' if parent_exits else 'wait'])
            try:
                until = time.monotonic()+5
                while not heartbeat.exists() and time.monotonic()<until:time.sleep(.02)
                self.assertTrue(heartbeat.exists())
                if parent_exits:process.wait(timeout=5)
                HOST.stop_tree(process, timeout=.25)
                time.sleep(.1); last = heartbeat.read_bytes(); time.sleep(.15)
                self.assertEqual(heartbeat.read_bytes(), last, 'Descendant survived cancellation')
                self.assertIsNotNone(process.poll())
            finally:
                HOST.signal_tree(process, force=True); process.wait(timeout=5)

    def test_cancellation_after_parent_already_exited(self):self.check_descendant(True)
    def test_forces_descendant_which_ignores_termination(self):self.check_descendant(False)


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'Service file tests use POSIX grants')
class LinuxServices(unittest.TestCase):
    def setUp(self):
        from task_relay import host_linux
        from task_relay.relay_paths import Paths
        self.adapter = host_linux
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.unit = self.root/'config/systemd/user'/host_linux.UNIT
        self.paths = Paths(self.root/'install', self.root/'data', self.root/'projects', self.root/'generated')
        self.calls = []; self.fail_restart = 0; self.active = False; self.enabled = False
        self.patches = [patch.object(host_linux, 'manager', return_value='fixture-systemctl'),
                        patch.object(host_linux, 'unit_path', return_value=self.unit),
                        patch.object(host_linux, 'command', side_effect=self.command)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def command(self, executable, *args):
        self.calls.append(args); code = 0; out = b''
        if args[0] == 'show':out = b'not-found\n'
        if args[0] == 'is-active':code = 0 if self.active else 3
        if args[0] == 'is-enabled':code = 0 if self.enabled else 1
        if args[0] == 'enable':self.enabled = True
        if args[0] == 'disable':self.enabled = False
        if args[0] == 'stop':self.active = False
        if args[0] == 'restart':
            if self.fail_restart:self.fail_restart -= 1;code = 1
            else:self.active = True
        return subprocess.CompletedProcess(args, code, stdout=out, stderr=b'')
    def install(self):
        self.adapter.install(self.paths.install, self.paths.data, self.paths, lambda: {'token':'fixture'}, ValueError)
    def test_missing_user_manager_has_no_install_effect(self):
        with patch.object(self.adapter, 'manager', side_effect=UnsupportedHost('No user manager')):
            with self.assertRaises(UnsupportedHost):self.install()
        self.assertFalse(self.unit.exists());self.assertEqual(self.calls, [])
    def test_failed_first_activation_removes_unit_and_preserves_data(self):
        self.paths.data.mkdir(); marker=self.paths.data/'receipt.txt';marker.write_text('preserved')
        self.fail_restart=1
        with self.assertRaisesRegex(ValueError, 'prior state restored'):self.install()
        self.assertFalse(self.unit.exists());self.assertFalse(self.enabled);self.assertFalse(self.active)
        self.assertEqual(marker.read_text(),'preserved')
    def test_reload_failure_restores_existing_unit_and_active_state(self):
        self.install();prior=self.unit.read_bytes();self.fail_restart=1
        with self.assertRaisesRegex(ValueError,'prior state restored'):self.install()
        self.assertEqual(self.unit.read_bytes(),prior);self.assertTrue(self.enabled);self.assertTrue(self.active)
    def test_changed_paths_or_edited_unit_are_preserved(self):
        from dataclasses import replace
        self.install();prior=self.unit.read_bytes();self.calls.clear()
        self.paths=replace(self.paths,data=self.root/'other')
        with self.assertRaisesRegex(ValueError,'preserved'):self.install()
        self.assertEqual(self.unit.read_bytes(),prior);self.assertEqual(self.calls,[])
        self.unit.write_bytes(prior+b'# user edit\n');self.calls.clear()
        with self.assertRaisesRegex(ValueError,'preserved'):
            self.adapter.uninstall(self.paths.install,ValueError)
        self.assertEqual(self.calls,[]);self.assertEqual(self.unit.read_bytes(),prior+b'# user edit\n')
    def test_unit_arguments_keep_literal_spaces_dollars_and_specifiers(self):
        raw=self.adapter.definition(Path('/opt/Relay $HOME %n'),self.paths,python='/opt/Python $HOME %n/python')
        body=raw.decode().split('\n',1)[1]
        self.assertIn('ExecStart=:"/opt/Python $HOME %%n/python" -m task_relay telegram run',body)
        self.assertIn('KillMode=process',body)
        for value in ('/bad\npath','/bad\x00path'):
            with self.assertRaises(ValueError):self.adapter.quote(value)


@unittest.skipUnless(sys.platform=='win32', 'Native Windows boundary evidence only')
class WindowsBoundaries(unittest.TestCase):
    def test_unavailable_mechanisms_fail_before_side_effects(self):
        from task_relay.filesystem import FILES, Grant
        from task_relay import credentials
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); target=root/'child-started'
            with self.assertRaises(UnsupportedHost):FILES.write(Grant(root,'fixture',writes=frozenset({'out.txt'})),'out.txt',b'fixture')
            with self.assertRaises(UnsupportedHost):HOST.telegram_service('install')
            self.assertFalse(target.exists());self.assertFalse((root/'out.txt').exists())
            # Direct environment references work; configuration/file ACL support remains open.
            self.assertEqual(credentials.resolve({'source':'environment','name':'FIXTURE'},environ={'FIXTURE':'text fixture'}),'text fixture')


if __name__=='__main__':unittest.main()
