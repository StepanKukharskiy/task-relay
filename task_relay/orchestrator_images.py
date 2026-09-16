"""Natural-language image jobs using the existing managed Gemini image backend."""
import json
from pathlib import Path
import secrets
import shlex
from orchestrator.handoff_contracts import MANAGED_IMAGE_REFERENCES

UPLOAD_SCOPE = '@orchestrator'


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS orchestrator_image_requests (
      job_id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, backend_job_id TEXT NOT NULL,
      reference_ids TEXT NOT NULL)''')


def files(state, focus=None):
    scopes=[UPLOAD_SCOPE] + ([focus] if focus else [])
    return [dict(r) for r in state.db.execute(
        'SELECT id,filename,caption,status,bytes,sha256 FROM production_uploads WHERE run IN ('+
        ','.join('?' for _ in scopes)+") AND status IN ('pending','ready','failed') ORDER BY rowid", scopes)]


def validate_selection(action, snapshot):
    from task_relay import routing_inputs
    refs=action.get('reference_ids');artifacts=action.get('artifact_ids',[])
    available={f['id'] for f in snapshot.get('uploaded_files',[]) if f['status']=='ready'}
    if (set(action)-{'artifact_ids','provider','model'}!={'kind','reference_ids'} or not isinstance(refs,list)
            or any(type(i) is not int or i not in available for i in refs) or len(set(refs))!=len(refs)):
        raise ValueError('Choose ready uploaded references and exact production artifact IDs.')
    preferred = snapshot.get('capabilities', {}).get('model_defaults', {}).get('image', {}).get('provider', 'gemini')
    if action.get('provider', 'gemini' if snapshot.get('media_reply') else preferred)!='gemini':
        raise ValueError('This immediate image action supports Gemini. Use an available provider-specific production image operation; no fallback was made.')
    if 'model' in action:
        from task_relay import gemini
        gemini.model_name(action['model'])
    routing_inputs.validate_artifact_ids(artifacts,snapshot.get('production_artifacts',[]))
    if len(refs)+len(artifacts)>MANAGED_IMAGE_REFERENCES:raise ValueError('Choose at most six image references in total.')
    known={a['id']:a for a in snapshot.get('production_artifacts',[])}
    if any(Path(known[i]['path']).suffix.lower() not in ('.png','.jpg','.jpeg','.webp') for i in artifacts):
        raise ValueError('Image generation needs an image artifact, not a Blender scene or report.')


def queue(state, job, reference_ids, artifact_ids=None, provider='gemini', model=None):
    from task_relay import backends
    from task_relay import gemini
    from task_relay import production_control as pc
    from orchestrator.runtime import safe_file, file_hash
    existing=state.db.execute('SELECT * FROM orchestrator_image_requests WHERE job_id=?',(job['id'],)).fetchone()
    if existing:
        return existing['task_id'], 'This image request is already queued or handled. No duplicate generation was started.'
    if not state.db.in_transaction:
        raise ValueError('Image queueing requires an outer transaction.')
    from task_relay import routing_inputs
    artifact_ids=[] if artifact_ids is None else artifact_ids
    validate_selection({'kind':'generate_image','reference_ids':reference_ids,'artifact_ids':artifact_ids,'provider':provider,
        **({'model':model} if model is not None else {})},
        {'uploaded_files':files(state,job['focus']),'production_artifacts':routing_inputs.artifact_catalog(state)})
    available={f['id']:f for f in files(state,job['focus'])}
    references=[]
    for ident in reference_ids:
        if ident not in available or available[ident]['status']!='ready':
            raise ValueError('A selected reference is unavailable or still downloading. Wait for “Attached” before asking again.')
        row=state.db.execute('SELECT * FROM production_uploads WHERE id=?',(ident,)).fetchone()
        path=safe_file(pc.root(state).parent/'production-guides',str(ident)+'/'+row['filename'])
        if str(path.resolve())!=row['path'] or path.stat().st_size!=row['bytes'] or file_hash(path)!=row['sha256']:
            raise ValueError('The uploaded reference changed. Please upload it again.')
        mime=gemini.validate_input(path,row['filename'])
        references.append((row,path,mime))
    catalog={a['id']:a for a in routing_inputs.artifact_catalog(state)}
    if sum(r[0]['bytes'] for r in references)+sum(catalog[i]['bytes'] for i in artifact_ids)>11_000_000:
        raise ValueError('Image references exceed 11 MB total.')
    frozen=routing_inputs.freeze_artifacts(state,job,artifact_ids)
    for record in frozen:
        path=Path(record['path']);filename=catalog[record['artifact_id']]['display_name']
        mime=gemini.validate_input(path,filename)
        references.append((dict(id=record['artifact_id'],filename=filename,bytes=record['bytes'],run=record['run'],
            caption='',sha256=record['sha256']),path,mime))
    if sum(r[0]['bytes'] for r in references)>11_000_000:
        raise ValueError('Image references exceed 11 MB total.')
    config=gemini.read_config()
    if not config:
        raise ValueError('Connect Gemini through /providers to generate images.')
    selected_model=gemini.model_name(model or config.get('models',{}).get('image',gemini.DEFAULT_MODELS['image']))
    folder=backends.WORKSPACES;folder.mkdir(parents=True,exist_ok=True)
    internal_id=-secrets.randbits(62)-1
    mode=state.get('orchestrator_mode',False)
    title='Image: '+' '.join(job['prompt'].split())[:100]
    source=state.get('orchestrator-media-reply:'+str(job['id']))
    latest=state.db.execute("SELECT j.id,r.model FROM backend_jobs j JOIN gemini_runs r ON r.job_id=j.id WHERE j.thread_id=? AND j.status='completed' AND r.capability='image' ORDER BY j.created_at DESC LIMIT 1",(source,)).fetchone() if source else None
    current={a['id'] for a in catalog.values() if a['run']==source and latest and a['attempt']==latest['id'] and a.get('media_type','').startswith('image/')}
    if latest and model is None and set(artifact_ids)==current and not reference_ids:
        override=state.db.execute("SELECT model FROM gemini_models WHERE thread_id=? AND capability='image'",(source,)).fetchone()
        selected_model=override[0] if override else latest['model']
    reuse=bool(current and set(artifact_ids)==current and not reference_ids and latest['model']==selected_model)
    if reuse:
        tid=source  # Native history includes these exact current candidate pixels.
    else:
        tid,_,_=backends.create_task(state,shlex.join(['gemini',str(folder),title]),internal_id,
            record_incoming=False,transaction=False)
        for row,path,mime in references:
            gemini.artifact(state,tid,None,'input',path,row['filename'],mime)
    state.db.execute('INSERT OR REPLACE INTO gemini_models VALUES (?,?,?)',(tid,'image',selected_model))
    from task_relay import orchestrator_guides
    prompt=job['prompt']+orchestrator_guides.handoff(state,job)
    captions=[r['filename']+': '+r['caption'] for r,_,_ in references if r['caption']]
    if captions:
        prompt+='\n\nUser-supplied reference captions:\n'+'\n'.join(captions)
    backend_job=backends.enqueue(state,tid,prompt,internal_id,'image',transaction=False)
    state.db.execute('INSERT INTO orchestrator_image_requests VALUES (?,?,?,?)',(job['id'],tid,backend_job,json.dumps(reference_ids)))
    state.put('image-artifact-inputs:'+str(job['id']),frozen)
    for row,_,_ in references:
        if row['run']==UPLOAD_SCOPE:
            state.db.execute("UPDATE production_uploads SET status='used' WHERE id=?",(row['id'],))
    state.put('orchestrator_mode',mode)
    return tid, ('Image generation queued with Gemini · '+selected_model+'.\nReferences: '+(', '.join(r['filename'] for r,_,_ in references) or 'none')+
                 '\nYour original request was sent. The image will arrive on this task; reply normally with your changes to edit the image. Use /gemini for text-only discussion.')
