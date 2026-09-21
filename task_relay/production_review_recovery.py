"""Explicit recovery of exhausted draft reviews without resetting old attempts."""
import copy
import json
from pathlib import Path
import secrets
import time

from orchestrator import contracts as c, worker_capabilities, executors
from orchestrator.runtime import Runtime
from . import production_control as pc, production_planning as planning, production_stages as stages


def prepare(state,run,request,backend=None):
    """Propose the saved graph with one bounded correction and a fresh review.

    No provider is called and no operation is dispatched. Start approves the
    resulting exact sources, bindings and attempt limits in a separate transaction.
    """
    if not state.db.in_transaction:raise ValueError('Recovery requires an atomic transaction.')
    c.nonempty(request,'Exact recovery request')
    channel=getattr(state,'channel','telegram')
    rt=Runtime(pc.root(state),connection=state.db)
    baseline=stages.failed_execution_snapshot(state,rt,run,channel,'review_revision')
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?',(run,)).fetchone():
        raise ValueError('A recovery already exists; use its saved plan.')
    parent=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
    if not parent or parent['channel']!=channel:raise ValueError('Original plan is unavailable.')
    payload=json.loads(parent['context'])
    if c.digest(payload)!=parent['context_hash']:raise ValueError('Original context changed.')
    for source in payload['sources']:planning.verify_artifact(rt,source)
    failed=next(t for t in baseline['tasks'] if t['status']=='blocked')
    reviewer=rt.reviewer(run,failed['id'])
    reason=json.loads(state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='revision_limit' ORDER BY id DESC LIMIT 1",(failed['latest'],)).fetchone()[0])
    result=json.loads(parent['result'])
    options=json.loads(parent['options']);options['max_attempts']=2
    options['local_corrections']=True
    if backend is not None:
        executors.available(backend)
        options.update(backend=copy.deepcopy(backend),tools=executors.validate(backend),executor_locked=True)
        options['limits']=executors.limits_for(backend) if backend['type'] in executors.API_TYPES else options['limits']
    options['worker_catalog']=worker_capabilities.capture(state,options['backend'],options.get('executor_locked',False))
    done={t['id']:t for t in baseline['tasks'] if t['status']=='completed' and t['id']!=reviewer['id']}
    retained=stages.retain_completed_sources(rt,run,payload,options,result,done)
    ident=-int(c.digest({'run':run,'request':request,'backend':backend})[:15],16)-1
    new_id='plan-'+str(ident)
    for task in (failed,reviewer):
        for artifact in state.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(task['latest'],)):
            entry=planning.source_entry(rt,artifact['id'],'recovery/previous/'+task['id']+'/'+artifact['path'],
                'Exact prior draft or review for targeted correction','Historical candidate/review; not accepted output.')
            planning.verify_artifact(rt,entry)
            payload['sources'].append(entry);payload['required_artifacts'].append(entry['artifact'])
    prompt=parent['request']+'\n\n--- EXACT USER RECOVERY REQUEST ---\n'+request
    folder=state.media_dir.parent/'production-planning'/new_id;folder.mkdir(parents=True,exist_ok=True)
    documents={'recovery/REQUEST.txt':prompt}
    if 'pptx.create' in options.get('step_capabilities',[]):
        from orchestrator import pptx_document
        documents['operation-support/pptx.create/validate.py']=pptx_document.validator_source()
    for name,content in documents.items():
        for source in payload['sources']:
            if source['path']==name:source['path']='recovery/history/'+source['artifact']+'/'+Path(name).name
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_text()!=content:raise ValueError('Recovery input changed.')
        path.write_text(content)
        aid=rt.register(path,'Recovery instructions or authoritative validation',run=new_id,path=name)
        payload['sources'].append(planning.source_entry(rt,aid,name,'Recovery instructions or validation','Exact request or service-owned contract.'))
        payload['required_artifacts'].append(aid)
    for task in result['plan']['tasks']:
        if task.get('execution'):continue
        task['max_attempts']=1 if task.get('browser') else 2
        task['instruction']=('Read recovery/REQUEST.txt and recovery/previous/. Correct the existing draft using the saved review: '+
            reason['instruction']+' Preserve unaffected content and exact image bindings. Do not repeat research or media generation. '
            'Review the corrected candidate independently before any downstream operation.\n\n'+task['instruction'])
        if backend is not None:
            required=task.get('worker',{}).get('requires',['files.text','code.execute'])
            task['worker']={'requires':required};task.pop('tools',None)
        if task.get('worker') and not options.get('executor_locked'):
            task['worker'].pop('executor',None)
        for key,limit in options['limits'].items():task['limits'][key]=min(task['limits'][key],limit)
    payload['recovery_origin']={'original_request':parent['request'],'previous_stage':payload.pop('previous_stage',None)}
    payload['execution_recovery']={'kind':'review_revision','baseline':baseline,'request':request,
        'reused_completed_tasks':sorted(done),'completed_deliverables':retained,'review_instruction':reason['instruction']}
    payload['options']=options
    result['message']='Correct the saved draft, independently review it, then resume the unstarted operations.'
    values=dict(parent);values.update(id=new_id,request_id=ident,parent_id=parent['id'],request=prompt,
        options=c.encoded(options),context=c.encoded(payload),context_hash=c.digest(payload),status='ready',calls=0,
        token=secrets.token_hex(12),event_id=None,expires=time.time()+86400,run=None,error=None,created=time.time())
    result,plan=planning.validate_recovery_result(result,values)
    values.update(result=c.encoded(result),plan=c.encoded(plan),plan_hash=c.digest(plan))
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
    state.db.execute('INSERT INTO production_stage_links(parent,plan_id) VALUES (?,?)',(run,new_id))
    stage=state.db.execute("SELECT s.*,p.status AS workflow_status FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline WHERE s.target_kind='plan_production' AND s.target=?",(parent['id'],)).fetchone()
    if stage:
        if stage['workflow_status'] not in ('active','blocked'):raise ValueError('Workflow is paused or cancelled.')
        from . import pipelines
        state.db.execute("UPDATE relay_pipeline_steps SET target=?,status='running',error=NULL WHERE pipeline=? AND id=?",(new_id,stage['pipeline'],stage['id']))
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(stage['pipeline'],))
        pipelines.event(state,stage['pipeline'],stage['id'],'review_correction_planned',{'parent':run,'plan':new_id,'attempts_reset':False})
    current=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
    event=planning.notice(state,current,'ready',planning.preview(current))
    state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,new_id))
    planning.publish_ready_files(state,current,event,rt,plan,payload)
    return new_id
