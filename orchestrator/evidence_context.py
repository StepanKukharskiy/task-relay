"""Code-owned local evidence context, separate from model-request capacity."""
import math,json,re
from pathlib import PurePosixPath

LOCAL_BYTES = 4000000
INITIAL_BYTES = 96000
BATCH_BYTES = 128000
# Leave room for the frozen assignment, tools, provisional notes and receipts.
# This is a transport ceiling, not an increase in the assigned request budget.
ENVELOPE_BYTES = 96000
ADAPTIVE_INITIAL_BYTES = 16000


def encoded_bytes(text, provider='gemini'):
    value = json.dumps(text, ensure_ascii=False)
    # Responses/chat adapters encode the tool result inside a string field.
    if provider != 'gemini':
        value = json.dumps(value, ensure_ascii=False)
    return len(value.encode('utf-8'))


def literal_descriptor(frozen,item):
    """Only declared text participates in text intervals; assets keep their readers."""
    from . import executors
    return not (item.get('media_type')=='image/png' or PurePosixPath(item['path']).suffix.lower()=='.png'
                or executors.asset_input(frozen,item) or executors.inspection_input(frozen,item))


def literal_input(files,path):
    return literal_descriptor(files.frozen,files.inputs[path])


class EvidenceCapacityError(ValueError):
    """Exact local evidence exceeds the assigned review request allowance."""


def admission_failure(exc):
    """Stable code for confirmed zero-dispatch local capacity failures."""
    if isinstance(exc,EvidenceCapacityError):return dict(version=1,code='evidence_capacity')
    if str(exc)=='API text input pack exceeds 512 KB.':return dict(version=1,code='text_input_capacity')
    return None


def recoverable_admission(event):
    """Read old receipts without rewriting their original failure evidence."""
    failure=event.get('failure')
    if failure is not None:
        return failure in (dict(version=1,code='evidence_capacity'),dict(version=1,code='text_input_capacity'))
    reason=event.get('reason','')
    return (reason=='API text input pack exceeds 512 KB.' or isinstance(reason,str) and
            re.fullmatch(r'Indexed evidence review needs [1-9][0-9]* reads/finalization requests within [1-9][0-9]*; partition the evidence before dispatch\.',reason) is not None)


def bind(rt, run, spec, backend, inputs):
    """Registered saved evidence and indexed typed outputs share this interface."""
    from . import executors, execution
    spec.pop('evidence_context', None)
    if backend['type'] not in executors.FILE_TYPES or spec.get('operation_contract') or not spec.get('review_of'):
        return
    outputs=spec.get('outputs',[])
    if len(outputs)!=1 or PurePosixPath(outputs[0]['path']).suffix.lower() not in ('.md','.txt'):
        return
    target = rt.task(run, spec['review_of'])
    producer = rt.spec(target)
    metadata = execution.REGISTRY.get(producer.get('execution', {}).get('capability'), {}).get('saved_evidence', {})
    candidates = [i for i in inputs if i.get('from_task') == target['id']]
    from .operation_contracts import output_contract,identity
    indexed=[]
    for item in candidates:
        contract=output_contract(producer,item.get('output'))
        if contract and identity(contract).get('file_context',{}).get('mode')=='indexed':
            indexed.append(dict(path=item['path'],contract=contract))
    if (metadata.get('kind') != 'pages' and not indexed) or not target['latest']:
        return
    if not candidates:
        raise ValueError('Saved-page review requires its exact candidate input.')
    literal_inputs=[i for i in inputs if literal_descriptor(spec,i)]
    size = sum(i['bytes'] for i in literal_inputs)
    if size > LOCAL_BYTES:
        raise ValueError('Indexed review evidence exceeds its registered local capacity.')
    # Count serialized literal text, including quotes/backslashes/Unicode.
    provider=executors.provider_for(backend)
    seen={};aliases={};unique=[]
    for item in literal_inputs:
        key=(item['sha256'],item['bytes'])
        if key in seen:aliases[item['path']]=seen[key]
        else:seen[key]=item['path'];unique.append(item)
    encoded_size=sum(encoded_bytes(i['blob'].read_bytes().decode('utf-8'),provider)+512 for i in unique)
    available = min(spec['limits']['tool_calls'],spec['limits'].get('provider_requests',executors.MAX_EXPLICIT_ROUNDS))
    batch_bytes=BATCH_BYTES
    calls = math.ceil(encoded_size / (batch_bytes-4096)) + 1
    if calls>available and available>1:
        needed=math.ceil(encoded_size/(available-1))+4096
        # Small reviews retain their existing interface. Larger reviews use the
        # actual transport capacity instead of treating a preferred page size as
        # a hard ceiling. The exact payload is still checked before every send.
        if needed<=executors.MAX_INPUT_BYTES-ENVELOPE_BYTES:
            batch_bytes=max(batch_bytes,needed)
            calls=math.ceil(encoded_size/(batch_bytes-4096))+1
    # Admission covers the logical review, not only its first invocation. The
    # existing session/controller can carry exact observations into an original
    # remaining attempt. Never count unallocated recovery cycles here.
    from .operation_session import supported
    invocations=spec.get('max_attempts',1) if available>1 and supported(dict(spec,backend=backend)) else 1
    # The last read tool result of a yielded invocation has not reached a model
    # request yet. Its interval must be supplied again, not marked inspected.
    capacity=(available-1)*invocations+1
    if calls>available and invocations>1:
        batch_bytes=max(BATCH_BYTES,executors.MAX_INPUT_BYTES-ENVELOPE_BYTES)
        calls=math.ceil(encoded_size/(batch_bytes-4096))+1
    if calls > capacity:
        raise EvidenceCapacityError('Indexed evidence review needs '+str(calls)+' reads/finalization requests within '+str(capacity)+'; partition the evidence before dispatch.')
    spec['evidence_context'] = dict(version=1, mode='indexed', input_bytes=LOCAL_BYTES,
        initial_bytes=ADAPTIVE_INITIAL_BYTES if batch_bytes>BATCH_BYTES else INITIAL_BYTES,
        batch_bytes=batch_bytes, transport_provider=provider,
        required_requests=calls,provider_requests=available,logical_provider_requests=capacity,
        aliases=aliases,indexed_outputs=indexed,
        producer=target['id'], attempt=target['latest'], assignment=target['assignment'],
        inputs=[{k:i[k] for k in ('artifact','path','sha256','bytes')} for i in inputs])


def aliases(files):
    """Exact byte equivalence permits observation reuse, never semantic acceptance."""
    mapping=files.frozen.get('evidence_context',{}).get('aliases',{})
    if not isinstance(mapping,dict):raise ValueError('Invalid evidence aliases')
    for path,original in mapping.items():
        if (path not in files.inputs or original not in files.inputs or original in mapping or
                files.inputs[path]['sha256']!=files.inputs[original]['sha256']):
            raise ValueError('Evidence alias does not identify exact original bytes')
    return mapping


def equivalent_paths(files,path):
    mapping=aliases(files);original=mapping.get(path,path)
    return [original]+[p for p,source in mapping.items() if source==original]


def next_batch(files, args):
    """Read literal unobserved intervals, across declared files, without replay."""
    if set(args)-{'notes'} or not files.frozen.get('evidence_context'):
        raise ValueError('evidence_next requires its frozen context and optional review notes only.')
    notes=args.get('notes','')
    if not isinstance(notes,str) or len(notes.encode('utf-8'))>2000:
        raise ValueError('Review notes must be at most 2000 UTF-8 bytes.')
    saved=getattr(files,'evidence_notes',[])
    if notes:
        if sum(len(n['notes'].encode('utf-8')) for n in saved)+len(notes.encode('utf-8'))>64000:raise ValueError('Review note capacity exhausted; advance evidence without additional notes.')
        saved.append(dict(notes=notes,inputs=[dict(path=p,sha256=i['sha256'],observed=list(files.observed.get(p,[]))) for p,i in files.inputs.items()]))
    files.evidence_notes=saved
    remaining = files.frozen['evidence_context']['batch_bytes']
    provider=files.frozen['evidence_context'].get('transport_provider','gemini')
    parts = []
    for path in files.input_order():
        if not literal_input(files,path) or path in aliases(files):
            continue
        raw = files.read_bytes(path); text = raw.decode('utf-8')
        observed = sorted(files.observed.get(path, []))
        intervals=[]; start=0
        for a,b in observed:
            if a>start:intervals.append((start,a))
            start=max(start,b)
        if start<len(text):intervals.append((start,len(text)))
        for start,stop in intervals:
            if remaining<=0:break
            # Find the largest literal prefix fitting the serialized response.
            low=0;high=min(stop-start,max(0,remaining-512))
            while low<high:
                mid=(low+high+1)//2
                if encoded_bytes(text[start:start+mid],provider)+512<=remaining:low=mid
                else:high=mid-1
            excerpt=text[start:start+low]
            if not excerpt:break
            end=start+len(excerpt);remaining-=encoded_bytes(excerpt,provider)+512
            files.observe(path,start,end,raw)
            parts.append(dict(path=path,sha256=files.inputs[path]['sha256'],offset=start,end=end,text=excerpt))
        if remaining<=0:break
    return dict(parts=parts,text_bytes=sum(len(p['text'].encode('utf-8')) for p in parts),
                remaining=progress(files),review_notes=[dict(notes=n['notes'],checkpoint=i+1) for i,n in enumerate(saved)],
                aliases=aliases(files),
                authority='Exact saved UTF-8 intervals; aliases identify identical bytes at other frozen paths. Review notes are provisional model observations, not acceptance or verified facts.')


def progress(files):
    result=[]
    for path in files.input_order():
        if not literal_input(files,path):continue
        text=files.read_bytes(path).decode('utf-8');end=0
        if path in aliases(files):continue
        for start,stop in sorted(files.observed.get(path,[])):
            if start>end:break
            end=max(end,stop)
        if end<len(text):result.append(dict(path=path,sha256=files.inputs[path]['sha256'],next_offset=end,characters=len(text)))
    return result
