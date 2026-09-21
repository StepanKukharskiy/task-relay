"""Exact-approved standalone CPython, full rhino3dm API, no native Rhino dispatch."""
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

from . import host_code
from .rhino3dm_document import available
from .rhino3dm_script_contract import validate_checks
from .runtime import file_hash,safe_file
from .workers import atomic


def runtime_identity():
    library=available()
    from rhino3dm import _rhino3dm
    return dict(library_version=library.__version__,python_version=sys.version,
        files={str(Path(m.__file__).resolve()):file_hash(Path(m.__file__)) for m in (library,_rhino3dm)})


def discover():
    try:identity=runtime_identity()
    except (ImportError,OSError,ValueError) as exc:
        return dict(available=False,blocker=str(exc),evidence=str(exc),executable=sys.executable,version=None,interpreter='CPython')
    return dict(available=True,blocker=None,evidence='Pinned standalone rhino3dm; no Rhino application needed',
        executable=sys.executable,version=identity['library_version'],interpreter='CPython '+sys.version.split()[0],library_runtime=identity)


def run_phase(request,path,timeout,workspace):
    atomic(path,request)
    command=[sys.executable,'-I',str(Path(__file__).with_name('rhino3dm_script_worker.py')),str(path)]
    stdout=path.with_suffix('.stdout');stderr=path.with_suffix('.stderr')
    run=dict(mode=request['mode'],command=command,passed=False,timeout=False,returncode=None)
    # Inherit the supervisor's process tree; OS-specific cancellation stays there.
    with stdout.open('xb') as out,stderr.open('xb') as err:
        try:
            result=subprocess.run(command,cwd=workspace,stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=timeout)
            run['returncode']=result.returncode
        except subprocess.TimeoutExpired:run['timeout']=True
        except OSError as exc:run['error']=str(exc)
    result_path=Path(request['result'])
    if result_path.exists():
        if result_path.is_symlink() or result_path.stat().st_size>100000:raise ValueError('Invalid library worker receipt')
        result=json.loads(result_path.read_text())
        if result.get('token')!=request['token'] or result.get('mode')!=request['mode']:raise ValueError('Library worker receipt identity mismatch')
        run['worker']=result
        run['passed']=result.get('passed') is True and run['returncode']==0 and not run['timeout']
    return run


def execute(frozen,control,documents):
    host_code.verify_frozen(frozen)
    workspace=Path(frozen['workspace']);control=Path(control);out=workspace/'delivery'
    if out.exists() or out.is_symlink():raise ValueError('Library delivery exists; no replacement or replay')
    paths={i['media_type']:safe_file(workspace,i['path']) for i in frozen['inputs']
           if i['media_type'] in ('application/vnd.rhino','text/x-python','application/json')}
    checks=validate_checks(json.loads(paths['application/json'].read_text()))
    grant=frozen['host_code_authorization']
    receipt=dict(capability='rhino3dm.run_python',execution_mode='standalone_library',host_execution=True,
        native_application_execution=False,native_rhino_verified=False,authorization=grant,
        library_runtime=runtime_identity(),file_version=checks['file_version'],assignment=frozen['assignment_id'],
        input_versions=[{k:i[k] for k in ('artifact','path','sha256')} for i in frozen['inputs']],
        limits=frozen['limits'],runs=[],passed=False,selected=False,
        scope='Exact reviewed CPython with normal filesystem/network permissions; no OS isolation. Runner uses rhino3dm, not a Rhino application.')
    with (control/'rhino3dm-script-intent.json').open('x') as stream:json.dump(receipt,stream)
    out.mkdir();shutil.copyfile(paths['text/x-python'],out/'model.py');atomic(out/'execution.json',receipt)
    deadline=time.monotonic()+max(1,frozen['limits']['seconds']-5)
    baseline=control/'rhino3dm-baseline.json';prepared=control/'rhino3dm-prepared.json'
    baseline_hash=prepared_hash=candidate_hash=None;passed=False;uncertain=False
    try:
        for mode in ('before','model','verify'):
            host_code.verify_frozen(frozen)
            for item in frozen['inputs']:
                if file_hash(safe_file(workspace,item['path']))!=item['sha256']:raise ValueError('Library input changed between phases')
            request=dict(mode=mode,token=secrets.token_hex(24),out=str(out),workspace=str(workspace),
                library_runtime=receipt['library_runtime'],
                source=str(paths['application/vnd.rhino']) if 'application/vnd.rhino' in paths else None,
                script=str(paths['text/x-python']),checks=str(paths['application/json']),baseline=str(baseline),prepared=str(prepared),
                input_paths={i['path']:str(safe_file(workspace,i['path'])) for i in frozen['inputs']},
                result=str(control/('rhino3dm-'+mode+'.result.json')))
            run=run_phase(request,control/('rhino3dm-'+mode+'.json'),max(.1,deadline-time.monotonic()),workspace)
            receipt['runs'].append(run);passed=run['passed']
            if mode=='model' and (run['timeout'] or 'worker' not in run):uncertain=True
            for item in frozen['inputs']:
                if file_hash(safe_file(workspace,item['path']))!=item['sha256']:raise ValueError('Library input copy changed')
            if file_hash(safe_file(workspace,'delivery/model.py'))!=frozen['execution']['parameters']['script_sha256']:
                raise ValueError('Delivered library script changed')
            if mode=='before' and passed:baseline_hash=file_hash(baseline)
            if mode!='before' and file_hash(baseline)!=baseline_hash:raise ValueError('Library baseline evidence changed')
            if mode=='model' and passed:
                prepared_hash=file_hash(prepared);candidate_hash=file_hash(safe_file(workspace,'delivery/candidate.3dm'))
                if run['worker'].get('details',{}).get('candidate_sha256')!=candidate_hash:
                    raise ValueError('Library candidate changed after script worker saved it')
            if mode=='verify' and (file_hash(prepared)!=prepared_hash or file_hash(safe_file(workspace,'delivery/candidate.3dm'))!=candidate_hash):
                raise ValueError('Library candidate or before-save evidence changed during verification')
            if sum(safe_file(workspace,'delivery/'+p.name).stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:
                raise ValueError('Library delivery exceeds output byte limit')
            receipt.update(passed=passed,recorded_at=time.time());atomic(out/'execution.json',receipt)
            if not passed:break
        if passed:
            evidence=json.loads(safe_file(workspace,'delivery/checks.json').read_text())
            if evidence.get('passed') is not True or evidence.get('candidate_sha256')!=candidate_hash:
                raise ValueError('Library verification report does not match candidate')
            receipt.update(candidate_sha256=candidate_hash,warnings=evidence['warnings'])
    except Exception as exc:
        if mode=='model' and (not receipt['runs'] or receipt['runs'][-1]['mode']!='model'):uncertain=True
        passed=False;receipt['validation_error']=str(exc)
    receipt.update(passed=passed,recorded_at=time.time(),outcome='uncertain' if uncertain else 'completed' if passed else 'failed')
    atomic(out/'execution.json',receipt)
    if passed and sum(p.stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:
        passed=False;receipt.update(passed=False,outcome='failed',validation_error='Library delivery exceeds total output byte limit')
        atomic(out/'execution.json',receipt)
    from .outcomes import quality
    findings=[quality('library_geometry_difference',w,'delivery/checks.json') for w in receipt.get('warnings',[])]
    summary=('Standalone rhino3dm script completed; version-'+str(checks['file_version'])+' file independently reopened with the library. '
             'Not executed or verified in Rhino; awaiting review and selection.') if passed else 'Standalone library operation '+receipt['outcome']+'; partial artifacts are diagnostic only. No automatic replay.'
    if findings:summary+=' Quality concerns require explicit user review.'
    details=dict(execution=frozen['execution'],summary=summary,usage={},findings=findings,**receipt)
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',dict(assignment_id=frozen['assignment_id'],summary=summary,findings=findings,
        decision='delivered' if passed else 'blocked',instruction='',checks=[dict(criterion=1,passed=passed,evidence='delivery/execution.json; delivery/checks.json: '+summary)]))
    return details
