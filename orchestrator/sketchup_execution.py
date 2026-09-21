"""SketchUp operations sharing registered attempts and exact-code authorization."""
import json
from pathlib import Path
import secrets
import shutil
import struct
import sys
import time
from . import host_code
from .native_apps import APPS
from .runtime import file_hash, safe_file
from .workers import atomic
from .sketchup_contract import MEDIA, validate_checks, compare, dimension_warnings


def application_binding():
    from task_relay.host_evidence import application_signature
    app=APPS['sketchup'].discover()
    if not app['available']:raise ValueError(app['blocker'])
    return dict(signature=application_signature(app['executable']),version=app.get('version'),
                sources=host_code.source_hashes(APPS['sketchup'].sources))


def execute(frozen, control, documents):
    from task_relay import sketchup_host
    if frozen.get('sketchup_application')!=application_binding():raise ValueError('SketchUp application or implementation changed after dispatch')
    workspace=Path(frozen['workspace']);control=Path(control);out=workspace/'delivery'
    if out.exists() or out.is_symlink():raise ValueError('SketchUp outputs exist; no replacement or replay')
    cap=frozen['execution']['capability'];modeling=cap=='sketchup.run_ruby'
    paths={i['media_type']:safe_file(workspace,i['path']) for i in frozen['inputs'] if i['media_type'] in (MEDIA,'text/x-ruby','application/json')}
    if modeling:
        host_code.verify_frozen(frozen)
        checks=validate_checks(json.loads(paths['application/json'].read_text()))
    app=APPS['sketchup'].discover()
    receipt=dict(host_execution=True,capability=cap,assignment=frozen['assignment_id'],application=frozen['sketchup_application'],
        input_versions=[{k:i[k] for k in ('artifact','sha256','path')} for i in frozen['inputs']],
        outputs=frozen['outputs'],limits=frozen['limits'],runs=[],passed=False)
    if modeling:receipt['authorization']=frozen['host_code_authorization']
    with (control/'sketchup-intent.json').open('x') as stream:json.dump(receipt,stream)
    out.mkdir()
    if modeling:shutil.copyfile(paths['text/x-ruby'],out/'model.rb')
    modes=('before','model','verify') if modeling else ('inspect',) if cap=='sketchup.inspect' else ('startup',)
    deadline=time.monotonic()+max(1,frozen['limits']['seconds']-5)
    baseline_hash=candidate_hash=None;passed=False;findings=[]
    atomic(out/'execution.json',receipt)
    for mode in modes:
        try:
            if frozen['sketchup_application']!=application_binding():raise ValueError('SketchUp application or implementation changed between phases')
            if modeling:host_code.verify_frozen(frozen)
            if mode=='verify' and file_hash(out/'candidate.skp')!=candidate_hash:raise ValueError('SketchUp candidate changed before verification')
            stage=control/('sketchup-'+mode);stage.mkdir()
            worker=stage/'sketchup_worker.rb';shutil.copyfile(Path(__file__).with_name('sketchup_worker.rb'),worker)
            request=dict(mode=mode,token=secrets.token_hex(24),out=str(out),source=str(paths[MEDIA]) if MEDIA in paths else None,
                         snapshot=str(stage/'snapshot.json'),version=app.get('version'))
            if modeling:request.update(script=str(paths['text/x-ruby']),checks=str(paths['application/json']))
            request_path=stage/'request.json';atomic(request_path,request)
            # JSON.parse avoids Ruby interpolation of user-controlled path names.
            launch=stage/'launch.rb'
            def ruby_string(value):return "JSON.parse('"+json.dumps(str(value),ensure_ascii=True).replace('\\','\\\\').replace("'","\\'")+"')"
            launch.write_text("require 'json'\nload "+ruby_string(worker)+"\nTaskRelaySketchup.start("+ruby_string(request_path)+")\n")
            run=sketchup_host.run(app['executable'],launch,request_path,max(.1,deadline-time.monotonic()),sys.platform)
            receipt['runs'].append(dict(mode=mode,**run));passed=run['passed']
            for item in frozen['inputs']:
                if file_hash(safe_file(workspace,item['path']))!=item['sha256']:raise ValueError('SketchUp input copy changed')
            if modeling and file_hash(safe_file(workspace,'delivery/model.rb'))!=frozen['execution']['parameters']['script_sha256']:
                raise ValueError('Delivered Ruby source changed')
            if passed and mode in ('before','verify','inspect'):
                snapshot_path=stage/'snapshot.json'
                if snapshot_path.is_symlink() or snapshot_path.stat().st_size>1500000:raise ValueError('Invalid or oversized SketchUp snapshot')
                snapshot=json.loads(snapshot_path.read_text())
                if not isinstance(snapshot.get('entities'),dict) or not isinstance(snapshot.get('document'),dict):raise ValueError('Incomplete SketchUp snapshot')
                if run['worker']['details'].get('snapshot_sha256')!=file_hash(snapshot_path):raise ValueError('SketchUp snapshot receipt mismatch')
                if mode=='before':baseline_hash=file_hash(snapshot_path)
                elif mode=='inspect':atomic(out/'inspection.json',dict(source_sha256=file_hash(paths[MEDIA]),**snapshot))
                else:
                    baseline=control/'sketchup-before/snapshot.json'
                    if file_hash(baseline)!=baseline_hash:raise ValueError('SketchUp baseline changed')
                    errors=compare(json.loads(baseline.read_text()),snapshot,checks)
                    from .outcomes import quality
                    findings=[quality('dimension_difference',w,'delivery/checks.json; delivery/preview.png') for w in dimension_warnings(snapshot,checks)]
                    receipt['findings']=findings
                    if file_hash(out/'candidate.skp')!=candidate_hash or run['worker']['details'].get('candidate_sha256')!=candidate_hash:
                        raise ValueError('SketchUp candidate changed after save or verification')
                    png=safe_file(workspace,'delivery/preview.png').read_bytes()
                    if len(png)<24 or png[:8]!=b'\x89PNG\r\n\x1a\n' or list(struct.unpack('>II',png[16:24]))!=checks['preview']['resolution']:
                        raise ValueError('SketchUp preview dimensions differ from checks')
                    atomic(out/'checks.json',dict(passed=not errors,errors=errors,findings=findings,before_sha256=baseline_hash,
                          after_sha256=file_hash(snapshot_path),candidate_sha256=candidate_hash,checks=checks))
                    if errors:raise ValueError('; '.join(errors)[:1500])
            if passed and mode=='model':
                if file_hash(control/'sketchup-before/snapshot.json')!=baseline_hash:raise ValueError('SketchUp baseline changed')
                candidate=safe_file(workspace,'delivery/candidate.skp')
                if not candidate.stat().st_size:raise ValueError('Empty SketchUp candidate')
                candidate_hash=file_hash(candidate)
                if run['worker']['details'].get('candidate_sha256')!=candidate_hash:raise ValueError('SketchUp save receipt mismatch')
            if sum(safe_file(workspace,'delivery/'+p.name).stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:
                raise ValueError('SketchUp output byte limit exceeded')
        except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
            passed=False;receipt['validation_error']=str(exc)
        receipt.update(passed=passed,recorded_at=time.time());atomic(out/'execution.json',receipt)
        if not passed:break
    if passed and modeling:
        receipt['lineage']=dict(source_scene_sha256=frozen['execution']['parameters']['scene_sha256'],
            script_sha256=frozen['execution']['parameters']['script_sha256'],candidate_sha256=candidate_hash,
            attempt=frozen['assignment_id'],selected=False)
        atomic(out/'execution.json',receipt)
    diagnostic=cap=='sketchup.startup'
    summary=('SketchUp startup '+('passed.' if passed else 'failed.')) if diagnostic else (
        'SketchUp candidate saved, reopened, checked and previewed; awaiting review and selection.' if passed and modeling else
        'SketchUp model inspected; source unchanged.' if passed else 'SketchUp operation failed; partial outputs retained, no replay.')
    if not passed:
        error=receipt.get('validation_error') or next((r.get('error') for r in reversed(receipt['runs']) if r.get('error')),None)
        if error:summary+=' '+str(error)[:1500]
    success=passed or diagnostic
    uncertain=any(r.get('launched') and not r.get('worker') and r['mode']=='model' for r in receipt['runs'])
    details=dict(outcome='uncertain' if uncertain else 'completed' if success else 'failed',execution=frozen['execution'],summary=summary,usage={},findings=findings)
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',dict(assignment_id=frozen['assignment_id'],summary=summary,
        decision='delivered' if success else 'blocked',instruction='',findings=findings,checks=[dict(criterion=1,passed=success,evidence='delivery/execution.json')]))
    return details
