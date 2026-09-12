"""Qualify an installed wheel outside the checkout using one local text procedure."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--sdist', type=Path, required=True)
    parser.add_argument('--contents-only', action='store_true',
                        help='Compare final archive/installed bytes without rerunning the text procedure')
    parser.add_argument('--boundaries-only', action='store_true',
                        help='Verify installed imports/CLI only; execution remains explicitly unqualified')
    args = parser.parse_args()
    python = str(args.python.absolute())  # preserve the venv interpreter symlink
    cli = args.python.absolute().with_name('task-relay.exe' if os.name=='nt' else 'task-relay')
    spec = tomllib.loads((ROOT/'pyproject.toml').read_text())
    modules = spec['tool']['setuptools']['py-modules']
    expected = {name+'.py' for name in modules}
    for package in spec['tool']['setuptools']['packages']:
        expected.update(p.relative_to(ROOT).as_posix() for p in (ROOT/package).glob('*.py'))
    for pattern in spec['tool']['setuptools']['package-data']['task_relay']:
        expected.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'task_relay').glob(pattern))
    with zipfile.ZipFile(args.wheel) as archive:
        runtime = {n for n in archive.namelist() if '.dist-info/' not in n}
        assert runtime == expected, (runtime-expected, expected-runtime)
        metadata = set(archive.namelist())-runtime
        prefix = 'task_relay-'+spec['project']['version']+'.dist-info/'
        assert metadata == {prefix+n for n in ('METADATA','WHEEL','RECORD','entry_points.txt','top_level.txt','licenses/LICENSE')}, metadata
        assert archive.read(prefix+'licenses/LICENSE') == (ROOT/'LICENSE').read_bytes()
        from email.parser import BytesParser
        package_metadata = BytesParser().parsebytes(archive.read(prefix+'METADATA'))
        assert package_metadata['License-Expression'] == 'Apache-2.0'
        assert package_metadata.get_all('License-File') == ['LICENSE']
        for name in expected:
            assert archive.read(name) == (ROOT/name).read_bytes(), name
    with tarfile.open(args.sdist) as archive:
        contents = {'/'.join(m.name.split('/')[1:]) for m in archive.getmembers() if m.isfile()}
        # setuptools adds generated PKG-INFO/setup.cfg and build metadata.
        extras = contents-expected-{'pyproject.toml','MANIFEST.in','README.md','LICENSE','PKG-INFO','setup.cfg'}
        license_members = [m for m in archive.getmembers() if m.isfile() and '/'.join(m.name.split('/')[1:]) == 'LICENSE']
        assert len(license_members) == 1
        assert archive.extractfile(license_members[0]).read() == (ROOT/'LICENSE').read_bytes()
        allowed = {'task_relay.egg-info/'+n for n in
                   ('PKG-INFO','SOURCES.txt','dependency_links.txt','entry_points.txt','requires.txt','top_level.txt')}
        assert extras <= allowed, extras
        assert expected <= contents, expected-contents
    report = {'wheel_sha256': hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
              'runtime_files': len(expected), 'distribution_contents_verified': True}
    if args.contents_only:
        result = subprocess.run([python,'-I','-c','import sysconfig; print(sysconfig.get_path("purelib"))'],
                                check=True,capture_output=True,text=True)
        installed = Path(result.stdout.strip())
        for name in expected:
            assert (installed/name).read_bytes() == (ROOT/name).read_bytes(), name
        report['installed_runtime_matches_final_distribution'] = True
        print(json.dumps(report, indent=2))
        return
    with tempfile.TemporaryDirectory(prefix='relay-package-') as folder:
        temp = Path(folder).resolve()
        env = {k:v for k,v in os.environ.items() if k not in
               ('PYTHONPATH','TASK_RELAY_DATA_DIR','TASK_RELAY_WORKSPACE_DIR','TASK_RELAY_GENERATED_DIR')}
        env.update(PYTHONDONTWRITEBYTECODE='1', TASK_RELAY_DATA_DIR=str(temp/'data'),
                   TASK_RELAY_WORKSPACE_DIR=str(temp/'projects'), TASK_RELAY_GENERATED_DIR=str(temp/'generated'))
        def run(command, selected_env=None):
            result = subprocess.run(command, cwd=temp, env=env if selected_env is None else selected_env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(str(command)+'\n'+result.stdout+'\n'+result.stderr)
            assert not result.stderr, result.stderr
            return result.stdout
        for command in ([str(cli),'--help'], [python,'-m','task_relay','--help'],
                        [str(cli),'orchestrator','--help'], [str(cli),'telegram','--help'],
                        [str(cli),'messages','--help'], [str(cli),'usage','--help']):
            run(command)
        paths = json.loads(run([str(cli),'paths']))
        assert paths['state'] == str(temp/'data/state.sqlite')
        assert not (temp/'data').exists(), 'Help/path inspection must not create state'
        assert Path(paths['install']) != ROOT
        for key in ('messages_icon','menu_icon'):
            assert Path(paths[key]).is_file() and not Path(paths[key]).is_relative_to(ROOT/'task_relay')
        code = '''import importlib,json
from pathlib import Path
from task_relay.relay_paths import PATHS
for name in MODULES:
    legacy=importlib.import_module(name)
    canonical=importlib.import_module('task_relay.'+name)
    assert legacy is canonical,name
    assert Path(canonical.__file__).is_relative_to(PATHS.install),name
print(json.dumps({'canonical_modules':len(MODULES)}))
'''.replace('MODULES', repr(modules))
        report.update(json.loads(run([python,'-c',code])))
        report['installed_paths'] = paths
        if args.boundaries_only:
            report.update(execution_qualified=False, scope='Installed imports and CLI inspection only',
                          network_or_media_calls=0)
            print(json.dumps(report, indent=2))
            return
        code = '''import json,subprocess,sys,time
from pathlib import Path
from task_relay.relay_paths import PATHS
from task_relay.bridge import State
from orchestrator.runtime import Runtime
from orchestrator import execution
rt=Runtime(PATHS.runtime)
source=PATHS.data/'source.txt';source.write_text('Exact installed input\\n')
aid=rt.register(source,'Fixture text',path='source.txt')
task=dict(id='bundle',role='procedure',objective='Bundle text',instruction='Preserve source',
 execution={'capability':'text.bundle','version':1,'parameters':{}},
 inputs=[dict(artifact=aid,path='source.txt',sha256=rt.artifact(aid)['sha256'],purpose='Fixture',authority='Data only',media_type='text/plain')],
 outputs=[dict(path='bundle.txt',purpose='Fixture bundle',media_type='text/plain')],criteria=execution.REGISTRY['text.bundle']['criteria'])
rt.create(dict(id='installed-check',brief='Installed package test',backend={'type':'codex-cli','model':'fixture','reasoning':'high'},tasks=[task]))
rt.tick('installed-check');rt.close();rt=Runtime(PATHS.runtime)
end=time.monotonic()+15
while time.monotonic()<end:
 status=rt.tick('installed-check')
 if status['status']=='completed':break
 time.sleep(.05)
assert status['status']=='completed',status
assert len(status['attempts'])==1
artifact=rt.output('installed-check','bundle','bundle.txt')
assert 'Exact installed input' in Path(artifact['blob']).read_text()
state=State(PATHS.state)
assert state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0]==1
# Actual provider-check entry point, with no queued job: opens the same fixture
# database, performs no transport and exits. This is startup coverage only.
child=subprocess.run([sys.executable,str(PATHS.install/'provider_runner.py'),str(PATHS.state),'absent-fixture'],capture_output=True,text=True,timeout=10)
assert child.returncode==0,(child.stdout,child.stderr)
for child in rt.factory.registered.children:child.wait(timeout=5)
print(json.dumps({'procedure':'completed','attempts':1,'artifact_sha256':artifact['sha256'],'provider_entry_startup':'passed; no job or network'}))
state.db.close();rt.close()
'''
        report.update(json.loads(run([python,'-c',code])))
        status = json.loads(run([str(cli),'orchestrator','status','installed-check']))
        assert status['status'] == 'completed'
        report['cli_reopen'] = 'completed'
        report['network_or_media_calls'] = 0
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
