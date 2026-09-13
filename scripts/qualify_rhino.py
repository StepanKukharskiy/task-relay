#!/usr/bin/env python3
"""Direct Rhino qualification. Host mode runs only fixed, small modeling fixtures."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def host_scenarios(folder, startup_only=False, continuous=False, render_source=None):
    from orchestrator import host_code
    from orchestrator.runtime import Runtime
    from orchestrator.step_runner import execute
    from tests.test_orchestrator import FakeFactory,plan
    from tests.test_blender_operations import operation
    from tests.test_rhino_operations import inputs,checks,MEDIA
    results=[]
    def invoke(name,prepare,expected_failure=False):
        root=folder/name;root.mkdir()
        factory=FakeFactory();rt=Runtime((folder/'project-runtime') if continuous else root/'runtime',factory)
        entry=dict(name=name,passed=False)
        results.append(entry)
        try:
            op=prepare(rt,root);run_id=name if continuous else 'demo';workflow=plan([op]);workflow['id']=run_id;rt.create(workflow)
            if host_code.required(op):
                with rt.transaction():host_code.authorize(rt,run_id,'app',{'source':'explicit_local_qualification_fixed_fixture','script_scope':'fixed native fixtures in qualify_rhino.py and rhino_workflow_fixture.py'})
            rt.tick(run_id);task=rt.task(run_id,'app')
            if not task['latest']:raise ValueError('Host qualification could not dispatch: '+str(rt.status(run_id)))
            session=factory.sessions[task['latest']]
            control=Path(session['session']['control']);control.mkdir(parents=True)
            entry['result']=execute(session['frozen'],control)
            delivery=Path(session['frozen']['workspace'])/'delivery'
            entry['delivery']=str(delivery)
            receipt=json.loads((delivery/'execution.json').read_text())
            entry['passed']=entry['result']['outcome']=='completed' and receipt['passed'] is True
            entry['operation_passed']=entry['passed']
            entry['expected_failure']=expected_failure
            if expected_failure:
                checks_path=delivery/'checks.json'
                errors=json.loads(checks_path.read_text()).get('errors',[]) if checks_path.is_file() else []
                entry['passed']=entry['result']['outcome']=='failed' and any('Untouched object changed' in e for e in errors)
            session['status']={'status':'finished','exit_code':0 if entry['operation_passed'] else 1}
            rt.tick(run_id,dispatch=False)
            entry['runtime_status']=rt.status(run_id)
            if not entry['passed']:raise ValueError('Rhino host failed; inspect '+str(delivery/'execution.json'))
            return delivery
        except Exception:
            entry['error']=traceback.format_exc()
            raise
        finally:
            rt.close()
            (folder/'host-results.json').write_text(json.dumps(results,indent=2))
            print(name+': '+('PASS' if entry['passed'] else 'FAIL'),flush=True)
    if render_source:
        def prepare_render(rt,root):
            from orchestrator.runtime import file_hash
            p=root/'render.json';p.write_text(json.dumps(dict(version=1,engine='rhino_render',named_view='Overview',resolution=[320,240])))
            args=[]
            for path,media in ((render_source,MEDIA),(p,'application/json')):
                aid=rt.register(path,'Exact diagnostic source',path=path.name)
                args.append(dict(artifact=aid,path=path.name,purpose='Bounded render check',authority='Explicit local qualification',media_type=media))
            op=operation('rhino.render',args);op['execution']['parameters']={'manifest_sha256':file_hash(p)}
            return op
        invoke('render-diagnostic',prepare_render)
        return results
    def startup(rt,root):
        p=root/'request.txt';p.write_text('Run only the fixed Rhino version/interpreter startup diagnostic.')
        aid=rt.register(p,'Exact qualification request',path=p.name)
        return operation('rhino.startup',[dict(artifact=aid,path=p.name,purpose='Startup check',authority='Qualification request',media_type='text/plain')])
    invoke('startup',startup)
    if startup_only:return results
    if continuous:
        from rhino_workflow_fixture import run
        run(folder,invoke)
        return results
    created=invoke('create',lambda rt,root:inputs(rt,root))
    def inspect(rt,root):
        p=created/'candidate.3dm';aid=rt.register(p,'Exact new candidate',path='source.3dm')
        return operation('rhino.inspect',[dict(artifact=aid,path='source.3dm',purpose='Inspect saved model',authority='Unaccepted fixture candidate',media_type=MEDIA)])
    inventory=invoke('inspect',inspect)
    data=json.loads((inventory/'inspection.json').read_text())
    ident=next(k for k,v in data['objects'].items() if v['name']=='Tower')
    contract=checks();contract.update(mode='edit',changed_objects=[ident],allow_additions=False,expected_dimensions={'Tower':[2,3,6]})
    script='''import Rhino
import System
ident = System.Guid("%s")
transform = Rhino.Geometry.Transform.Scale(Rhino.Geometry.Plane.WorldXY, 1.0, 1.0, 1.5)
if doc.Objects.Transform(ident, transform, True) == System.Guid.Empty:
    raise ValueError("Transform failed")
''' % ident
    invoke('edit',lambda rt,root:inputs(rt,root,(created/'candidate.3dm').read_bytes(),script,contract))
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true',help='Launch Rhino for fixed startup/create/inspect/edit fixtures; no provider or channel calls')
    parser.add_argument('--rhino-version',choices=('7','8'),help='Select the exact installed major version, with no fallback')
    parser.add_argument('--render-source',type=Path,help='With --host, run only a 320x240 Overview render of this exact selected fixture file')
    parser.add_argument('--continuous',action='store_true',help='One native project: create, three edits, rejected edit/recovery, repeated inspection, three actual renders; restart Relay between stages')
    parser.add_argument('--startup-only',action='store_true',help='With --host, run only the startup fixture')
    parser.add_argument('--skip-controlled',action='store_true',help='Do not repeat already recorded controlled checks')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.rhino_version:os.environ['TASK_RELAY_RHINO_VERSION']=args.rhino_version
    if args.render_source and (not args.host or args.startup_only or args.continuous):parser.error('--render-source requires --host alone')
    if args.continuous and (not args.host or args.startup_only):parser.error('--continuous requires --host without --startup-only')
    if args.startup_only and not args.host:parser.error('--startup-only requires --host')
    folder=(args.output or ROOT/'outputs'/('rhino-qualification-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    folder.mkdir(parents=True,exist_ok=False)
    summary=dict(started=time.time(),command=sys.argv,scope='Controlled fixtures; optional real Rhino host. No live model planning, service reload or network channel delivery.',checks=[])
    status=0
    try:
        if not args.skip_controlled:
            command=[sys.executable,'-m','unittest','tests.test_rhino_operations','tests.test_rhino_planning',
                     'tests.test_blender_edit','tests.test_blender_edit_planning','tests.test_host_apps','tests.test_blender_operations']
            with (folder/'controlled.log').open('w') as log:
                result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            summary['checks'].append(dict(command=command,returncode=result.returncode,log='controlled.log'))
            if result.returncode:raise ValueError('Controlled qualification failed; see controlled.log')
        if args.host:summary['host']=host_scenarios(folder,args.startup_only,args.continuous,args.render_source.resolve() if args.render_source else None)
    except Exception:
        status=1;summary['error']=traceback.format_exc();print(summary['error'],file=sys.stderr)
    summary.update(passed=status==0,finished=time.time())
    (folder/'summary.json').write_text(json.dumps(summary,indent=2))
    print(str(folder/'summary.json'))
    return status


if __name__=='__main__':raise SystemExit(main())
