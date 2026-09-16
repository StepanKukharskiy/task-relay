"""Approved, bounded correction of data inputs to local document operations."""
import copy
import json
from . import contracts as c


def compile(tasks):
    """Called only while preparing a new Start proposal, never on saved plans."""
    from .execution import REGISTRY
    by_id={t['id']:t for t in tasks}
    for operation in tasks:
        capability=REGISTRY.get(operation.get('execution',{}).get('capability'),{})
        if not capability.get('review_correction'):continue
        inputs=[i for i in operation['inputs'] if i.get('media_type')==capability['review_correction'] and i.get('from_task')]
        if len(inputs)!=1:continue
        author=by_id[inputs[0]['from_task']]
        reviews=[t for t in tasks if t.get('review_of')==author['id']]
        final=[t for t in tasks if t.get('review_of')==operation['id']]
        if (author.get('execution') or author.get('browser') or author.get('review_of') or author.get('user_gate')
                or author['max_attempts']<2 or len(reviews)!=1 or len(final)!=1
                or reviews[0].get('browser') or final[0].get('browser')):continue
        if reviews[0]['id'] not in operation['dependencies']:continue
        operation['review_correction']={'producer':author['id']}
        operation['max_attempts']=2;final[0]['max_attempts']=2
        author['max_attempts']=3;reviews[0]['max_attempts']=3
        for reviewer in (reviews[0],final[0]):
            reviewer['instruction']+='\nFor a correctable candidate defect, return revise with precise changes and evidence so the approved correction loop can run. Use blocked for missing required authority/evidence or unavailable capabilities. An image omission explicitly permitted by the user is not a defect. Never accept an unverified candidate.'


def validate(tasks):
    by_id={t['id']:t for t in tasks}
    for operation in tasks:
        policy=operation.get('review_correction')
        if not policy:continue
        author=by_id.get(policy['producer'],{})
        reviews=[t for t in tasks if t.get('review_of')==author.get('id')]
        final=[t for t in tasks if t.get('review_of')==operation['id']]
        if (not author or author.get('execution') or author.get('browser') or author.get('review_of') or author.get('user_gate')
                or len(reviews)!=1 or len(final)!=1 or reviews[0].get('browser') or final[0].get('browser')
                or author['id'] not in operation['dependencies'] or reviews[0]['id'] not in operation['dependencies']
                or not any(i.get('from_task')==author['id'] and i.get('media_type')=='application/json' for i in operation['inputs'])
                or author['max_attempts']!=3 or reviews[0]['max_attempts']!=3 or final[0]['max_attempts']!=2):
            raise ValueError('Local correction requires a bounded data author, its review, operation and final review.')


def workflow_attempt_limits(tasks):
    """Recognize the same validated local correction graph as execution does."""
    from .execution import validate as validate_operation
    if not any(t.get('review_correction') for t in tasks):return {}
    validate(tasks)
    limits={}
    for operation in tasks:
        policy=operation.get('review_correction')
        if not policy:continue
        validate_operation(copy.deepcopy(operation))
        limits[operation['id']]=2
        limits[policy['producer']]=3
        for task in tasks:
            if task.get('review_of')==policy['producer']:limits[task['id']]=3
            elif task.get('review_of')==operation['id']:limits[task['id']]=2
    return limits


def schedule(rt,run,tid,instruction,source):
    """Inside the receipt transaction. Requeue exact inputs, never dispatch here."""
    task=rt.task(run,tid);spec=rt.spec(task)
    if not spec.get('review_correction'):return False
    if task['status'] not in ('blocked','awaiting_review') or not task['latest']:
        raise ValueError('Automatic correction requires an unaccepted failed or reviewed candidate.')
    c.nonempty(instruction,'Correction instruction')
    all_tasks=[dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))]
    validate([rt.spec(t) for t in all_tasks])
    author=rt.task(run,spec['review_correction']['producer'])
    review=rt.reviewer(run,author['id']);final=rt.reviewer(run,tid)
    group={t['id'] for t in (author,review,task,final)}
    def refuse(reason):
        rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,tid))
        rt.event(run,tid,task['latest'],'correction_limit',{'reason':reason,'instruction':instruction,'source':source})
        return True
    if rt.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0]!='active':return refuse('Workflow is paused or cancelled.')
    if any(t['status'] in ('launching','running','cancelling','uncertain') for t in all_tasks):return refuse('Active or uncertain work prevents correction.')
    if author['status']!='completed' or review['status']!='completed':return refuse('The exact reviewed input is no longer complete.')
    if any(t['attempts']>=rt.spec(t)['max_attempts'] for t in (author,review,task,final)):return refuse('Approved correction allowance exhausted.')
    if any(t['id'] not in group and t['attempts'] and set(rt.spec(t)['dependencies'])&group for t in all_tasks):return refuse('Downstream work has already started.')
    old=rt.db.execute('SELECT frozen,receipt,state FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
    receipt=json.loads(old['receipt'] or '{}');frozen=json.loads(old['frozen'])
    if (receipt.get('status')!='finished' or receipt.get('pending_requests')
            or receipt.get('operation',{}).get('outcome') not in ('completed','failed')):
        return refuse('A confirmed local operation receipt is required.')
    if source=='local_operation_failure:'+task['latest']:
        if receipt['operation']['outcome']!='failed':return refuse('The operation has no confirmed failure.')
    elif source=='model_review:'+str(final['latest']):
        reviewed=rt.db.execute('SELECT frozen,state FROM production_attempts WHERE id=?',(final['latest'],)).fetchone()
        if (not reviewed or reviewed['state']!='completed'
                or json.loads(reviewed['frozen']).get('review_target')!=task['latest']):
            return refuse('The independent review does not target this candidate.')
    else:raise ValueError('An explicit new plan is required outside the approved failure/review correction loop.')
    if any(i.get('from_task')==author['id'] and rt.artifact(i['artifact'])['attempt']!=author['latest'] for i in frozen['inputs']):
        return refuse('The reviewed source version changed.')
    specs={t['id']:copy.deepcopy(rt.spec(t)) for t in (author,review,task,final)}
    authored=specs[author['id']]
    authored['inputs']=[i for i in authored['inputs'] if not i.get('previous_delivery')]
    for previous in (author,final):
        if not previous['latest']:continue
        for artifact in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(previous['latest'],)):
            authored['inputs'].append({'artifact':artifact['id'],'path':'correction/'+previous['id']+'/'+artifact['path'],
                'purpose':'Exact previous draft or independent review for correction','authority':'Unaccepted candidate or review evidence; original request controls scope.',
                'previous_delivery':True})
    for current in (author,review,task,final):
        replacement=specs[current['id']]
        replacement['revision']={'instruction':instruction,'source':source,'previous_attempt':current['latest'],
                                 'kind':'local_document_correction','operation_attempt':task['latest']}
        # Validate all replacements before writing any new assignments.
        specs[current['id']]=c.assignment(replacement)
    for current in (author,review,task,final):
        aid=rt.new_assignment(run,specs[current['id']])
        rt.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,current['id']))
    rt.event(run,tid,task['latest'],'local_correction_scheduled',{'producer':author['id'],'instruction':instruction,'source':source,'attempts_reset':False})
    return True
