"""Compiler-owned dependency and evidence closure over exact artifact bindings.

Only already-authorized ancestry is inherited. No source discovery, copying of
facts, version substitution, execution, or acceptance takes place here.
"""
import copy
import hashlib
from pathlib import PurePosixPath


# Native renderers receive prepared data plus registered asset companions.
# Research evidence follows the provenance chain to agent reviewers, not into
# a renderer's single-JSON data port. New adapters register the same metadata.
NATIVE_COMPANIONS={cap:['image/png','image/jpeg','application/zip'] for cap in ('pptx.create','document.compose')}


def capture(operations):
    return {cap:copy.deepcopy(NATIVE_COMPANIONS[cap]) for cap in operations if cap in NATIVE_COMPANIONS}


def validate(captured,operations):
    """Older frozen grants may omit newer companion routes; never backfill them."""
    expected=capture(operations)
    if not isinstance(captured,dict) or any(cap not in expected or media!=expected[cap] for cap,media in captured.items()):
        raise ValueError('Handoff companion metadata differs from the frozen grant')


def inherits_assets(task,via,depth,companions):
    """Native documents need direct assets; reviews retain recursive evidence."""
    cap=task.get('execution',{}).get('capability')
    return not cap or depth==0 and via.get('media_type') not in companions.get(cap,[])


def capture_outputs(operations):
    """Fixed multi-output operations declare one exact execution family.

    Family membership supplies evidence, never semantic equivalence or acceptance.
    Dynamic/unregistered output sets have no implicit peers.
    """
    from .execution import REGISTRY
    return {cap:copy.deepcopy(REGISTRY[cap]['outputs']) for cap in operations
            if len(REGISTRY[cap].get('outputs',{}))>1}


def validate_outputs(captured,operations):
    expected=capture_outputs(operations)
    if not isinstance(captured,dict) or any(cap not in expected or value!=expected[cap] for cap,value in captured.items()):
        raise ValueError('Output family metadata differs from the frozen grant')


def output_peers(task,path,policy):
    """Select only co-outputs declared by this exact registered step."""
    steps=list(task.get('work_tools',{}).get('steps',{}).values())
    if task.get('execution'):
        cap=task['execution']['capability']
        steps.append(dict(operation=cap,outputs={o['path']:o for o in task.get('outputs',[])}))
    for step in steps:
        registered=policy.get(step['operation'])
        if not registered:continue
        mapped=step['outputs']
        if not any(o['path']==path for o in mapped.values()):continue
        if any(p not in mapped or mapped[p].get('media_type')!=m for p,m in registered.items()):
            raise ValueError('Registered output family differs from its producing assignment')
        return [mapped[p] for p in registered if mapped[p]['path']!=path]
    return []


def key(item):
    return ('artifact',item['artifact']) if 'artifact' in item else ('output',item['from_task'],item['output'])


def resolved_key(item,rt,run,pending=()):
    """Resolve a collected current output to its exact registered identity.

    Pending producers keep output identities; equal bytes from different
    producers never establish interchangeability or review acceptance.
    """
    if 'artifact' in item:return key(item)
    if item['from_task'] not in pending:
        try:
            if rt.task(run,item['from_task'])['status']=='completed':
                return ('artifact',rt.output(run,item['from_task'],item['output'])['id'])
        except ValueError:pass
    return key(item)


def add_evidence(task,item,identity=key):
    """Add compiler-owned context without changing any existing path binding."""
    existing=next((i for i in task['inputs'] if identity(i)==identity(item)),None)
    if existing:return existing
    value=copy.deepcopy(item);old=value['path']
    used={i['path'] for i in task['inputs']+task.get('outputs',[])}
    if old in used:
        tag=hashlib.sha256(repr(identity(value)).encode()).hexdigest()
        stem='evidence/'+tag+'/'
        value['path']=stem+PurePosixPath(old).name
        # A bounded set of declared files always has a free deterministic alias.
        for n in range(len(used)+1):
            if value['path'] not in used:break
            value['path']=stem+str(n)+'-'+PurePosixPath(old).name
        value['purpose']='Evidence alias ('+old+'): '+value['purpose']
    task['inputs'].append(value)
    return value


def review_inputs(producer):
    """Reserve current candidate paths before aliasing inherited context."""
    candidates=[dict(from_task=producer['id'],output=o['path'],path='candidate/'+o['path'],
        purpose=o['purpose'],authority='Exact candidate; independent assessment required',
        media_type=o.get('media_type','application/octet-stream')) for o in producer['outputs']]
    used={i['path'] for i in candidates}|{'outputs/review.md'};context=[]
    for item in producer['inputs']:
        value=copy.deepcopy(item)
        if value['path'] in used:
            old=value['path'];tag=hashlib.sha256(repr(key(value)).encode()).hexdigest()[:16]
            value['path']='evidence/'+tag+'/'+PurePosixPath(old).name
            value['purpose']='Evidence alias ('+old+'): '+value['purpose']
        if value['path'] in used:raise ValueError('Ambiguous inherited review evidence path')
        used.add(value['path']);context.append(value)
    return context+candidates


def bind(tasks,lookup,artifact_producer,preserve_paths=lambda task:False,inherit=lambda task,item:True,output_policy=None,
         inherit_ancestry=lambda task,via,depth:True):
    by_id={t['id']:t for t in tasks};done=set();visiting=set()
    def producer(item):
        if 'artifact' in item:return artifact_producer(item['artifact'])
        ident=item['from_task']
        return by_id.get(ident) or lookup(ident)
    def visit(task):
        ident=task['id']
        if ident in done:return
        if ident in visiting:raise ValueError('Cyclic data handoff')
        visiting.add(ident)
        inputs=task.setdefault('inputs',[]);seen={key(i) for i in inputs}
        paths={i['path'] for i in inputs+task.get('outputs',[])}
        inherited=[]
        def add(item,via):
            if not inherit(task,item):return
            if any(key(i)==key(item) and (not preserve_paths(task) or i['path']==item['path']) for i in inputs):return
            value=copy.deepcopy(item)
            if value['path'] in paths:
                if preserve_paths(task):raise ValueError('Required upstream path conflicts with a native input: '+value['path'])
                tag=hashlib.sha256(repr(key(value)).encode()).hexdigest()[:16]
                value['path']='evidence/'+tag+'/'+PurePosixPath(value['path']).name
            if value['path'] in paths:raise ValueError('Evidence binding path collision')
            value['purpose']='Required upstream evidence ('+item['path']+'): '+value['purpose']
            paths.add(value['path']);seen.add(key(value));inputs.append(value)
            inherited.append(dict(source=key(value),path=value['path'],via=key(via)))
        # Traverse exact provenance even when a native intermediate consumes
        # only an asset subset. Reviewers still receive the original evidence.
        walked=set()
        def ancestors(item,depth=0):
            inherits=inherit_ancestry(task,item,depth)
            visit_key=(key(item),inherits)
            if visit_key in walked:return
            walked.add(visit_key)
            upstream=producer(item)
            if not upstream:return
            if upstream['id'] in by_id:visit(upstream)
            peers=upstream.get('companions',[]) if 'artifact' in item else [dict(
                from_task=upstream['id'],output=o['path'],path=o['path'],purpose=o['purpose'],
                authority='Exact registered co-output; independent assessment required',media_type=o['media_type'])
                for o in output_peers(upstream,item['output'],output_policy or {})]
            for peer in peers:
                if inherits:add(peer,item)
                # Peers share this producer's ancestry; do not recursively
                # walk the family and manufacture a cycle between siblings.
            for source in upstream.get('inputs',[]):
                if inherits:add(source,item)
                ancestors(source,depth+1)
        for item in list(inputs):ancestors(item)
        deps=task.setdefault('dependencies',[])
        for item in inputs:
            if 'from_task' in item and item['from_task'] not in deps:deps.append(item['from_task'])
        visiting.remove(ident);done.add(ident)
        receipts.append(dict(task=ident,inherited=inherited,dependencies=list(deps)))
    receipts=[]
    for task in tasks:visit(task)
    return receipts
