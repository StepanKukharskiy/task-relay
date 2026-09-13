"""Registered Rhino operations with exact-code grants and no replay."""
import json
from pathlib import Path
import secrets
import struct
import shutil
import sys
import time

from . import host_code
from .runtime import file_hash, safe_file
from .workers import atomic
from .rhino_contract import MEDIA, validate_checks, validate_render


def execute(frozen, control, documents):
    from task_relay.host_apps import rhino
    from task_relay.host_evidence import application_signature
    from task_relay import rhino_host
    from task_relay import host_apps
    app = rhino()
    if not app['available']:raise ValueError(app['blocker'])
    if frozen.get('rhino_application') != {'signature':application_signature(app['executable']),
            'major':app.get('major',8),'version':app.get('version')}:
        raise ValueError('Selected Rhino application/version changed after dispatch')
    if frozen.get('rhino_host_sources') != {m.__name__:file_hash(Path(m.__file__)) for m in (rhino_host,host_apps)}:
        raise ValueError('Rhino host adapter changed after dispatch was frozen')
    for name in ('rhino_execution.py', 'rhino_contract.py', 'rhino_worker.py'):
        if frozen['runtime_sources'].get(name) != file_hash(Path(__file__).with_name(name)):
            raise ValueError('Rhino implementation changed after dispatch was frozen')
    workspace, control = Path(frozen['workspace']), Path(control)
    out = workspace/'delivery'
    if out.exists() or out.is_symlink():raise ValueError('Rhino delivery exists; no replacement or replay')
    cap = frozen['execution']['capability']
    paths = {i['media_type']:safe_file(workspace, i['path']) for i in frozen['inputs'] if i['media_type'] in (MEDIA, 'text/x-python', 'application/json')}
    modeling = cap == 'rhino.run_python'
    rendering = cap == 'rhino.render'
    if rendering:
        if file_hash(paths['application/json']) != frozen['execution']['parameters']['manifest_sha256']:
            raise ValueError('Rhino render manifest hash changed')
        manifest = validate_render(json.loads(paths['application/json'].read_text()))
    if modeling:
        host_code.verify_frozen(frozen)
        validate_checks(json.loads(paths['application/json'].read_text()))
    receipt = dict(host_execution=True, capability=cap, assignment=frozen['assignment_id'], rhino_version=app.get('version'), interpreter=app.get('interpreter'),
        application_signature=application_signature(app['executable']),
        input_versions=[{k:i[k] for k in ('artifact','sha256','path')} for i in frozen['inputs']],
        runtime_sources={name:frozen['runtime_sources'][name] for name in ('rhino_execution.py','rhino_contract.py','rhino_worker.py')},
        host_adapter_sha256=file_hash(Path(rhino_host.__file__)), runs=[], outputs=frozen['outputs'], limits=frozen['limits'],
        scope='Owned Rhino 7/8 process with normal OS permissions. No OS isolation. Grasshopper support is paused. Candidate creation is not selection.')
    if modeling:receipt['authorization'] = frozen['host_code_authorization']
    # Exclusive intent precedes every external process and cannot be replayed.
    with (control/'rhino-intent.json').open('x') as stream:json.dump(receipt, stream)
    out.mkdir()
    if modeling:shutil.copyfile(paths['text/x-python'], out/'model.py')
    modes = ('before','model','verify') if modeling else ('inspect',) if cap == 'rhino.inspect' else ('render',) if rendering else ('startup',)
    deadline = time.monotonic()+max(1, frozen['limits']['seconds']-5)
    baseline_hash = None
    passed = False
    atomic(out/'execution.json', receipt)
    for mode in modes:
        try:
            # Each later process still needs the exact implementation/runtime
            # selected at dispatch; a running multi-phase job is not an upgrade.
            for name in ('rhino_execution.py','rhino_contract.py','rhino_worker.py'):
                if frozen['runtime_sources'][name] != file_hash(Path(__file__).with_name(name)):
                    raise ValueError('Rhino implementation changed between phases')
            if frozen['rhino_host_sources'] != {m.__name__:file_hash(Path(m.__file__)) for m in (rhino_host,host_apps)}:
                raise ValueError('Rhino host adapter changed between phases')
            current = rhino()
            if not current['available'] or current.get('major',8)!=app.get('major',8) or current.get('version')!=app.get('version') or application_signature(current['executable'])!=receipt['application_signature']:
                raise ValueError('Rhino application/version changed between phases')
            if modeling:host_code.verify_frozen(frozen)
        except (OSError,ValueError,KeyError) as exc:
            passed = False
            receipt.update(passed=False, validation_error=str(exc), recorded_at=time.time())
            atomic(out/'execution.json', receipt)
            break
        stage = control/('rhino-'+mode)
        stage.mkdir()
        for name in ('rhino_worker.py', 'rhino_contract.py'):
            shutil.copyfile(Path(__file__).with_name(name), stage/name)
        request = dict(mode=mode, token=secrets.token_hex(24), out=str(out), rhino_major=app.get('major',8),
                       baseline=str(control/'rhino-baseline.json'), source=str(paths[MEDIA]) if MEDIA in paths else None)
        if rendering:request['manifest'] = str(paths['application/json'])
        if modeling:request.update(script=str(paths['text/x-python']), checks=str(paths['application/json']))
        request_path = stage/'request.json'
        atomic(request_path, request)
        script = stage/'launch.py'
        script.write_text(('#! python 2\n' if app.get('major',8)==7 else '#! python 3\n')+
                          '# -*- coding: utf-8 -*-\nimport sys, os, json, time, traceback, io, System\n'+
                          rhino_host.shutdown_script(app.get('major',8),sys.platform)+
                          'request_path = '+repr(str(request_path))+'\n'+
                          'owner_path = os.path.splitext(request_path)[0]+".owner.json"\n'+
                          'deadline = time.time()+10\n'+
                          'while not os.path.exists(owner_path) and time.time()<deadline: time.sleep(.02)\n'+
                          'request=json.loads(io.open(request_path,encoding="utf-8").read())\n'+
                          'owner=json.loads(io.open(owner_path,encoding="utf-8").read())\n'+
                          'pid=int(System.Diagnostics.Process.GetCurrentProcess().Id)\n'+
                          'if owner!={"pid":pid,"token":request["token"]}: raise ValueError("Startup process mismatch")\n'+
                          'try:\n'+
                          '    sys.path.insert(0, os.path.dirname(request_path))\n'+
                          '    import rhino_worker\n    rhino_worker.main(request_path, relay_exit)\n'+
                          'except BaseException:\n'+
                          '    result=dict(pid=pid,token=request["token"],mode=request["mode"],passed=False,error=traceback.format_exc())\n'+
                          '    path=os.path.splitext(request_path)[0]+".result.json"\n'+
                          '    if not os.path.exists(path):\n'+
                          '        with open(path,"wb") as stream: stream.write(json.dumps(result).encode("utf-8"))\n'+
                          '    relay_exit(1)\n')
        try:
            run = rhino_host.run(app['executable'], script, request_path, max(.1, deadline-time.monotonic()), sys.platform)
        except (OSError, ValueError, RuntimeError) as exc:
            run = dict(passed=False, error=str(exc), returncode=None)
        receipt['runs'].append(dict(mode=mode, **run))
        passed = run['passed']
        try:
            for item in frozen['inputs']:
                if file_hash(safe_file(workspace, item['path'])) != item['sha256']:raise ValueError('Rhino input copy changed')
            if modeling:
                if file_hash(safe_file(workspace, 'delivery/model.py')) != frozen['execution']['parameters']['script_sha256']:
                    raise ValueError('Delivered Rhino script changed')
                baseline = control/'rhino-baseline.json'
                if passed and mode == 'before':baseline_hash = file_hash(baseline)
                if mode in ('model','verify') and baseline_hash != file_hash(baseline):raise ValueError('Rhino baseline evidence changed')
            if passed and mode == 'inspect':
                inventory = json.loads(safe_file(workspace, 'delivery/inspection.json').read_text())
                if not isinstance(inventory.get('objects'), dict):raise ValueError('Missing Rhino inventory')
            if passed and mode == 'render':
                evidence = json.loads(safe_file(workspace, 'delivery/checks.json').read_text())
                png = safe_file(workspace, 'delivery/render.png').read_bytes()
                if len(png)<24 or png[:8]!=b'\x89PNG\r\n\x1a\n' or list(struct.unpack('>II',png[16:24]))!=manifest['resolution']:
                    raise ValueError('Rhino render PNG dimensions differ from the manifest')
                digest=file_hash(out/'render.png')
                if evidence.get('passed') is not True or evidence.get('engine')!='rhino_render' or evidence.get('render_sha256')!=digest or run['worker']['details'].get('render_sha256')!=digest:
                    raise ValueError('Rhino render evidence differs from saved image')
            if passed and mode == 'verify':
                evidence = json.loads(safe_file(workspace, 'delivery/checks.json').read_text())
                if evidence.get('passed') is not True:raise ValueError('Independent Rhino checks failed')
                png = safe_file(workspace, 'delivery/preview.png').read_bytes()
                if png[:8] != b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid Rhino viewport preview')
                candidate = safe_file(workspace, 'delivery/candidate.3dm')
                if candidate.stat().st_size == 0:raise ValueError('Empty Rhino candidate')
                if file_hash(candidate) != run['worker']['details'].get('candidate_sha256'):raise ValueError('Candidate changed after verification')
            if sum(safe_file(workspace, 'delivery/'+p.name).stat().st_size for p in out.iterdir()) > frozen['limits']['output_bytes']:
                raise ValueError('Rhino output byte limit exceeded')
        except (OSError, ValueError, KeyError) as exc:
            passed = False
            receipt['validation_error'] = str(exc)
        receipt.update(passed=passed, recorded_at=time.time())
        atomic(out/'execution.json', receipt)
        if not passed:break
    diagnostic = cap == 'rhino.startup'
    if passed and modeling:
        receipt['lineage'] = dict(source_scene_sha256=frozen['execution']['parameters']['scene_sha256'],
            script_sha256=frozen['execution']['parameters']['script_sha256'], candidate_sha256=file_hash(out/'candidate.3dm'),
            attempt=frozen['assignment_id'], selected=False)
        atomic(out/'execution.json', receipt)
    summary = ('Rhino startup '+('passed.' if passed else 'failed; see execution.json.')) if diagnostic else (
        'Rhino candidate saved, independently reopened, checked and previewed; awaiting review and selection.' if passed and modeling else
        'Rhino Render image saved at the selected named view and resolution; source unchanged.' if passed and rendering else
        'Selected Rhino model inspected; source copy unchanged.' if passed else 'Rhino operation failed; partial files are not accepted. No automatic replay; see execution.json.')
    details = dict(outcome='completed' if passed or diagnostic else 'failed', execution=frozen['execution'], summary=summary, usage={})
    atomic(control/'operation.json', details)
    atomic(workspace/'.relay/result.json', dict(assignment_id=frozen['assignment_id'], summary=summary,
        decision='delivered' if passed or diagnostic else 'blocked', instruction='',
        checks=[dict(criterion=1, passed=passed or diagnostic, evidence='delivery/execution.json: '+summary)]))
    return details
