"""Bind recovery to confirmed append-only descendants within the existing grant.

The registry defines the evidence relation. The compiler verifies exact producer
inputs and committed outputs; neither recency nor byte count confers authority.
This never accepts results, executes a tool, or repairs an uncertain operation.
"""
import json
from pathlib import Path
from . import execution


def pending(session,hook,identifiers,ref,producer):
    path=None
    if 'task' in ref:
        from .owner_intents import ports
        path=ports(producer(ref['task'])).get(ref['output'],{}).get('path')
    for row in session.rt.db.execute("SELECT * FROM production_tasks WHERE run=? AND status IN ('queued','launching','running','waiting','cancelling','uncertain')",(session.run,)):
        spec=session.rt.spec(row)
        caps=([spec['execution']['capability']] if spec.get('execution') else
              [s['operation'] for s in spec.get('work_tools',{}).get('steps',{}).values()])
        if not any(execution.adapter(c).evidence_extension==hook for c in caps):continue
        for item in spec.get('inputs',[]):
            if item.get('artifact') in identifiers or (path and item.get('from_task')==ref['task'] and item.get('output')==path):
                raise ValueError('Evidence recovery is already pending for this lineage; collect its original outcome before selecting another reader')


def committed(rt,artifact):
    """Yield exact registered receipts across standalone and inline execution.

    A stopped worker may retain completed operations, never pending effects or
    an arbitrary authored output. Shared by selection and source admission.
    """
    from .operation_lifecycle import terminal,materialized
    from .operation_execution import Context
    from .runtime import safe_file,file_hash
    row=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
    if not row or row['state'] not in ('completed','blocked','failed'):return
    frozen=json.loads(row['frozen']);control=Path(json.loads(row['session'])['control'])
    sources=[]
    if frozen.get('execution'):
        sources=[(frozen,control,artifact['path'])]
    elif frozen.get('work_tools'):
        from .worker_tools import verify_delivery
        proof=verify_delivery(frozen,control,rt.db,candidate=True)
        for name,version in proof['steps'].items():
            step=frozen['work_tools']['steps'][name]
            for path,output in step['outputs'].items():
                if output['path']!=artifact['path']:continue
                folder=control/'work-operations'/version['version']
                sources.append((json.loads(safe_file(folder,'workspace/.relay/ASSIGNMENT.json').read_text()),folder,path))
    for sub,folder,path in sources:
        workspace=Path(sub['workspace'])
        for i in sub['inputs']:
            if file_hash(safe_file(workspace,i['path']))!=i['sha256']:raise ValueError('Recovery producer input changed')
        receipt=terminal(sub,folder)
        if receipt.get('outcome')!='completed':continue
        materialized(Context(sub,folder,workspace,{},[]),receipt,verify=True)
        if file_hash(safe_file(workspace,path))!=artifact['sha256']:raise ValueError('Recovery candidate differs from committed output')
        yield frozen,sub,receipt


def confirmed(rt,artifact,parent,hook,operations):
    for frozen,sub,receipt in committed(rt,artifact):
        cap=sub['execution']['capability']
        if cap not in operations or execution.adapter(cap).evidence_extension!=hook:continue
        if not any(i['sha256']==parent['sha256'] for i in sub['inputs']):continue
        if not any(i['artifact']==parent['id'] and i['sha256']==parent['sha256'] for i in frozen['inputs']):continue
        return True
    return False


def select(session,cap,ref,producer,*,hook=None,reader=True):
    hook=hook or execution.adapter(cap).evidence_extension
    if not hook:return ref
    if 'artifact' in ref:ident=ref['artifact']
    else:
        # Future producers retain their ordinary dependency binding.
        row=session.rt.db.execute('SELECT latest FROM production_tasks WHERE run=? AND id=?',(session.run,ref['task'])).fetchone()
        if not row or not row['latest']:
            if reader:pending(session,hook,set(),ref,producer)
            return ref
        from .owner_intents import ports
        output=ports(producer(ref['task'])).get(ref['output'])
        if not output:return ref
        found=session.rt.db.execute('SELECT id FROM production_artifacts WHERE attempt=? AND path=?',(row['latest'],output['path'])).fetchone()
        if not found:
            if reader:pending(session,hook,set(),ref,producer)
            return ref
        ident=found['id']
    base,raw=session.artifact(ident)
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):return ref
    if not isinstance(value,dict):return ref
    from .operation_adapters import resolve
    relation=resolve(hook);chain=[];visited={ident}
    candidates=session.rt.db.execute('SELECT * FROM production_artifacts WHERE run=? AND attempt IS NOT NULL ORDER BY id',(session.run,)).fetchall()
    while True:
        successors=[]
        for row in candidates:
            if row['id'] in visited:continue
            # This hook relates JSON evidence ports, not binary deliverables.
            if not row['path'].endswith('.json'):continue
            candidate,data=session.artifact(row['id'])
            try:document=json.loads(data)
            except (ValueError,UnicodeError):continue
            if not isinstance(document,dict) or not relation(value,document):continue
            if confirmed(session.rt,candidate,base,hook,session.grant['operations']):successors.append((candidate,document))
        if not successors:break
        # Divergent confirmed branches require an explicit merge; choosing one
        # would discard evidence. Identical bytes are interchangeable evidence.
        if len({a['sha256'] for a,_ in successors})!=1:
            raise ValueError('Recovery has divergent confirmed evidence; merge the retained branches before continuing')
        base,value=successors[0];visited.add(base['id']);chain.append(dict(artifact=base['id'],sha256=base['sha256']))
    # One continuation of an evidence lineage at a time. Otherwise two readers
    # could consume the same old counters concurrently and both repeat a URL.
    if reader:pending(session,hook,visited,ref,producer)
    if not chain:return ref
    session.rt.event(session.run,session.frozen['id'],session.frozen['assignment_id'],'evidence_recovery_bound',
        dict(operation=cap,requested=ref,original_artifact=ident,selected=base['id'],chain=chain,acceptance=False))
    return dict(artifact=base['id'])
