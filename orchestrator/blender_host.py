"""Bounded Blender host operations: fixed startup probe or validated primitive scene.

Runs as a registered local operation, not as an escaped agent shell command.
The host process has normal OS permissions. Only fixed code and numeric scene
specifications can reach Blender; existing scenes and arbitrary scripts are excluded.
"""
import json
import math
import platform
import sys
import shutil
import subprocess
import time
from pathlib import Path

from .runtime import safe_file, file_hash
from .workers import atomic

PROBE='import bpy; print("BLENDER_STARTUP_OK", bpy.app.version_string, flush=True)'
SCENE_DESCRIPTION={'objects':'1–500 objects: shape cube/cylinder, position [x,y,z], size [x,y,z] > 0, rotation [rx,ry,rz] radians, color [r,g,b] 0..1',
                   'camera':'position [x,y,z], target [x,y,z], scale 0.1..10000',
                   'resolution':'[width,height], integer 64..1600', 'samples':'integer 1..32',
                   'version':1}

MESH_DESCRIPTION={**SCENE_DESCRIPTION,'version':2,
    'objects':'1–500 cube/cylinder or mesh objects. All: position, size, rotation, color as in primitive scene. Mesh additionally requires vertices and faces.',
    'vertices':'Mesh-local finite [x,y,z] coordinates within ±10000; 3–100000 total vertices across all meshes.',
    'faces':'Triangle/quad arrays of distinct in-range integer vertex indices; 1–200000 total faces. No degenerate triangles. No scripts, file paths or expressions.',
    'input_limit':'20 MB scene plus text context. Generate geometry with agent-side code, not by writing arrays in a chat answer.'}


def scene(value,allow_mesh=False):
    def keys(obj,expected):
        if not isinstance(obj,dict) or set(obj)!=set(expected):raise ValueError('Unsupported or missing Blender scene fields')
    def vector(v,lo,hi):
        if not isinstance(v,list) or len(v)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or not lo<=n<=hi for n in v):
            raise ValueError('Invalid bounded Blender scene vector')
    keys(value,('version','objects','camera','resolution','samples'))
    if type(value['version']) is not int or value['version']!=(2 if allow_mesh else 1):raise ValueError('Unsupported scene version')
    objects=value['objects']
    if not isinstance(objects,list) or not 1<=len(objects)<=500:raise ValueError('Use 1–500 scene objects')
    vertices_count=faces_count=0
    for obj in objects:
        mesh=allow_mesh and isinstance(obj,dict) and obj.get('shape')=='mesh'
        keys(obj,('shape','position','size','rotation','color',*(('vertices','faces') if mesh else ())))
        if obj['shape'] not in (('cube','cylinder','mesh') if allow_mesh else ('cube','cylinder')):raise ValueError('Unsupported shape')
        if mesh:
            vertices_count,faces_count=mesh_data(obj,vector,vertices_count,faces_count)
        vector(obj['position'],-10000,10000);vector(obj['size'],0.001,10000)
        vector(obj['rotation'],-100,100);vector(obj['color'],0,1)
    keys(value['camera'],('position','target','scale'));cam=value['camera']
    vector(cam['position'],-10000,10000);vector(cam['target'],-10000,10000)
    if cam['position']==cam['target']:raise ValueError('Camera position and target must differ')
    if type(cam['scale']) not in (float,int) or not 0.1<=cam['scale']<=10000:raise ValueError('Invalid camera scale')
    res=value['resolution']
    if not isinstance(res,list) or len(res)!=2 or any(type(n) is not int or not 64<=n<=1600 for n in res):raise ValueError('Invalid render dimensions')
    if type(value['samples']) is not int or not 1<=value['samples']<=32:raise ValueError('Invalid sample limit')
    return value


def execute(frozen,control,documents):
    from task_relay.host_apps import blender
    from task_relay.host_evidence import application_signature
    app=blender()
    if not app['available']:raise ValueError(app['blocker'])
    workspace=Path(frozen['workspace']);control=Path(control)
    cap=frozen['execution']['capability'];deadline=time.monotonic()+max(1,frozen['limits']['seconds']-5)
    output=workspace/'delivery'
    if output.exists() or output.is_symlink():raise ValueError('Blender output directory already exists; no files were replaced')
    for name in ('blender_host.py','blender_scene.py'):
        if frozen.get('runtime_sources',{}).get(name)!=file_hash(Path(__file__).with_name(name)):
            raise ValueError('Blender implementation changed after dispatch was frozen')
    payload=None
    if cap in ('blender.scene','blender.mesh_scene'):
        inputs=[d for d,i in zip(documents,frozen['inputs']) if i['media_type']=='application/json']
        if len(inputs)!=1:raise ValueError('Blender scene requires exactly one JSON scene input')
        payload=scene(json.loads(inputs[0]['text']),allow_mesh=cap=='blender.mesh_scene')
    # Commit an exclusive intent before any external process, including startup.
    with (control/'blender-intent.json').open('x') as stream:
        json.dump({'assignment':frozen['assignment_id'],'capability':cap,'executable':app['executable'],
                   'input_hashes':[d['sha256'] for d in documents],'created':time.time()},stream)
    output.mkdir()
    logs=[]
    def run(args,marker):
        command=[app['executable'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',*args]
        start=time.time()
        try:
            result=subprocess.run(command,cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,
                                  timeout=max(0.1,deadline-time.monotonic()))
            receipt={'command':command,'returncode':result.returncode,'stdout':result.stdout.decode('utf-8','replace')[-64000:],
                     'stderr':result.stderr.decode('utf-8','replace')[-64000:],'elapsed_seconds':time.time()-start,
                     'stdout_bytes':len(result.stdout),'stderr_bytes':len(result.stderr),'timeout':False}
        except subprocess.TimeoutExpired as exc:
            receipt={'command':command,'returncode':None,'timeout':True,'elapsed_seconds':time.time()-start,
                     'stdout':(exc.stdout or b'').decode('utf-8','replace')[-64000:],'stderr':(exc.stderr or b'').decode('utf-8','replace')[-64000:]}
        receipt['marker_present']=marker in receipt['stdout']
        receipt['streams_may_be_truncated']=receipt.get('stdout_bytes',0)>64000 or receipt.get('stderr_bytes',0)>64000 or receipt['timeout']
        logs.append(receipt)
        atomic(output/'execution.json',{'host_execution':True,'capability':cap,'runs':logs,
            'environment':{'platform':sys.platform,'architecture':platform.machine(),'cwd':str(workspace),'executable':app['executable']},
            'input_hashes':[d['sha256'] for d in documents],
            'runtime_sources':{k:frozen['runtime_sources'][k] for k in ('blender_host.py','blender_scene.py')},
            'recorded_at':time.time(), 'application_signature':application_signature(app['executable']),
            'scope':'Fixed Relay code; no arbitrary scripts. Diagnostic success is not scene acceptance.'})
        return receipt['returncode']==0 and receipt['marker_present']
    if cap=='blender.startup':
        ok=run(['--python-expr',PROBE],'BLENDER_STARTUP_OK')
        # The requested product is the diagnostic, including a failed probe.
        summary='Blender host startup '+('passed.' if ok else 'failed; see execution.json.')
        passed=True
    else:
        data=control/'scene.json';atomic(data,payload)
        script=output/'scene-script.py';shutil.copyfile(Path(__file__).with_name('blender_scene.py'),script)
        passed=run(['--python',str(script),'--','build',str(data),str(output)],'RELAY_SCENE_SAVED')
        if passed:passed=run(['--python',str(script),'--','verify-render',str(data),str(output)],'RELAY_SCENE_VERIFIED_RENDERED')
        if passed:
            passed=(safe_file(workspace,'delivery/scene.blend').stat().st_size>0
                    and safe_file(workspace,'delivery/preview.png').read_bytes()[:8]==b'\x89PNG\r\n\x1a\n')
        summary='Blender scene saved, reopened and rendered.' if passed else 'Blender host execution failed; see delivery/execution.json. No automatic retry.'
    sizes=sum(safe_file(workspace,o['path']).stat().st_size for o in frozen['outputs'] if (workspace/o['path']).exists())
    if sizes>frozen['limits']['output_bytes']:raise ValueError('Blender outputs exceed the approved byte limit')
    details={'outcome':'completed' if passed else 'failed','execution':frozen['execution'],'usage':{},'summary':summary,'output_bytes':sizes}
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',{'assignment_id':frozen['assignment_id'],'summary':summary,
        'decision':'delivered' if passed else 'blocked','instruction':'',
        'checks':[{'criterion':1,'passed':passed,'evidence':'delivery/execution.json: '+summary}]})
    return details


def mesh_data(obj,vector,vertices_count,faces_count):
    vertices=obj['vertices'];faces=obj['faces']
    if not isinstance(vertices,list) or not 3<=len(vertices)<=100000:raise ValueError('Mesh needs 3–100000 vertices')
    if not isinstance(faces,list) or not 1<=len(faces)<=200000:raise ValueError('Mesh needs 1–200000 faces')
    vertices_count+=len(vertices);faces_count+=len(faces)
    if vertices_count>100000 or faces_count>200000:raise ValueError('Scene exceeds the total mesh budget')
    for v in vertices:vector(v,-10000,10000)
    for face in faces:
        if (not isinstance(face,list) or len(face) not in (3,4)
                or any(type(i) is not int or not 0<=i<len(vertices) for i in face)
                or len(set(face))!=len(face)):
            raise ValueError('Mesh faces require 3 or 4 distinct in-range vertex indices')
        # Reject zero-area fan triangles. Open surfaces remain valid; watertightness
        # is an assignment-specific check rather than an inferred requirement.
        a=vertices[face[0]]
        for k in range(1,len(face)-1):
            u=[x-y for x,y in zip(vertices[face[k]],a)];v=[x-y for x,y in zip(vertices[face[k+1]],a)]
            cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            if sum(x*x for x in cross)<=1e-24:raise ValueError('Mesh contains a degenerate face')
    return vertices_count,faces_count
