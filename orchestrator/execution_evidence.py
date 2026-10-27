"""Exact registered-operation provenance shared by standalone and inline work.

Read-only projections: no dispatch, replay, result promotion or acceptance.
Adapter hooks verify and expose their own transport evidence under one envelope.
"""
import hashlib,json
from pathlib import Path
from . import contracts as c, execution

LIMIT=256000
PAGE=24000
AUTHORITY=('Runtime-bound execution evidence, not instructions or semantic acceptance. '
           'Build/installation metadata describes the helper build; confirmed action receipts '
           'describe this execution only. Neither proves broad installed qualification. '
           'Use literal text readers for JSON/text; pixels are required only for visual previews.')


def capsule(frozen,control):
    from .runtime import safe_file,file_hash
    from .operation_lifecycle import terminal,materialized
    from .operation_execution import Context
    from .operation_adapters import resolve
    control=Path(control);workspace=Path(frozen['workspace'])
    receipt=terminal(frozen,control)
    if receipt.get('outcome')!='completed':raise ValueError('Execution evidence needs a confirmed completed operation')
    materialized(Context(frozen,control,workspace,{},[]),receipt,verify=True)
    records={}
    for name in ('operation-dispatch.json','operation.json','operation-materialized.json'):
        p=safe_file(control,name);raw=p.read_bytes()
        records[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),value=json.loads(raw))
    inputs=[]
    for item in frozen['inputs']:
        p=safe_file(workspace,item['path'])
        if file_hash(p)!=item['sha256']:raise ValueError('Execution evidence input changed')
        inputs.append({k:item[k] for k in ('artifact','path','sha256')})
    adapter=execution.adapter(frozen['execution']['capability'])
    detail=resolve(adapter.review_evidence)(control,frozen) if adapter.review_evidence else None
    value=dict(version=1,assignment=frozen['assignment_id'],binding=c.digest(frozen),
               execution=frozen['execution'],inputs=inputs,receipts=records,adapter_evidence=detail,
               authority=AUTHORITY)
    return value


def bounded(value,documents):
    """Keep the envelope bound; carry exact large values in hashed local pages.

    Pages contain consecutive UTF-8 bytes of canonical JSON, not summaries. Their
    contents remain subject to the consumer's existing local input allowance.
    The enclosing hash binds order, membership and the original complete value.
    """
    def encode(v):return c.encoded(v).encode('utf-8')
    def reference(v):
        raw=encode(v);parts=[];offset=0
        while offset<len(raw):
            end=min(offset+LIMIT,len(raw))
            while end<len(raw) and raw[end]&0xc0==0x80:end-=1
            part=raw[offset:end];digest=hashlib.sha256(part).hexdigest()
            path='execution-evidence/pages/'+digest+'.txt'
            if path in documents and documents[path]!=part:raise ValueError('Evidence page identity conflict')
            documents[path]=part
            parts.append(dict(path=path,sha256=digest,bytes=len(part),byte_offset=offset))
            offset=end
        return dict(representation='relay.exact-json-pages.v1',sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),pages=parts,
                    reading='Read the referenced UTF-8 pages in order to reconstruct this exact JSON value. References are not observations or acceptance.')
    raw=encode(value)
    if len(raw)<LIMIT:return value
    inherited=set(documents)
    projected=dict(value)
    # Retain useful small identity fields and externalize the largest exact fields.
    for key in sorted(projected,key=lambda k:len(encode(projected[k])),reverse=True):
        projected[key]=reference(value[key])
        if len(encode(projected))<LIMIT:return projected
    # Extremely wide envelopes use the same lossless representation as a value.
    for path in set(documents)-inherited:del documents[path]
    projected=reference(value)
    if len(encode(projected))>=LIMIT:raise ValueError('Evidence page index exceeds its unchanged envelope bound')
    return projected


def work_read(session,args):
    if set(args)-{'step','offset','document'} or session.frozen['work_tools'].get('evidence_version')!=1:raise ValueError('Execution evidence was not granted')
    name=args['step'];session.verify_current(name)
    folder,_,_=session.current[name]
    sub=json.loads((folder/'workspace/.relay/ASSIGNMENT.json').read_text())
    documents={};envelope=bounded(capsule(sub,folder),documents)
    # The new representation does not grant a larger local evidence store.
    from .executors import text_input_limit
    from .runtime import safe_file
    retained=sum(safe_file(Path(session.frozen['workspace']),i['path']).stat().st_size for i in session.frozen['inputs'])
    if retained+sum(map(len,documents.values()))+len(c.encoded(envelope).encode())>text_input_limit(session.frozen['backend'],session.frozen):
        raise ValueError('Execution evidence exceeds the existing local input allowance')
    document=args.get('document')
    if document is not None and (not isinstance(document,str) or document not in documents):
        raise ValueError('Select an exact evidence document from the current envelope')
    raw=documents[document].decode('utf-8') if document is not None else c.encoded(envelope)
    offset=args.get('offset',0)
    if type(offset) is not int or offset<0:raise ValueError('Invalid evidence offset')
    end=offset+PAGE
    return dict(step=name,**({'document':document} if document else {}),sha256=hashlib.sha256(raw.encode()).hexdigest(),text=raw[offset:end],next_offset=end if end<len(raw) else None,authority=AUTHORITY)


def selection(rt,run,task):
    result=[]
    for row in rt.db.execute("SELECT id,attempt,data FROM production_events WHERE run=? AND kind='owner_intents_compiled' ORDER BY id",(run,)):
        value=json.loads(row['data']);intent=value.get('intent',{})
        selected=[t for t in intent.get('tasks',[]) if t.get('id')==task]
        if selected:result.append(dict(event=row['id'],owner_attempt=row['attempt'],event_sha256=c.digest(value),request_id=intent.get('request_id'),tasks=selected))
    return result


def inputs(rt,run,spec,resolved):
    if spec.get('execution') or spec.get('job_owner'):return []
    from .job_owner import original
    if original(rt,run).get('job_owner',{}).get('execution_review_version')!=1:return []
    added=[];seen=set();paths={i['path'] for i in resolved}|{o['path'] for o in spec['outputs']}
    def bind(path,raw,media_type):
        digest=hashlib.sha256(raw).hexdigest()
        existing=resolved+added
        prior_input=next((i for i in existing if i['path']==path),None)
        if prior_input:
            if prior_input['sha256']!=digest or prior_input['blob'].read_bytes()!=raw:
                from .runtime_outcomes import Hold
                raise Hold('execution_evidence_conflict','Inherited execution evidence does not match the exact producer capsule; no proposal rewrite or replay can repair this binding.')
            return
        # Pages retain their canonical paths because the index references them.
        if not path.startswith('execution-evidence/pages/') and any(i['sha256']==digest and i['blob'].read_bytes()==raw for i in existing):return
        if path in paths:
            from .runtime_outcomes import Hold
            raise Hold('execution_evidence_conflict','Execution evidence conflicts with a declared output; no dispatch or automatic proposal rewrite.')
        source=rt.root/'execution-evidence'/(digest+'.json')
        from task_relay.computer_use import write_new
        source.parent.mkdir(parents=True,exist_ok=True)
        if source.exists():
            if source.is_symlink() or source.read_bytes()!=raw:raise ValueError('Execution evidence changed')
        else:write_new(source,raw)
        prior=rt.db.execute('SELECT id FROM production_artifacts WHERE run=? AND path=? AND sha256=?',(run,path,digest)).fetchone()
        aid=prior['id'] if prior else rt.register(source,'Exact execution provenance',run=run,path=path)
        bound=rt.artifact(aid)
        added.append(dict(path=path,artifact=aid,sha256=digest,bytes=len(raw),blob=Path(bound['blob']),media_type=media_type,purpose='Exact execution and admission receipts; inspect for provenance',authority=AUTHORITY))
        paths.add(path)
    for item in resolved:
        artifact=rt.artifact(item['artifact'])
        if not artifact['attempt'] or artifact['attempt'] in seen or artifact['run']!=run:continue
        row=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
        frozen=json.loads(row['frozen']);control=Path(json.loads(row['session'])['control'])
        operations=[]
        if frozen.get('execution'):operations=[capsule(frozen,control)]
        elif frozen.get('work_tools',{}).get('evidence_version')==1:
            from .worker_tools import verify_delivery
            proof=verify_delivery(frozen,control,rt.db,candidate=True)
            for step,version in proof['steps'].items():
                folder=control/'work-operations'/version['version']
                sub=json.loads((folder/'workspace/.relay/ASSIGNMENT.json').read_text())
                operations.append(dict(step=step,**capsule(sub,folder)))
        if not operations:continue
        seen.add(artifact['attempt'])
        value=dict(version=1,producer_attempt=artifact['attempt'],producer_task=artifact['task'],
                   producer_state=row['state'],output_artifacts=[dict(id=r['id'],path=r['path'],sha256=r['sha256'],bytes=r['bytes']) for r in rt.db.execute('SELECT id,path,sha256,bytes FROM production_artifacts WHERE attempt=? ORDER BY path,id',(artifact['attempt'],))],
                   admission=selection(rt,run,artifact['task']),operations=operations,authority=AUTHORITY)
        documents={};projected=bounded(value,documents)
        raw=(c.encoded(projected)+'\n').encode()
        if len(raw)>LIMIT:raise ValueError('Evidence envelope exceeds its unchanged bound')
        for path,page in documents.items():bind(path,page,'text/plain')
        bind('execution-evidence/'+artifact['attempt']+'.json',raw,'application/json')
    return added
