"""Propose browser setup repairs from confirmed read-only failures; never replay."""
import copy
import json
import secrets
import time

from orchestrator import contracts as c
from orchestrator.browser_contract import validate as validate_browser
from orchestrator.runtime import Runtime
from . import production_control as pc, production_planning as planning, production_stages as stages


def prepare_startup(state,run,request):
    """An explicit Continue may recover a confirmed pre-action Chrome timeout."""
    rt=Runtime(pc.root(state),connection=state.db)
    status=rt.status(run)
    failed=[t for t in status['tasks'] if t['status']=='blocked']
    if status['status']!='blocked' or len(failed)!=1 or not rt.spec(failed[0]).get('browser'):return None
    attempt=next(a for a in status['attempts'] if a['id']==failed[0]['latest'])
    receipt=json.loads(attempt['receipt'] or '{}')
    if (receipt.get('api_requests')!=0 or receipt.get('tool_calls')!=0
            or receipt.get('browser',{}).get('actions')!=[]
            or not str(receipt.get('reason','')).startswith((
                'ValueError: Chrome did not finish opening.',
                'ValueError: Chrome did not publish a verified connection within the startup limit.'))):return None
    existing=state.db.execute('SELECT plan_id FROM production_stage_links WHERE parent=?',(run,)).fetchone()
    if existing:return existing['plan_id']
    parent=state.db.execute('SELECT result FROM production_plans WHERE run=?',(run,)).fetchone()
    if not parent:raise ValueError('Original browser plan unavailable.')
    done={t['id'] for t in status['tasks'] if t['status']=='completed'}
    policies={t['id']:t['browser'] for t in json.loads(parent['result'])['plan']['tasks'] if t.get('browser') and t['id'] not in done}
    return prepare(state,run,request,policies)


def prepare_code(state,run,request):
    """Explicit Start after confirmed request exhaustion or generation truncation."""
    existing=state.db.execute('SELECT plan_id FROM production_stage_links WHERE parent=?',(run,)).fetchone()
    if existing:return existing['plan_id']
    rt=Runtime(pc.root(state),connection=state.db)
    policies={t['id']:rt.spec(t)['browser'] for t in rt.status(run)['tasks']
              if t['status']!='completed' and rt.spec(t).get('browser')}
    return prepare(state,run,request,policies,kind='code_budget')


def prepare(state,run,request,policies,*,kind='browser_setup'):
    if not state.db.in_transaction:raise ValueError('Recovery requires an atomic transaction.')
    c.nonempty(request,'Exact recovery request')
    rt=Runtime(pc.root(state),connection=state.db);channel=getattr(state,'channel','telegram')
    if kind not in ('browser_setup','code_budget'):raise ValueError('Unsupported recovery kind.')
    baseline=stages.failed_execution_snapshot(state,rt,run,channel,kind)
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?',(run,)).fetchone():
        raise ValueError('A recovery already exists; use its saved proposal.')
    parent=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
    if not parent or parent['channel']!=channel:raise ValueError('Original plan unavailable.')
    payload=json.loads(parent['context']);options=json.loads(parent['options'])
    if c.digest(payload)!=parent['context_hash']:raise ValueError('Original context changed.')
    for source in payload['sources']:planning.verify_artifact(rt,source)
    result=json.loads(parent['result']);tasks=result['plan']['tasks']
    done={t['id']:t for t in baseline['tasks'] if t['status']=='completed'}
    tasks=result['plan']['tasks']=[t for t in tasks if t['id'] not in done]
    if kind=='code_budget':
        options['max_attempts']=2
        options['local_corrections']=True
        options['response_budgets']=True
        # Preserve the latest approved bounds, including prior delivered repair
        # cards, rather than reverting to the original planner's limits.
        for task in tasks:
            current=rt.spec(rt.task(run,task['id']))
            task['limits']=copy.deepcopy(current['limits'])
            if task['id'] in {t['id'] for t in baseline['tasks'] if t['status']=='blocked'} and task.get('tools')==['files','python']:
                from orchestrator import executors
                task['limits']['response_tokens']=executors.MAX_RESPONSE_TOKENS
            task['max_attempts']=1 if task.get('execution') or task.get('browser') else 2
            task['instruction']='Save a draft after focused inspection, then validate and correct it. Do not repeat completed research or image collection.\n\n'+task['instruction']
        from .presentation_inputs import restore_selected_images
        restore_selected_images(rt,payload,tasks)
        failed=next(t for t in baseline['tasks'] if t['status']=='blocked')
        for artifact in state.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(failed['latest'],)):
            source=planning.source_entry(rt,artifact['id'],'recovery/previous/'+failed['latest']+'/'+failed['id']+'/'+artifact['path'],
                'Exact unreviewed draft from stopped preparation','Historical unaccepted draft; current request controls corrections.')
            planning.verify_artifact(rt,source)
            payload['sources'].append(source);payload['required_artifacts'].append(source['artifact'])
    browser_ids={t['id'] for t in tasks if t.get('browser')}
    if not isinstance(policies,dict) or set(policies)!=browser_ids:
        raise ValueError('Specify each browser producer/reviewer policy for the new proposal.')
    for task in tasks:
        if task['id'] in policies:
            policy=copy.deepcopy(policies[task['id']]);validate_browser(policy)
            old=task['browser']
            if any(policy.get(k)!=old.get(k) for k in set(old)|set(policy) if k not in ('profile','origins','session_source')):
                raise ValueError('Setup repair may change only profile, session source and exact origins; preserve actions and capture grants.')
            task['browser']=policy
        if task.get('execution',{}).get('capability')=='images.collect':task['inputs']=[]
    retained=stages.retain_completed_sources(rt,run,payload,options,result,done)
    payload['options']=options
    ident=-int(c.digest({kind:run,'request':request,'policies':policies})[:15],16)-1
    new_id='plan-'+str(ident)
    if kind=='code_budget':
        from pathlib import Path
        from .production_feedback import collect
        feedback={'current_request':request,'history':collect(state,run)}
        name='recovery/'+new_id+'/USER_FEEDBACK.json'
        path=state.media_dir.parent/'production-planning'/new_id/'USER_FEEDBACK.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        encoded=c.encoded(feedback)
        if path.exists() and path.read_text()!=encoded:raise ValueError('Recovery feedback changed; prepare a new proposal.')
        path.write_text(encoded)
        aid=rt.register(path,'Exact recovery request and user decisions',run=new_id,path=name)
        payload['sources'].append(planning.source_entry(rt,aid,name,'Exact recovery request and user decisions',
            'Latest explicit user decisions override earlier conflicting preferences. No additional execution authority.'))
        payload['required_artifacts'].append(aid)
        for task in tasks:
            if not task.get('execution'):
                # These are Relay-generated preambles, not user requests. Keep
                # their exact files as historical inputs without telling the
                # worker to start with every prior snapshot on each recovery.
                for source in payload['sources']:
                    old_path=source.get('path','')
                    if old_path.startswith('recovery/plan-') and old_path.endswith('/USER_FEEDBACK.json'):
                        old='Read '+old_path+' first. Apply the latest explicit user decisions when authoring and reviewing; preserve the original request otherwise.\n\n'
                        task['instruction']=task['instruction'].replace(old,'')
                task['instruction']='Read '+name+' first. Apply the latest explicit user decisions when authoring and reviewing; preserve the original request otherwise.\n\n'+task['instruction']
    payload['execution_recovery']={'kind':kind,'baseline':baseline,'request':request,
                                   'policies':copy.deepcopy(policies),'reused_completed_tasks':sorted(done),
                                   'completed_deliverables':retained}
    payload['recovery_origin']={'original_request':parent['request'],'previous_stage':payload.pop('previous_stage',None)}
    values=dict(parent)
    values.update(id=new_id,request_id=ident,parent_id=parent['id'],request=parent['request']+'\n\n--- RECOVERY REQUEST ---\n'+request,
        options=c.encoded(options),context=c.encoded(payload),context_hash=c.digest(payload),status='ready',calls=0,token=secrets.token_hex(12),
        event_id=None,expires=time.time()+86400,run=None,error=None,created=time.time())
    result,plan=planning.validate_recovery_result(result,values)
    values.update(result=c.encoded(result),plan=c.encoded(plan),plan_hash=c.digest(plan))
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
    state.db.execute('INSERT INTO production_stage_links(parent,plan_id) VALUES (?,?)',(run,new_id))
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
    intro=('Preparation recovery proposed. Start approves the displayed initial and correction attempts with exact asset bindings; completed work and old attempts are preserved.\n'
           if kind=='code_budget' else 'Browser setup repair proposed. Review the changed profile and exact origins; Start approves this new attempt.\n')
    event=planning.notice(state,row,'ready',intro+planning.preview(row))
    state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,new_id))
    planning.publish_ready_files(state,row,event,rt,plan,payload)
    return new_id
