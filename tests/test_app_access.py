"""App choice and code default regressions. Fixtures never launch an app/model."""
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from task_relay import app_access as access, host_apps, code_runtime, native_code_host
from task_relay.host import Host, UnsupportedHost
from orchestrator.contracts import digest


class Tests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        for target,value in ((access,'path'),(code_runtime,'path')):
            p=patch.object(target,value,return_value=self.root/(target.__name__.split('.')[-1]+'.json'))
            p.start();self.addCleanup(p.stop)
        for name in ('APPLICATIONS','RHINO_APPLICATIONS'):
            p=patch.object(host_apps,name,self.root);p.start();self.addCleanup(p.stop)

    def app(self,name,version,binary):
        root=self.root/(name+'.app')/'Contents'; (root/'MacOS').mkdir(parents=True)
        executable=root/'MacOS'/binary; executable.write_text('fixture');executable.chmod(0o700)
        (root/'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':version}))
        return executable

    def choice(self,family,enabled,executable=None):
        return access.update({'id':access.key(family,executable),'enabled':enabled})

    def test_both_versions_remain_visible_and_explicit_version_does_not_fallback(self):
        r7=self.app('Rhino 7','7.32','Rhinoceros');r8=self.app('Rhino 8','8.35','Rhinoceros')
        with patch('sys.platform','darwin'),patch.dict(os.environ,{},clear=True),patch('subprocess.run',side_effect=AssertionError('No launch')):
            self.choice('rhino',False,r8)
            rows=[r for r in access.snapshot()['apps'] if r['family']=='rhino']
            self.assertEqual({r['version']:r['enabled'] for r in rows},{'7.32':True,'8.35':False})
            self.assertEqual(host_apps.rhino({})['executable'],str(r7))
            self.assertFalse(host_apps.rhino({'TASK_RELAY_RHINO_VERSION':'8'})['available'])
            self.choice('rhino',False)
            self.assertFalse(host_apps.rhino({})['available'])
            self.choice('rhino',True)
            self.assertFalse(access.enabled('rhino',r8))
            self.assertTrue(access.enabled('rhino',r7))

    def test_blender_versions_deduplicate_and_disabled_override_never_switches(self):
        first=self.app('Blender','4.5','Blender');other=self.app('Blender 4.3','4.3','Blender')
        with patch('sys.platform','darwin'),patch.dict(os.environ,{},clear=True),patch('shutil.which',return_value=str(first)):
            self.choice('blender',False,first)
            rows=[r for r in access.snapshot()['apps'] if r['family']=='blender']
            self.assertEqual(len(rows),2)
            self.assertEqual(host_apps.blender()['executable'],str(other))
            self.assertFalse(host_apps.blender({'TASK_RELAY_BLENDER':str(first)})['available'])
            self.choice('blender',False)
            from orchestrator import execution
            self.assertFalse(next(r for r in execution.catalog() if r['id']=='blender.startup')['available'])

    def test_codex_choice_blocks_factory_and_desktop_before_submission(self):
        from task_relay.bridge import Desktop
        from task_relay.codex_app_server import Client
        from orchestrator.executors import available
        self.choice('codex',False)
        with self.assertRaises(UnsupportedHost):Host().codex()
        with self.assertRaisesRegex(ValueError,'off'):available({'type':'codex-cli','model':'fixture','reasoning':'low'})
        desktop=Desktop()
        with patch.object(desktop,'request') as send:
            with self.assertRaisesRegex(ValueError,'off'):desktop.start('task','exact request','owner')
            send.assert_not_called()

    def test_claude_group_and_exact_executor_are_enforced(self):
        from task_relay import backends
        exe=self.root/'claude';exe.write_text('fixture');exe.chmod(0o700)
        with patch.object(host_apps,'claude_candidates',return_value=[exe]):
            self.choice('claude',False,exe)
            with self.assertRaisesRegex(ValueError,'off'):host_apps.claude_cli()
            self.assertIsNone(backends.claude_config())

    def test_windows_discovery_does_not_claim_rhino_execution(self):
        exe=self.root/'Rhino 8/System/Rhino.exe';exe.parent.mkdir(parents=True);exe.write_text('fixture');exe.chmod(0o700)
        rows=host_apps.installed({'PROGRAMFILES':str(self.root)},'win32',lambda _:None)
        row=next(r for r in rows if r['family']=='rhino')
        self.assertFalse(row['supported']);self.assertEqual(row['executable'],str(exe))

    def test_unknown_settings_or_malformed_policy_cannot_enable_apps(self):
        for value in ({'id':'shell','enabled':True},{'id':'rhino','enabled':1},{'id':'rhino','enabled':True,'command':'run'}):
            with self.assertRaises(ValueError):access.update(value)
        access.path().write_text('{invalid')
        self.assertFalse(access.enabled('rhino'))
        with self.assertRaises(ValueError):access.require('rhino')

    def runtime(self):
        runtime={'adapter':'fixture','python':'fixture'}
        p=patch.object(native_code_host,'identity',return_value=runtime);p.start();self.addCleanup(p.stop)
        return runtime

    def successful_probe(self,runtime,folder,*args):
        output=folder/'outputs';output.mkdir()
        (output/'tools.json').write_text(json.dumps({'isolation':{'outside_read_denied':True,'network_denied':True,'fork_denied':True},'tools':{}}))
        return {'returncode':0}

    def test_default_on_is_read_only_until_first_use_and_qualifies_once(self):
        self.runtime()
        with patch.object(native_code_host,'run',side_effect=self.successful_probe) as probe:
            self.assertTrue(code_runtime.status()['enabled']);self.assertFalse(code_runtime.status()['ready'])
            self.assertFalse(code_runtime.path().exists());probe.assert_not_called()
            first=code_runtime.available();second=code_runtime.available(first['id'])
            self.assertEqual(first,second);self.assertEqual(probe.call_count,1)

    def test_explicit_off_before_first_use_is_persistent(self):
        self.runtime();code_runtime.configure(False)
        with patch.object(native_code_host,'run') as probe:
            self.assertFalse(code_runtime.status()['enabled'])
            with self.assertRaisesRegex(ValueError,'Enable'):code_runtime.available()
            probe.assert_not_called()

    def test_failed_automatic_probe_stays_off_without_retry(self):
        self.runtime()
        with patch.object(native_code_host,'run',return_value={'returncode':1}) as probe:
            with self.assertRaisesRegex(ValueError,'failed'):code_runtime.available()
            with self.assertRaisesRegex(ValueError,'Enable'):code_runtime.available()
            self.assertEqual(probe.call_count,1);self.assertFalse(code_runtime.status()['enabled'])

    def test_missing_receipt_cannot_reapprove_frozen_runtime(self):
        runtime=self.runtime()
        with patch.object(native_code_host,'run') as probe:
            with self.assertRaisesRegex(ValueError,'missing'):code_runtime.available(digest(runtime))
            probe.assert_not_called()


if __name__=='__main__':unittest.main()
