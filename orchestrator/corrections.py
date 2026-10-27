"""Approved, bounded correction of data inputs to local document operations."""
import copy
import json
from . import contracts as c


def layout_task(task):
    from .execution import REGISTRY
    return REGISTRY.get(task.get('execution',{}).get('capability'),{}).get('native_adapter')=='record-slides'


def compile(tasks,*,sourcing_layout=False,reserve=False,record_layout=False):
    """Called only while preparing a new Start proposal, never on saved plans."""
    sourcing_layout=sourcing_layout or record_layout
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
        if reserve and len(reviews)==len(final)==1 and all(not t.get('user_gate') and not t.get('browser') and not t.get('computer') for t in (author,reviews[0],operation,final[0])):
            if not author.get('execution') or sourcing_layout and layout_task(author):
                for actor in (author,reviews[0],final[0]):actor['max_attempts']=max(2,actor['max_attempts'])
        if (sourcing_layout and layout_task(author) and operation['execution']['capability']=='pptx.create'
                and len(reviews)==len(final)==1 and reviews[0]['id'] in operation['dependencies']
                and all(t['max_attempts']>=2 for t in (reviews[0],final[0]))
                and all(not t.get('user_gate') and not t.get('browser') for t in (author,reviews[0],operation,final[0]))):
            operation['review_correction']={'producer':author['id'],'kind':'sourcing_layout'}
            operation['max_attempts']=author['max_attempts']=2
            for helper in tasks:
                if helper.get('execution',{}).get('capability')=='pptx.render' and operation['id'] in helper['dependencies']:helper['max_attempts']=2
            final[0]['instruction']+='\nA revise decision can request one code-owned readable-layout correction within existing attempt limits. This changes no source facts or images; unresolved factual defects must be reported honestly.'
            for reviewer in (reviews[0],final[0]):
                reviewer['instruction']+='\nThe native correction changes only layout. For observed clipping or unreadable text that a roomier layout can resolve, use category requirements and code layout_readability. Content, source and factual findings retain their own codes and need semantic correction. Subjective taste remains quality; do not turn it into a technical layout finding.'
            continue
        if (author.get('execution') or author.get('browser') or author.get('review_of') or author.get('user_gate')
                or author['max_attempts']<2 or len(reviews)!=1 or len(final)!=1
                or reviews[0].get('browser') or final[0].get('browser')):continue
        if reviews[0]['id'] not in operation['dependencies']:continue
        operation['review_correction']={'producer':author['id']}
        operation['max_attempts']=2;final[0]['max_attempts']=2
        author['max_attempts']=3;reviews[0]['max_attempts']=3
        for helper in tasks:
            if helper.get('execution',{}).get('capability')=='pptx.render' and operation['id'] in helper['dependencies']:helper['max_attempts']=2
        for reviewer in (reviews[0],final[0]):
            reviewer['instruction']+='\nFor a correctable candidate defect, return revise with precise changes and evidence so the approved correction loop can run. Use blocked for missing required authority/evidence or unavailable capabilities. An image omission explicitly permitted by the user is not a defect. Never accept an unverified candidate.'


def validate(tasks):
    by_id={t['id']:t for t in tasks}
    for operation in tasks:
        policy=operation.get('review_correction')
        if not policy:continue
        for helper in tasks:
            if helper.get('execution',{}).get('capability')=='pptx.render' and operation['id'] in helper['dependencies'] and helper['max_attempts']!=2:raise ValueError('Presentation correction requires two exact-candidate preview attempts')
        author=by_id.get(policy['producer'],{})
        reviews=[t for t in tasks if t.get('review_of')==author.get('id')]
        final=[t for t in tasks if t.get('review_of')==operation['id']]
        if policy.get('kind')=='sourcing_layout':
            if (not layout_task(author) or operation.get('execution',{}).get('capability')!='pptx.create'
                    or len(reviews)!=1 or len(final)!=1 or reviews[0]['id'] not in operation['dependencies'] or author['id'] not in operation['dependencies']
                    or any(t['max_attempts']<2 or t.get('user_gate') or t.get('browser') for t in (author,reviews[0],operation,final[0]))):raise ValueError('Native sourcing correction needs an existing two-attempt reviewed assembly/deck grant')
            continue
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
        for helper in tasks:
            if helper.get('execution',{}).get('capability')=='pptx.render' and operation['id'] in helper['dependencies']:limits[helper['id']]=helper['max_attempts']
        validate_operation(copy.deepcopy(operation))
        if policy.get('kind')=='sourcing_layout':
            for t in tasks:
                if t['id'] in (operation['id'],policy['producer']) or t.get('review_of') in (operation['id'],policy['producer']):limits[t['id']]=t['max_attempts']
            continue
        limits[operation['id']]=2
        limits[policy['producer']]=3
        for task in tasks:
            if task.get('review_of')==policy['producer']:limits[task['id']]=3
            elif task.get('review_of')==operation['id']:limits[task['id']]=2
    return limits


def authorized_layout(db,run,spec,original):
    """Prove the single preset change already granted by the frozen graph."""
    revision=spec.get('revision',{})
    if (revision.get('kind')!='native_sourcing_layout'
            or not layout_task(original)):
        return False
    expected=copy.deepcopy(original['execution']);expected['parameters']['layout']='readable'
    if (original['execution']['parameters']['layout']!='standard'
            or spec.get('execution')!=expected):return False
    graph=json.loads(db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    operation=next((t for t in graph['tasks'] if t.get('review_correction')==dict(producer=spec['id'],kind='sourcing_layout')),None)
    if not operation:return False
    before=db.execute('SELECT * FROM production_attempts WHERE id=?',(revision.get('previous_attempt'),)).fetchone()
    if not before or before['run']!=run or before['task']!=spec['id'] or before['state']!='completed':return False
    old=json.loads(before['frozen']);receipt=json.loads(before['receipt'] or '{}')
    if (old.get('execution')!=original['execution'] or receipt.get('status')!='finished'
            or receipt.get('pending_requests') or receipt.get('operation',{}).get('outcome')!='completed'):return False
    source=revision.get('source','')
    if not source.startswith('model_review:'):return False
    review=db.execute('SELECT * FROM production_attempts WHERE id=?',(source[len('model_review:'):],)).fetchone()
    if not review or review['run']!=run or review['state']!='completed':return False
    rf=json.loads(review['frozen']);rr=json.loads(review['receipt'] or '{}')
    target=revision.get('operation_attempt',revision['previous_attempt'])
    reviewed=operation['id'] if 'operation_attempt' in revision else spec['id']
    if (rf.get('review_of')!=reviewed or rf.get('review_target')!=target
            or rr.get('status')!='finished' or rr.get('pending_requests') or rr.get('exit_code')):return False
    kind='native_sourcing_correction_scheduled' if 'operation_attempt' in revision else 'native_specification_correction_scheduled'
    event=db.execute('SELECT data FROM production_events WHERE run=? AND kind=? ORDER BY id DESC LIMIT 1',(run,kind)).fetchone()
    if not event:return False
    detail=json.loads(event[0])
    if (detail.get('layout')!='readable' or detail.get('source')!=source
            or detail.get('instruction')!=revision.get('instruction') or detail.get('attempts_reset') is not False):return False
    report=db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(review['id'],)).fetchall()
    return any((v:=json.loads(r[0])).get('kind')=='model_review' and v.get('result',{}).get('decision')=='revise' for r in report)


def schedule(rt,run,tid,instruction,source):
    """Inside the receipt transaction. Requeue exact inputs, never dispatch here."""
    task=rt.task(run,tid);spec=rt.spec(task)
    if not spec.get('review_correction'):return False
    if spec['review_correction'].get('kind')=='sourcing_layout':
        return schedule_sourcing(rt,run,task,spec,instruction,source)
    if task['status'] not in ('blocked','awaiting_review') or not task['latest']:
        raise ValueError('Automatic correction requires an unaccepted failed or reviewed candidate.')
    c.nonempty(instruction,'Correction instruction')
    all_tasks=[dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))]
    validate([rt.spec(t) for t in all_tasks])
    author=rt.task(run,spec['review_correction']['producer'])
    review=rt.reviewer(run,author['id']);final=rt.reviewer(run,tid)
    helpers=[t for t in all_tasks if rt.spec(t).get('execution',{}).get('capability')=='pptx.render' and tid in rt.spec(t)['dependencies']]
    correction_group=[author,review,task,final]+helpers
    group={t['id'] for t in correction_group}
    def refuse(reason):
        rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,tid))
        rt.event(run,tid,task['latest'],'correction_limit',{'reason':reason,'instruction':instruction,'source':source})
        return True
    if rt.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0]!='active':return refuse('Workflow is paused or cancelled.')
    if any(t['status'] in ('launching','running','cancelling','uncertain') for t in all_tasks):return refuse('Active or uncertain work prevents correction.')
    if author['status']!='completed' or review['status']!='completed':return refuse('The exact reviewed input is no longer complete.')
    if any(t['attempts']>=rt.spec(t)['max_attempts'] for t in correction_group):return refuse('Approved correction allowance exhausted.')
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
    specs={t['id']:copy.deepcopy(rt.spec(t)) for t in correction_group}
    authored=specs[author['id']]
    authored['inputs']=[i for i in authored['inputs'] if not i.get('previous_delivery')]
    for previous in (author,final):
        if not previous['latest']:continue
        for artifact in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(previous['latest'],)):
            authored['inputs'].append({'artifact':artifact['id'],'path':'correction/'+previous['id']+'/'+artifact['path'],
                'purpose':'Exact previous draft or independent review for correction','authority':'Unaccepted candidate or review evidence; original request controls scope.',
                'previous_delivery':True})
    for current in correction_group:
        replacement=specs[current['id']]
        replacement['revision']={'instruction':instruction,'source':source,'previous_attempt':current['latest'],
                                 'kind':'local_document_correction','operation_attempt':task['latest']}
        # Validate all replacements before writing any new assignments.
        specs[current['id']]=c.assignment(replacement)
    for current in correction_group:
        aid=rt.new_assignment(run,specs[current['id']],fresh_review=bool(specs[current['id']].get('review_of')))
        rt.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,current['id']))
    rt.event(run,tid,task['latest'],'local_correction_scheduled',{'producer':author['id'],'instruction':instruction,'source':source,'attempts_reset':False})
    return True


def specification_policy(rt,run,tid):
    """A native spec can use only its downstream frozen layout correction."""
    for task in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)):
        policy=rt.spec(task).get('review_correction',{})
        if policy==dict(producer=tid,kind='sourcing_layout') and task['attempts']==0:return task['id']
    return None


def layout_findings(db, source):
    """A deterministic layout preset cannot repair content or evidence defects."""
    if not source.startswith('model_review:'):return False
    attempt=source[len('model_review:'):]
    for row in db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(attempt,)):
        event=json.loads(row[0])
        if event.get('kind')!='model_review':continue
        result=event.get('result',{});findings=result.get('findings',[])
        def repairable(f):return f.get('category')=='requirements' and f.get('code')=='layout_readability'
        return (result.get('decision')=='revise' and any(repairable(f) for f in findings)
                and all(repairable(f) or f.get('category')=='advisory' for f in findings))
    return False


def schedule_specification(rt,run,tid,instruction,source):
    operation=specification_policy(rt,run,tid)
    if not operation or not layout_findings(rt.db,source):return False
    task=rt.task(run,tid);review=rt.reviewer(run,tid);spec=copy.deepcopy(rt.spec(task))
    if (task['status']!='awaiting_review' or not layout_task(spec)
            or spec['execution']['parameters']['layout']!='standard' or not review
            or task['attempts']>=spec['max_attempts'] or review['attempts']>=rt.spec(review)['max_attempts']
            or source!='model_review:'+str(review['latest'])):return False
    attempt=rt.db.execute('SELECT state,frozen FROM production_attempts WHERE id=?',(review['latest'],)).fetchone()
    if not attempt or attempt['state']!='completed' or json.loads(attempt['frozen']).get('review_target')!=task['latest']:return False
    if any(t['id'] not in (tid,review['id']) and t['attempts'] and tid in rt.spec(t)['dependencies'] for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))):return False
    spec['execution']['parameters']['layout']='readable'
    replacements=[]
    for current,value in ((task,spec),(review,copy.deepcopy(rt.spec(review)))):
        value['revision']=dict(instruction=instruction,source=source,previous_attempt=current['latest'],kind='native_sourcing_layout',operation=operation)
        replacements.append((current,c.assignment(value)))
    for current,value in replacements:
        aid=rt.new_assignment(run,value,fresh_review=bool(value.get('review_of')))
        rt.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,current['id']))
    rt.event(run,tid,task['latest'],'native_specification_correction_scheduled',dict(layout='readable',instruction=instruction,source=source,attempts_reset=False))
    return True


def schedule_sourcing(rt,run,task,spec,instruction,source):
    """One deterministic layout correction; facts and photo versions stay fixed."""
    c.nonempty(instruction,'Sourcing layout correction')
    tasks=[dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))]
    validate([rt.spec(t) for t in tasks])
    author=rt.task(run,spec['review_correction']['producer']);review=rt.reviewer(run,author['id']);final=rt.reviewer(run,task['id'])
    helpers=[t for t in tasks if rt.spec(t).get('execution',{}).get('capability')=='pptx.render' and task['id'] in rt.spec(t)['dependencies']]
    group=[author,review,task,final]+helpers;ids={t['id'] for t in group}
    def refuse(reason):
        rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
        rt.event(run,task['id'],task['latest'],'correction_limit',dict(reason=reason,instruction=instruction,source=source));return True
    if not layout_findings(rt.db,source):return refuse('Layout correction cannot resolve the reported content or evidence findings')
    if rt.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0]!='active':return refuse('Workflow is paused or cancelled')
    if any(t['status'] in ('launching','running','cancelling','uncertain') for t in tasks):return refuse('Active or uncertain work prevents correction')
    if task['status'] not in ('awaiting_review','blocked') or author['status']!='completed' or review['status']!='completed':return refuse('Exact reviewed assembly is no longer current')
    if any(t['attempts']>=rt.spec(t)['max_attempts'] for t in group):return refuse('Existing attempt grant exhausted')
    if any(t['id'] not in ids and t['attempts'] and ids.intersection(rt.spec(t)['dependencies']) for t in tasks):return refuse('Downstream work already started')
    if source!='model_review:'+str(final['latest']):return refuse('Native layout correction requires exact independent final review')
    final_attempt=rt.db.execute('SELECT state,frozen FROM production_attempts WHERE id=?',(final['latest'],)).fetchone()
    if not final_attempt or final_attempt['state']!='completed' or json.loads(final_attempt['frozen']).get('review_target')!=task['latest']:return refuse('Stale final review')
    specs={t['id']:copy.deepcopy(rt.spec(t)) for t in group}
    authored=specs[author['id']]
    if authored['execution']['parameters']['layout']!='standard':return refuse('Readable layout was already tried; retain the unresolved finding')
    for producer in (author,task):
        a=rt.db.execute('SELECT receipt,state FROM production_attempts WHERE id=?',(producer['latest'],)).fetchone();receipt=json.loads(a['receipt'] or '{}')
        if a['state']!='completed' or receipt.get('status')!='finished' or receipt.get('pending_requests') or receipt.get('operation',{}).get('outcome')!='completed':return refuse('Confirmed native operation receipt required')
    authored['execution']['parameters']['layout']='readable'
    for t in group:
        replacement=specs[t['id']];replacement['revision']=dict(instruction=instruction,source=source,previous_attempt=t['latest'],kind='native_sourcing_layout',operation_attempt=task['latest'])
        specs[t['id']]=c.assignment(replacement)
    for t in group:
        aid=rt.new_assignment(run,specs[t['id']],fresh_review=bool(specs[t['id']].get('review_of')));rt.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,t['id']))
    rt.event(run,task['id'],task['latest'],'native_sourcing_correction_scheduled',dict(producer=author['id'],layout='readable',instruction=instruction,source=source,attempts_reset=False))
    return True
