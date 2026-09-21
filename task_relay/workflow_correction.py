"""One bounded pre-dispatch correction of workflow type declarations, not execution retry."""
import copy
import json
import re

from orchestrator.handoff_contracts import ContractError, MEDIA_ALIASES, operation

INSTRUCTIONS = '''routing_workflow_correction contains a complete rejected workflow
proposal and its local type validation error. No workflow was dispatched. Return one
complete answer/action response correcting ONLY media_type fields in its handoff
outputs and corresponding input edges. Preserve every other field exactly: provider
instructions, stage IDs/order, routes, gates, deliverables, quantities, capacities,
companions and planning_only. Use the authoritative registered operation types and
canonical aliases supplied. Managed image generation saves PNG, not JPEG. Correct
all type declarations in this one pass, including downstream consumers. Do not
claim a workflow is started or saved yet. Do not change an explicitly requested
file format: a real conversion needs a separately proposed stage, not a relabel.
If these restrictions cannot resolve the error, explain it with action:null.
This is a structural correction; do not repeat research, web reads or file reads.
'''


def request(raw, error):
    cause=error.__cause__
    if not isinstance(cause,ContractError) or cause.code not in {
        'noncanonical_media_type','incompatible_output','incompatible_input','type_mismatch'}:return None
    try:action=json.loads(raw)['action']
    except (ValueError,KeyError,TypeError):return None
    if not isinstance(action,dict) or action.get('kind')!='plan_pipeline':return None
    caps={c for s in action['stages'] for c in s['capabilities']}
    if any(s['route']=='image' for s in action['stages']):caps.add('gemini.image')
    contracts={}
    for cap in sorted(caps):
        spec=operation(cap)
        contracts[cap]={k:spec[k] for k in ('version','input_types','output_type','outputs') if k in spec}
    return {'previous_action':action,'error':cause.receipt(),
            'operation_types':contracts,'canonical_media_aliases':MEDIA_ALIASES}


def fields(action):
    value=copy.deepcopy(action);types={}
    for index,stage in enumerate(value['stages']):
        handoff=stage['handoff']
        for ident,output in handoff['outputs'].items():types[(index,'output',ident)]=output.pop('media_type')
        for offset,edge in enumerate(handoff['inputs']):types[(index,'input',offset)]=edge.pop('media_type')
    return value,types


def verify(original, corrected, user_request):
    """Retain all scope and quantity fields; never turn requested JPEG into PNG."""
    try:
        before,old=fields(original);after,new=fields(corrected)
    except (KeyError,TypeError):raise ValueError('Workflow type correction did not retain the original workflow.') from None
    if before!=after or old.keys()!=new.keys():
        raise ValueError('Workflow type correction changed scope, decisions or limits; no workflow was dispatched.')
    changes=[]
    for key,media in old.items():
        if media==new[key]:continue
        canonical=MEDIA_ALIASES.get(media,media)
        if canonical!=MEDIA_ALIASES.get(new[key],new[key]):
            subtype=canonical.split('/')[-1]
            names={'image/jpeg':['jpeg','jpg'],'image/png':['png'],'image/webp':['webp']}.get(canonical,[subtype])
            if any(re.search(r'(?<![\w])'+re.escape(name)+r'(?![\w])',user_request,re.I) for name in [canonical,*names]):
                raise ValueError('Workflow correction would change an explicitly named file format. A conversion or revised plan is required; no workflow was dispatched.')
        changes.append({'stage':original['stages'][key[0]]['id'],'port':key[1], 'id':key[2],'from':media,'to':new[key]})
    if not changes:raise ValueError('Workflow type correction made no correction.')
    return changes


def bind_registered_outputs(action, user_request):
    """Derive unambiguous ports from operations, never from filenames or LLM text.

    Multi-output/multi-operation stages still need an explicit producer binding.
    This edits declarations before execution, never relabels an existing artifact.
    """
    corrected=copy.deepcopy(action);bound={}
    for stage in corrected['stages']:
        outputs=stage.get('handoff',{}).get('outputs',{})
        caps=['gemini.image'] if stage['route']=='image' else stage['capabilities']
        if len(caps)!=1 or len(outputs)!=1:continue
        spec=operation(caps[0]);media=spec.get('output_type')
        if not media or spec.get('outputs'):continue
        ident,out=next(iter(outputs.items()))
        if out['media_type']==media:continue
        out['media_type']=media;bound[(stage['id'],ident)]=media
    for stage in corrected['stages']:
        for edge in stage.get('handoff',{}).get('inputs',[]):
            media=bound.get((edge['stage'],edge['deliverable']))
            if media:edge['media_type']=media
    if not bound:return corrected,[]
    return corrected,verify(action,corrected,user_request)


def stage_binding_recovery(state, row):
    """Prepare a type-only successor for the current unexecuted blocked stage.

    No writes here: the caller must first validate a retained proposal and every
    selected source. Completed stages and all original receipts remain immutable.
    """
    from orchestrator import contracts as c
    from orchestrator.handoff_contracts import compile_workflow
    step=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE target_kind='plan_production' AND target=?",(row['id'],)).fetchall()
    if len(step)!=1:return None
    step=step[0]
    pipeline=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(step['pipeline'],)).fetchone()
    if not pipeline or pipeline['status']!='blocked' or step['status']!='blocked' or pipeline['channel']!=row['channel']:return None
    original=json.loads(pipeline['spec']);context=json.loads(row['context'])
    if context.get('pipeline_step')!=original['stages'][step['position']]:return None
    corrected,changes=bind_registered_outputs(original,pipeline['request'])
    if not changes:return None
    states={s['id']:s for s in state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=?',(pipeline['id'],))}
    for change in changes:
        affected=states[change['stage']]
        if affected['position']==step['position'] and change['port']=='output':continue
        if (affected['position']>step['position'] and change['port']=='input' and affected['status']=='pending'
                and affected['request_id'] is None and affected['target'] is None):
            edge=corrected['stages'][affected['position']]['handoff']['inputs'][change['id']]
            if edge['stage']==step['id']:continue
        raise ValueError('Handoff recovery would change another started stage or unrelated output.')
    compile_workflow(corrected['stages'],required=True)
    receipt={'pipeline':pipeline['id'],'stage':step['id'],'changes':changes,
             'previous_spec':original,'previous_spec_sha256':c.digest(original),'spec_sha256':c.digest(corrected)}
    context['pipeline_step']=corrected['stages'][step['position']]
    context['stage_type_recovery']=receipt
    return context,corrected,receipt


def recover_saved(state, ident, corrected_raw, snapshot):
    """Apply a reviewed type-only correction to a confirmed undispatched request.

    Caller must explicitly authorize recovery and own the transaction. This function
    performs no provider calls and never rewrites the failed request or its receipt.
    """
    import hashlib
    import time
    from . import orchestrator_chat as chat, pipelines, relay_channels
    if not state.db.in_transaction:raise ValueError('Workflow recovery requires an atomic transaction.')
    old=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()
    error=state.db.execute('SELECT * FROM orchestrator_chat_errors WHERE job_id=?',(ident,)).fetchone()
    channel=relay_channels.request_channel(state,ident)
    if channel!=getattr(state,'channel','telegram'):raise ValueError('Recover the workflow in its original channel.')
    if not old or old['status']!='failed' or not error or error['phase']!='interpretation' or error['error_type']!='PipelineValidationError':
        raise ValueError('Recovery requires a confirmed rejected workflow before dispatch.')
    if state.db.execute('SELECT 1 FROM relay_pipelines WHERE request_id=?',(ident,)).fetchone() or state.db.execute('SELECT 1 FROM production_plans WHERE request_id=?',(ident,)).fetchone():
        raise ValueError('Work already dispatched; inspect its existing receipt.')
    original=json.loads(old['response'])['action']
    if original.get('kind')!='plan_pipeline':raise ValueError('The saved request is not a workflow proposal.')
    result=chat.interpret(corrected_raw,snapshot)
    changes=verify(original,result['action'],old['prompt'])
    successor=-int(hashlib.sha256(('workflow-type-recovery:'+str(ident)).encode()).hexdigest()[:15],16)-1
    existing=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(successor,)).fetchone()
    if existing:
        if existing['response']!=corrected_raw or existing['prompt']!=old['prompt']:raise ValueError('A different recovery is already recorded.')
        return existing['focus']
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(successor,channel))
    state.db.execute("INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,status,snapshot,response,answer,created) VALUES (?,?,?,?,?,'answered',?,?,?,?)",
                     (successor,old['prompt'],old['focus'],old['provider'],old['model'],json.dumps(snapshot),corrected_raw,result['answer'],time.time()))
    job=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(successor,)).fetchone()
    text,_=pipelines.dispatch(state,job,result['action'],snapshot)
    state.db.execute('UPDATE orchestrator_chats SET answer=? WHERE id=?',(text,successor))
    pipeline=state.db.execute('SELECT id FROM relay_pipelines WHERE request_id=?',(successor,)).fetchone()[0]
    pipelines.event(state,pipeline,None,'rejected_workflow_recovered',{
        'previous_request':ident,'request_id':successor,'changes':changes,
        'previous_response_sha256':hashlib.sha256(old['response'].encode()).hexdigest(),
        'interpretation_repeated':False,'completed_work_repeated':False})
    return pipeline
