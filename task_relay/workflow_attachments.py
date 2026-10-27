"""Host-neutral frozen attachment binding and one bounded omission repair.

Only explicit request manifests are eligible. Registration/decoding establishes
byte provenance, never semantic inspection or acceptance.
"""
import hashlib
import io
import json
from pathlib import Path
import secrets
import time


def decoded_image(state, job, item):
    """Static raster compatibility copy; keep original bytes and exact provenance."""
    formats={'image/jpeg':'JPEG','image/webp':'WEBP','image/avif':'AVIF'}
    if item['media_type'] not in formats:return None
    from PIL import Image
    raw=Path(item['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Captured image changed before decoding.')
    with Image.open(io.BytesIO(raw)) as image:
        if (image.format!=formats[item['media_type']] or image.width*image.height>20_000_000
                or getattr(image,'n_frames',1)!=1):
            raise ValueError('Image compatibility copy requires a static raster of at most 20 million pixels.')
        pixels=image.convert('RGBA');out=io.BytesIO();pixels.save(out,format='PNG')
        size=list(image.size)
        pixel_hash=hashlib.sha256(pixels.tobytes()).hexdigest()
    data=out.getvalue();digest=hashlib.sha256(data).hexdigest()
    target=state.media_dir.parent/'route-inputs'/str(job['id'])/'decoded-images'/digest/(Path(item['name']).stem+'.png')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if target.is_symlink() or target.read_bytes()!=data:raise ValueError('Immutable decoded image changed.')
    else:
        with target.open('xb') as stream:stream.write(data);stream.flush()
        target.chmod(0o400)
    return dict(name=target.name,path=str(target.resolve()),sha256=digest,bytes=len(data),
        media_type='image/png',role='Decoded compatibility copy of exact user image',project=None,
        source=item['path'],decoded_from=dict(sha256=item['sha256'],bytes=item['bytes'],
            media_type=item['media_type'],dimensions=size,rgba_sha256=pixel_hash,
            transformation='Static image decoded to RGBA PNG; no resize or inferred content'))


def capture(state,job,pipeline,snapshot):
    from . import attachment_batches,routing_inputs,pipelines,production_control as pc,relay_channels
    from orchestrator.runtime import Runtime
    uploads=routing_inputs.freeze_uploads(state,job,attachment_batches.selected(state,job['id']))
    selected={f['id']:f for f in snapshot.get('uploaded_files',[])}
    for item in uploads:
        original=selected.get(item['upload_id'])
        if not original or any(item[k]!=original[k] for k in ('sha256','bytes')):
            raise ValueError('Workflow attachment changed after request capture.')
    desktop=routing_inputs.desktop_files(state,job['id']) if relay_channels.request_channel(state,job['id'])=='desktop' else []
    rt=Runtime(pc.root(state),connection=state.db);sources=[];bindings=[]
    for index,item in enumerate(uploads+desktop):
        path=('request-uploads/'+str(item['upload_id']) if 'upload_id' in item else 'request-desktop/'+str(index))+'/'+Path(item['name']).name
        aid=rt.register(item['path'],item['role'],run=pipeline,path=path)
        source=pipelines.artifact_source(state,aid);sources.append(source)
        binding=dict(artifact=aid,sha256=source['sha256'],bytes=source['bytes'],
                     request_id=job['id'],captured_path=item['path'])
        decoded=decoded_image(state,job,item)
        if decoded:
            decoded_id=rt.register(decoded['path'],decoded['role'],run=pipeline,
                path='request-decoded/'+str(index)+'/'+decoded['name'])
            sources.append(pipelines.artifact_source(state,decoded_id))
            binding['decoded']=dict(artifact=decoded_id,sha256=decoded['sha256'],bytes=decoded['bytes'],
                                    decoded_from=decoded['decoded_from'])
        bindings.append(binding)
    return sources,dict(version=1,request_id=job['id'],bindings=bindings,provider_calls=0) if bindings else None


def recover_missing(state,pipeline,step,row):
    """Restore omitted exact desktop inputs once, retaining the completed proposal."""
    if not state.db.in_transaction:raise ValueError('Attachment recovery requires an atomic transaction.')
    if (pipeline['status']!='active' or pipeline['channel']!='desktop' or row['status']!='needs_input'
            or row['plan'] or row['run'] or not json.loads(pipeline['spec']).get('completion')):return False
    if not state.db.execute('SELECT 1 FROM completion_recovery_grants WHERE pipeline=?',(pipeline['id'],)).fetchone():return False
    if state.db.execute("SELECT 1 FROM relay_pipeline_events WHERE pipeline=? AND step=? AND kind='request_attachments_recovered'",(pipeline['id'],step['id'])).fetchone():return False
    from . import routing_inputs,pipelines,production_planning as planning,production_control as pc,planner_view
    from orchestrator import contracts as c
    from orchestrator.runtime import Runtime
    originals=routing_inputs.desktop_files(state,pipeline['request_id'])
    if not originals:return False
    payload=json.loads(row['context'])
    if c.digest(payload)!=row['context_hash']:raise ValueError('Frozen planning request changed.')
    rt=Runtime(pc.root(state),connection=state.db)
    for source in payload['sources']:planning.verify_artifact(rt,source)
    present={(source['sha256'],source['bytes']) for source in payload['sources']}
    if all((item['sha256'],item['bytes']) in present for item in originals):return False
    root_job=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(pipeline['request_id'],)).fetchone()
    sources,receipt=capture(state,root_job,pipeline['id'],json.loads(root_job['snapshot'] or '{}'))
    added=[source for source in sources if (source['sha256'],source['bytes']) not in present]
    if not added:return False
    request=-int(c.digest({'attachment_recovery':row['id'],'sources':added})[:15],16)-1
    ident='plan-'+str(request)
    for source in added:
        entry=planning.source_entry(rt,source['artifact'],source['name'],'Exact frozen request attachment',
            'Existing user source; restored omitted binding, no new authorization or inspection.')
        entry.update(workflow_artifact=source['artifact'],media_type=source['media_type'])
        if source['media_type']=='image/png':entry['visual_reference']=True
        payload['sources'].append(entry);payload['required_artifacts'].append(entry['artifact'])
        payload['missing_text_artifacts'].append(entry['artifact'])
    payload['input_ports']=planner_view.ports(payload['sources'],payload.get('handoff_sources',[]))
    payload['planner_instructions']+=planning.UPLOAD_PLANNER_INSTRUCTIONS
    payload['attachment_recovery']=dict(previous_plan=row['id'],previous_context_hash=row['context_hash'],
        request_id=pipeline['request_id'],sources=added,provider_calls=0)
    values=dict(row);values.update(id=ident,request_id=request,parent_id=row['id'],
        context=c.encoded(payload),context_hash=c.digest(payload),status='queued',calls=0,result=None,
        plan=None,plan_hash=None,token=secrets.token_hex(12),event_id=None,expires=time.time()+86400,
        run=None,error=None,created=time.time())
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(request,row['channel']))
    state.db.execute('UPDATE relay_pipeline_steps SET target=? WHERE pipeline=? AND id=?',
                     (ident,pipeline['id'],step['id']))
    pipelines.event(state,pipeline['id'],step['id'],'request_attachments_recovered',
        dict(version=1,previous_plan=row['id'],successor_plan=ident,previous_context_hash=row['context_hash'],
             input_sources=added,attachment_receipt=receipt,provider_calls=0))
    return True
