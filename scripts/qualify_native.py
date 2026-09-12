"""Run the selected native-host profile and preserve actual command evidence."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'outputs/native-qualification')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    report={'system':platform.platform(),'platform':sys.platform,'python':sys.version,
            'machine':platform.machine(),'commit':os.environ.get('GITHUB_SHA'),
            'scope':'Native controlled host tests and isolated wheel; no authorized provider/chat configured',
            'o12_complete':False,'checks':[],
            'remaining':['Authorized provider text task and Telegram delivery on each native host',
                         'Native service activation/restart evidence'],
            'provider_calls':0,'live_messages':0,'media_operations':0}
    if sys.platform=='win32':
        report['profile']='windows-boundaries'
        report['remaining'][:0]=['Windows process-tree ownership, native lock, junction/reparse-point grants and credential ACL adapter',
                                'Windows service adapter and task execution/recovery qualification']
    elif sys.platform in ('darwin','linux'):report['profile']='posix-text-runtime'
    else:raise SystemExit('No qualification profile for '+sys.platform)
    def save(): (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(name,command):
        start=time.monotonic()
        with (out/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        report['checks'].append({'name':name,'command':list(map(str,command)), 'exit_code':result.returncode,
                                 'seconds':round(time.monotonic()-start,2),'log':name+'.log'})
        save()
        if result.returncode:raise SystemExit('Failed: '+name+'; see '+str(out/(name+'.log')))
    run('host-report',[sys.executable,'-m','task_relay','host'])
    selected=(['tests.test_native_hosts.WindowsBoundaries'] if sys.platform=='win32' else [
        'tests.test_native_hosts.ProcessTrees','tests.test_native_hosts.LinuxServices',
        'tests.test_host_adapters','tests.test_file_tools','tests.test_worker_factory',
        'tests.test_mixed_execution.Tests.test_ambiguous_api_submission_remains_uncertain_across_restart_and_cancel'])
    run('host-tests',[sys.executable,'-m','unittest','-v',*selected])
    run('build',[sys.executable,'-m','build','--outdir',out/'dist'])
    run('environment',[sys.executable,'-m','venv',out/'installed'])
    python=out/'installed'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    wheel=next((out/'dist').glob('*.whl'));sdist=next((out/'dist').glob('*.tar.gz'))
    run('install',[python,'-m','pip','install','--no-deps',wheel])
    run('installed-text' if sys.platform!='win32' else 'installed-boundaries',
        [sys.executable,ROOT/'scripts/qualify_package.py','--python',python,'--wheel',wheel,'--sdist',sdist,
         *(['--boundaries-only'] if sys.platform=='win32' else [])])
    report['selected_profile_passed']=True
    save();print(json.dumps(report,indent=2))


if __name__=='__main__':main()
