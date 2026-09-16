"""Prepare a bounded code-worker recovery; approval uses the shared Start cards."""
import copy,json
from orchestrator import contracts as c,executors
from orchestrator.runtime import file_hash
from . import production_control as pc


def snapshot(state,run,rt,status,task,stage):
    spec=rt.spec(task)
    if spec.get('browser') or spec.get('execution') or spec.get('review_of') or spec.get('tools')!=['files','python']:
        raise ValueError('Request-budget recovery requires a local preparation worker.')
    if any(a['state'] in ('launching','running','cancelling','uncertain') for a in status['attempts']):raise ValueError('Active or uncertain work prevents recovery.')
    attempt=next(a for a in status['attempts'] if a['id']==task['latest'])
    frozen=json.loads(state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(attempt['id'],)).fetchone()[0])
    receipt=json.loads(attempt['receipt'] or '{}')
    if (receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
        or receipt.get('pending_requests') or frozen['backend']['type'] not in executors.CODE_TYPES
        or 'Provider request budget exhausted' not in str(receipt.get('reason',''))):
        raise ValueError('A confirmed request-budget failure without pending effects is required.')
    if task['attempts']>=spec['max_attempts']:raise ValueError('No approved preparation attempt remains; a new plan is required.')
    if any(t['attempts'] and task['id'] in rt.spec(t)['dependencies'] for t in status['tasks']):raise ValueError('Downstream work already started.')
    for item in frozen['inputs']:
        artifact=rt.artifact(item['artifact'])
        if artifact['sha256']!=item['sha256'] or file_hash(artifact['blob'])!=item['sha256']:raise ValueError('Preparation source changed.')
    drafts=[dict(a) for a in state.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(task['latest'],))]
    new=copy.deepcopy(spec)
    requests=min(executors.MAX_EXPLICIT_ROUNDS,spec['limits']['tool_calls'])
    if requests<=executors.request_limit(frozen):raise ValueError('Request limit already reaches the approved tool allowance; revise the plan.')
    new['limits']['provider_requests']=requests
    new['instruction']='Use the existing exact sources and make the requested edits. Batch focused inspection, writing and validation. Save declared outputs early; do not spend the attempt printing whole validators or conversation histories. Prior drafts, if present, are unaccepted inputs under recovery/previous/.\n\n'+new['instruction']
    for artifact in drafts:
        if file_hash(artifact['blob'])!=artifact['sha256']:raise ValueError('Prior draft changed.')
        output=next(o for o in spec['outputs'] if o['path']==artifact['path'])
        new['inputs'].append({'artifact':artifact['id'],'path':'recovery/previous/'+artifact['path'],
            'purpose':'Preserve unreviewed draft from stopped preparation','authority':'Unaccepted previous draft; current request controls changes.',
            **({'media_type':output['media_type']} if output.get('media_type') else {})})
    new['revision']={'kind':'code_budget_recovery','instruction':'Complete the saved task within the newly approved provider request limit.','previous_attempt':task['latest']}
    updates={}
    for following in status['tasks']:
        other=copy.deepcopy(rt.spec(following))
        if following['status']=='queued' and not following['attempts'] and other.get('tools')==['files','python'] and not other.get('execution'):
            limit=min(executors.MAX_EXPLICIT_ROUNDS,other['limits']['tool_calls'])
            if limit>executors.request_limit(other):
                other['limits']['provider_requests']=limit
                updates[following['id']]=c.assignment(other)
    baseline={'budget_updates':updates,'run':run,'tasks':status['tasks'],'attempts':status['attempts'],'drafts':drafts,
        'pipeline_stage':dict(stage) if stage else None,'review_frozen':frozen,'digest':pc.runtime_digest(rt,run),'epoch':state.get('production-control-epoch:'+run,0)}
    return baseline,c.assignment(new)
