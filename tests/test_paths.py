"""Path compatibility, isolated overrides and real child inheritance; no provider calls."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import relay_paths
from scripts.source_inventory import inventory

ROOT=Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.env={k:v for k,v in os.environ.items() if k not in relay_paths.OVERRIDES}
        self.env.update(PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
    def tearDown(self):self.tmp.cleanup()
    def run_python(self,code,extra=None,check=True,cwd=None):
        r=subprocess.run([sys.executable,'-c',code],env={**self.env,**(extra or {})},cwd=cwd or self.root,capture_output=True,text=True,timeout=25)
        if check:self.assertEqual(r.returncode,0,r.stderr+r.stdout)
        return r

    def test_default_bindings_are_identical_outside_install_and_do_not_create_data(self):
        code='''import json
import bridge,gemini,backends,claude_setup,messages_pilot,messages_service
from relay_paths import PATHS
print(json.dumps({'paths':PATHS.describe(),'modules':[str(x.DATA) for x in (bridge,gemini,backends,claude_setup)],'messages':str(messages_service.DATA)}))'''
        outside=json.loads(self.run_python(code).stdout);inside=json.loads(self.run_python(code,cwd=ROOT).stdout)
        self.assertEqual(outside,inside);self.assertEqual(outside['modules'],[str(ROOT/'private')]*4)
        self.assertEqual(outside['paths']['state'],str(ROOT/'private/state.sqlite'))
        self.assertEqual(outside['paths']['workspaces'],str(ROOT/'projects'))
        self.assertEqual(outside['paths']['generated'],str(ROOT/'generated'))
        self.assertEqual(outside['messages'],str(ROOT/'private/messages-pilot'))
        self.assertTrue(Path(outside['paths']['messages_icon']).is_file())

    def test_override_redirects_all_roots_without_creating_them_on_import(self):
        data=self.root/'fresh data';env={'TASK_RELAY_DATA_DIR':str(data)}
        code='''import json
from relay_paths import PATHS
import bridge,gemini,backends,messages_service
print(json.dumps({'paths':PATHS.describe(),'modules':[str(x.DATA) for x in (bridge,gemini,backends)],'native':messages_service.runtime_configuration(),'service_env':messages_service.definition()['EnvironmentVariables']}))'''
        result=json.loads(self.run_python(code,env).stdout)
        self.assertEqual(result['modules'],[str(data)]*3)
        self.assertEqual(result['paths']['workspaces'],str(data.with_name(data.name+'-projects')))
        self.assertEqual(result['paths']['generated'],str(data.with_name(data.name+'-generated')))
        self.assertEqual(result['native']['messages'],str(data/'messages-pilot'))
        self.assertEqual(result['service_env']['TASK_RELAY_DATA_DIR'],str(data))
        self.assertFalse(data.exists())

    def test_invalid_or_overbroad_overrides_fail_without_default_fallback(self):
        for value in ('','relative folder',str(ROOT),str(ROOT.parent)):
            result=self.run_python('import bridge',{'TASK_RELAY_DATA_DIR':value},check=False)
            self.assertNotEqual(result.returncode,0)
        for value in (str(ROOT),str(self.root)):
            result=self.run_python('import bridge',{'TASK_RELAY_DATA_DIR':str(self.root/'data'),'TASK_RELAY_WORKSPACE_DIR':value},check=False)
            self.assertNotEqual(result.returncode,0)

    def test_fresh_cli_and_bridge_share_state_and_worker_reopen_preserves_artifact(self):
        data=self.root/'isolated data';workspace=self.root/'user projects'
        env={'TASK_RELAY_DATA_DIR':str(data),'TASK_RELAY_WORKSPACE_DIR':str(workspace)}
        code='''import json,time
from pathlib import Path
from relay_paths import PATHS
from orchestrator.runtime import Runtime
from orchestrator import execution
from bridge import State
rt=Runtime(PATHS.runtime)
source=PATHS.data/'source.txt';source.write_text('Exact isolated input\\n')
aid=rt.register(source,'Fixture text',path='source.txt')
task=dict(id='bundle',role='procedure',objective='Bundle text',instruction='Preserve exact source',
 execution={'capability':'text.bundle','version':1,'parameters':{}},
 inputs=[dict(artifact=aid,path='source.txt',sha256=rt.artifact(aid)['sha256'],purpose='Fixture',authority='Data only',media_type='text/plain')],
 outputs=[dict(path='bundle.txt',purpose='Fixture bundle',media_type='text/plain')],criteria=execution.REGISTRY['text.bundle']['criteria'])
rt.create(dict(id='path-check',brief='Isolated path test',backend={'type':'codex-cli','model':'fixture','reasoning':'high'},tasks=[task]))
rt.tick('path-check');rt.close();rt=Runtime(PATHS.runtime)
end=time.monotonic()+10
while time.monotonic()<end:
 status=rt.tick('path-check')
 if status['status']=='completed':break
 time.sleep(.05)
assert status['status']=='completed',status
assert len(status['attempts'])==1
artifact=rt.output('path-check','bundle','bundle.txt');assert 'Exact isolated input' in Path(artifact['blob']).read_text()
state=State(PATHS.state)
assert state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0]==1
assert not (PATHS.runtime/'state.sqlite').exists()
for child in rt.factory.registered.children:child.wait(timeout=5)
print(json.dumps({'state':str(PATHS.state),'artifact':artifact['blob'],'hash':artifact['sha256']}))
state.db.close();rt.close()'''
        result=json.loads(self.run_python(code,env).stdout)
        self.assertEqual(result['state'],str(data/'state.sqlite'))
        self.assertTrue(Path(result['artifact']).is_relative_to(data))
        # Invoke the actual CLI from a different directory against the same store.
        cli=subprocess.run([sys.executable,'-m','orchestrator','status','path-check'],env={**self.env,**env},cwd=self.root,capture_output=True,text=True,timeout=10)
        self.assertEqual(cli.returncode,0,cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['status'],'completed')

    def test_default_override_workspace_is_readable_without_exposing_credentials(self):
        code="import json\nfrom relay_paths import PATHS\nimport file_tools\nPATHS.data.mkdir(parents=True);PATHS.workspaces.mkdir(parents=True)\n(PATHS.data/'gemini.json').write_text('private fixture')\n(PATHS.workspaces/'source.txt').write_text('Readable project input')\nresult=file_tools.execute(PATHS.workspaces,'file_read',json.dumps({'path':'source.txt','offset':0,'limit':100}),(PATHS.data,))\nassert 'Readable project input' in str(result),result\ndenied=file_tools.execute(PATHS.workspaces,'file_read',json.dumps({'path':str(PATHS.data/'gemini.json'),'offset':0,'limit':100}),(PATHS.data,))\nassert denied['ok'] is False,denied\nprint('project readable; data protected')"
        self.assertIn('data protected',self.run_python(code,{'TASK_RELAY_DATA_DIR':str(self.root/'private-data')}).stdout)

    def test_real_provider_child_reads_override_configuration_and_store(self):
        env={'TASK_RELAY_DATA_DIR':str(self.root/'override')}
        code='''import json,subprocess,sys
from relay_paths import PATHS
from bridge import State
import gemini
state=State(PATHS.state)
from task_relay.credentials import save
save(PATHS.data/'gemini.json',{'api_key':'fixture-only','models':{'text':'fixture'}})
with state.db:state.put('path-fixture','retained')
child=subprocess.run([sys.executable,'-c',"import gemini; from relay_paths import PATHS; from bridge import State; s=State(PATHS.state); assert gemini.read_config()['api_key']=='fixture-only'; assert s.get('path-fixture')=='retained'; s.db.close(); print('child-paths-ok')"],capture_output=True,text=True)
assert child.returncode==0,child.stderr
print(child.stdout.strip());state.db.close()'''
        self.assertEqual(self.run_python(code,env).stdout.strip(),'child-paths-ok')

    def test_installer_persists_paths_and_refuses_switching_existing_data(self):
        import bridge
        selected=relay_paths.resolve({'TASK_RELAY_DATA_DIR':str(self.root/'data')})
        home=self.root/'home';plist=home/'Library/LaunchAgents/com.personal.codex-telegram.plist'
        with patch.object(bridge,'PATHS',selected),patch.object(bridge,'read_config'),patch.object(Path,'home',return_value=home),patch.object(bridge.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            bridge.install();original=plist.read_bytes();spec=plistlib.loads(original)
            self.assertEqual(spec['EnvironmentVariables'],selected.environment())
            bridge.install()
            with patch.object(bridge,'PATHS',relay_paths.resolve({'TASK_RELAY_DATA_DIR':str(self.root/'different')})):
                with self.assertRaisesRegex(bridge.BridgeError,'migration'):bridge.install()
            self.assertEqual(plist.read_bytes(),original)

    def test_failed_service_reload_restores_prior_configuration(self):
        import bridge
        selected=relay_paths.resolve({'TASK_RELAY_DATA_DIR':str(self.root/'data')})
        home=self.root/'home';plist=home/'Library/LaunchAgents/com.personal.codex-telegram.plist'
        plist.parent.mkdir(parents=True)
        old=plistlib.dumps({'WorkingDirectory':str(ROOT),'EnvironmentVariables':{'TASK_RELAY_DATA_DIR':str(selected.data)},'Label':'com.personal.codex-telegram'})
        plist.write_bytes(old)
        responses=[subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],1),subprocess.CompletedProcess([],0)]
        with patch.object(bridge,'PATHS',selected),patch.object(bridge,'read_config'),patch.object(Path,'home',return_value=home),patch.object(bridge.subprocess,'run',side_effect=responses):
            with self.assertRaisesRegex(bridge.BridgeError,'previous service restarted'):bridge.install()
        self.assertEqual(plist.read_bytes(),old)

    def test_explicit_workspace_and_generated_roots_are_inherited(self):
        chosen=relay_paths.resolve({'TASK_RELAY_DATA_DIR':str(self.root/'data'),'TASK_RELAY_WORKSPACE_DIR':str(self.root/'projects'),'TASK_RELAY_GENERATED_DIR':str(self.root/'deliveries')})
        self.assertEqual(relay_paths.resolve(chosen.environment()),chosen)

    def test_inventory_excludes_operational_data_and_retains_active_assets(self):
        value=inventory();files={f['path']:f for f in value['files']}
        self.assertIn('relay_paths.py',files);self.assertIn('tests/test_paths.py',files)
        self.assertIn('output/logos/scribble-logo-circular-v3.png',files)
        self.assertFalse(any(p.startswith(('private/','outputs/','generated/','projects/','Messages Relay.app/')) for p in files))
        self.assertFalse(files['tests/test_paths.py']['release'])

if __name__=='__main__':unittest.main()
