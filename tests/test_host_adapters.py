"""Host boundaries, real local process cancellation and declared text grants."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from task_relay import credentials, host, providers, gemini
from task_relay.filesystem import Grant, Filesystem, AccessDenied


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.files=Filesystem(host.Host('darwin'))

    def tearDown(self):self.temp.cleanup()

    def test_read_grant_and_exact_edit_paths(self):
        (self.root/'input.txt').write_text('original')
        read=Grant(self.root,'selected task',frozenset({'input.txt'}))
        self.assertEqual(self.files.read(read,'input.txt',50),b'original')
        for name in ('input.txt','other.txt','../escape.txt'):
            with self.assertRaises(AccessDenied):self.files.write(read,name,b'changed')
        edit=Grant(self.root,'assignment-1',frozenset({'input.txt'}),frozenset({'out/result.txt'}))
        self.files.write(edit,'out/result.txt',b'candidate')
        self.assertEqual((self.root/'out/result.txt').read_bytes(),b'candidate')
        with self.assertRaises(AccessDenied):self.files.write(edit,'input.txt',b'changed')
        self.assertEqual((self.root/'input.txt').read_text(),'original')

    def test_links_and_protected_data_are_not_grants(self):
        (self.root/'private').mkdir();(self.root/'private/key.txt').write_text('secret fixture')
        (self.root/'link').symlink_to(self.root/'private',target_is_directory=True)
        os.link(self.root/'private/key.txt',self.root/'hard.txt')
        grant=Grant(self.root,'project',protected=(self.root/'private',))
        for name in ('private/key.txt','link/key.txt','hard.txt'):
            with self.assertRaises((OSError,ValueError)):self.files.read(grant,name,100)
        write=Grant(self.root,'assignment',writes=frozenset({'link/new.txt'}))
        with self.assertRaises(OSError):self.files.write(write,'link/new.txt',b'escape')
        self.assertFalse((self.root/'private/new.txt').exists())

    def test_directory_swap_does_not_follow_replacement_link(self):
        (self.root/'child').mkdir();(self.root/'child/in.txt').write_text('permitted')
        outside=self.root/'outside';outside.mkdir();(outside/'in.txt').write_text('private')
        grant=Grant(self.root/'child','selected project')
        original=os.open;swapped=False
        def swap(name,*args,**kwargs):
            nonlocal swapped
            if name=='child' and not swapped:
                swapped=True;(self.root/'child').rename(self.root/'retained')
                (self.root/'child').symlink_to(outside,target_is_directory=True)
            return original(name,*args,**kwargs)
        with patch('os.open',side_effect=swap):
            with self.assertRaises(OSError):self.files.read(grant,'in.txt',100)
        self.assertTrue(swapped)

    def test_unsupported_host_fails_before_operations(self):
        unsupported=host.Host('win32')
        with patch('subprocess.Popen') as spawn,patch('subprocess.run') as run:
            with self.assertRaises(host.UnsupportedHost):unsupported.spawn(['never'])
            with self.assertRaises(host.UnsupportedHost):unsupported.telegram_service('install')
            with self.assertRaises(host.UnsupportedHost):Filesystem(unsupported).read(Grant(self.root,'task'),'input.txt',20)
            spawn.assert_not_called();run.assert_not_called()

    def test_worker_discovery_does_not_fallback_from_invalid_override(self):
        with patch.dict(os.environ,{'TASK_RELAY_CODEX':str(self.root/'missing')},clear=False),patch('shutil.which',return_value=sys.executable):
            with self.assertRaises(host.UnsupportedHost):host.Host().codex()
        with patch.dict(os.environ,{},clear=True),patch('shutil.which',return_value=sys.executable):
            self.assertEqual(host.Host('linux').codex(),sys.executable)

    def test_core_imports_without_messages_or_unix_lock_module(self):
        code='''import builtins
old=builtins.__import__
def guard(name,*a,**k):
 if name=='fcntl':raise ImportError('fixture: native locking unavailable')
 if 'messages' in name or name.endswith('host_macos'):raise AssertionError(name)
 return old(name,*a,**k)
builtins.__import__=guard
import task_relay.bridge, task_relay.cli, orchestrator.runtime
print('core imports without native integrations')
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_exclusive_lock_is_released_after_owner_closes(self):
        path=self.root/'lock'
        with path.open('w') as first:
            host.HOST.lock(first)
            with path.open('w') as second:
                with self.assertRaises(BlockingIOError):host.HOST.lock(second)
        with path.open('w') as third:host.HOST.lock(third)

    def test_cancel_reaches_child_and_grandchild(self):
        ready=self.root/'ready';done=self.root/'done'
        grandchild="import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,lambda *a:(pathlib.Path(sys.argv[2]).write_text('stopped'),sys.exit(0))); pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
        parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]); time.sleep(30)"
        process=host.HOST.spawn([sys.executable,'-c',parent,grandchild,str(ready),str(done)])
        try:
            end=time.monotonic()+5
            while not ready.exists() and time.monotonic()<end:time.sleep(.02)
            self.assertTrue(ready.exists());host.HOST.stop_tree(process)
            end=time.monotonic()+5
            while not done.exists() and time.monotonic()<end:time.sleep(.02)
            self.assertEqual(done.read_text(),'stopped');self.assertIsNotNone(process.poll())
        finally:
            host.HOST.signal_tree(process,force=True);process.wait(timeout=5)

    def test_secret_reference_failure_never_uses_inline_fallback(self):
        path=self.root/'gemini.json'
        credentials.save(path,{'api_key':'old-secret','api_key_ref':{'source':'environment','name':'RELAY_TEST_KEY'},'model':'fixture'})
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(credentials.CredentialError):credentials.configuration(path)
            self.assertNotIn('old-secret',json.dumps(credentials.status(path)))
        with patch.dict(os.environ,{'RELAY_TEST_KEY':'resolved-secret'},clear=True):
            self.assertEqual(credentials.configuration(path)['api_key'],'resolved-secret')
            self.assertNotIn('resolved-secret',json.dumps(credentials.status(path)))
            self.assertNotIn('old-secret',json.dumps(credentials.status(path)))

    def test_private_reference_permissions_links_and_no_secret_errors(self):
        secret=self.root/'secret.json';credentials.save(secret,{'key':'hidden fixture'})
        ref={'source':'private-file','path':str(secret),'field':'key'}
        self.assertEqual(credentials.resolve(ref),'hidden fixture')
        secret.chmod(0o644)
        with self.assertRaises(credentials.CredentialError):credentials.resolve(ref)
        secret.chmod(0o600);link=self.root/'alias.json';link.symlink_to(secret)
        with self.assertRaises(credentials.CredentialError):credentials.resolve({**ref,'path':str(link)})
        broken=self.root/'broken.json';broken.write_text('hidden fixture')
        self.assertNotIn('hidden fixture',json.dumps(credentials.status(broken)))

    def test_secret_write_cannot_create_directories_through_link(self):
        outside=self.root/'outside';outside.mkdir();(self.root/'alias').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):credentials.save(self.root/'alias/new/key.json',{'api_key':'fixture'})
        self.assertFalse((outside/'new').exists())

    def test_keychain_locked_and_unsupported_are_explicit(self):
        ref={'source':'macos-keychain','service':'relay.fixture','account':'fixture'}
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,stdout='',stderr='hidden diagnostic')):
            with self.assertRaisesRegex(credentials.CredentialError,'locked or denied'):credentials.resolve(ref,host=host.Host('darwin'))
        with patch('subprocess.run') as run:
            with self.assertRaises(credentials.CredentialError):credentials.resolve(ref,host=host.Host('win32'))
            run.assert_not_called()

    def test_connection_refresh_preserves_reference_and_configure_replaces_it(self):
        path=self.root/'gemini.json';ref={'source':'environment','name':'RELAY_TEST_KEY'}
        credentials.save(path,{'api_key_ref':ref})
        with patch.object(gemini,'DATA',self.root):
            providers.configure_gemini('fixture',names=['fixture'],preserve_reference=True)
            saved=credentials.private_json(path)
            self.assertEqual(saved['api_key_ref'],ref);self.assertNotIn('api_key',saved)
            providers.configure_gemini('new fixture',names=['fixture'])
            saved=credentials.private_json(path)
            self.assertNotIn('api_key_ref',saved);self.assertEqual(saved['api_key'],'new fixture')

    def test_changed_host_support_rejects_frozen_assignment(self):
        binding=host.support_hashes();host.verify_support({'host_support':binding})
        binding['filesystem.py']='changed'
        with self.assertRaisesRegex(ValueError,'changed after assignment'):host.verify_support({'host_support':binding})
