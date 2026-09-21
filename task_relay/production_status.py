"""Authenticated status cards with optional exact-output selection controls."""
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import time
from contextlib import closing

from task_relay import production_control as pc


def token(run,kind='prodstatus'):
    # Full run names can exceed Telegram's 64-byte callback-data limit.
    return kind+':' + hashlib.sha256(run.encode()).hexdigest()[:24]


def controls(state, event):
    run=None
    if event.startswith('production:'):
        run=event.split(':')[1]
    elif event.startswith('orchestrator:'):
        row=state.db.execute('SELECT focus FROM orchestrator_chats WHERE id=?',(event.split(':')[1],)).fetchone()
        run=row['focus'] if row else None
    if not run or not state.db.execute('SELECT 1 FROM production_runs WHERE id=?',(run,)).fetchone():return None
    from task_relay import production_selections; from task_relay import production_lifecycle
    buttons=[[{'text':'Check status','callback_data':token(run)},
        {'text':'Inspect stage','callback_data':token(run,'prodinspect')}]]+production_selections.controls(state,event)+production_lifecycle.controls(state,event,run)
    view=next((v for v in pc.inspect(state,run,include_files=False) if v['name']==run),None)
    from . import pipelines
    if view and view['status']=='completed' and view.get('deferred_operations') and not pipelines.owns_run(state,run):
        buttons.append([{'text':'Plan execution','callback_data':token(run,'prodexecute')}])
    from . import production_review_corrections
    if view and production_review_corrections.details(state,run):
        buttons.append([{'text':'Plan correction','callback_data':token(run,'prodcorrect')}])
    return {'inline_keyboard':buttons}


def plan_execution(state,run):
    """Explicit button request; select nothing and launch no host work here."""
    from task_relay import production_planning as planning, capabilities, relay_channels
    from task_relay import production_stages
    from orchestrator.runtime import Runtime
    rt=Runtime(pc.root(state),connection=state.db)
    channel=getattr(state,'channel','telegram')
    production_stages.snapshot(state,rt,run,channel)
    plan=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    deferred=plan.get('deferred_operations',{})
    if not deferred:raise ValueError('This stage has no pending execution to plan.')
    prior=production_stages.planning_origin(state,run)
    if not prior:raise ValueError('The original planning request is missing; inspect the stage.')
    linked=state.db.execute('''SELECT p.id,p.status FROM production_stage_links l
        JOIN production_plans p ON p.id=l.plan_id WHERE l.parent=?''',(run,)).fetchone()
    if linked and linked['status']!='discarded':
        if linked['status']=='blocked':
            recovered,_=planning.recover_validated_response(state,linked['id'])
            return 'Recovered saved execution plan: '+recovered+'. No provider call repeated; review its files and use Start.'
        return 'Execution plan already '+linked['status']+': '+linked['id']+'. Use that saved plan; no duplicate was created.'
    options=json.loads(prior['options']);project=options.get('project')
    ident=int(hashlib.sha256(('plan-execution:'+run).encode()).hexdigest()[:15],16)
    action=dict(kind='plan_production',template='custom',project=project,reference_pack_id=None,
        research_ids=[],planning_only=False,previous_run=run,step_capabilities=sorted(deferred),
        deliverables={k:v['description'] for k,v in plan.get('deliverables',{}).items() if v.get('deferred_operation')})
    snapshot={'production_runs':pc.inspect(state,run,include_files=False),
        'codex_projects':[{'cwd':project}] if project else [],'capabilities':capabilities.catalog(state,{})}
    state.db.execute('INSERT OR IGNORE INTO relay_request_channels VALUES (?,?)',(ident,channel))
    prompt=('Plan the pending execution using the exact selected prepared inputs. Produce the remaining declared deliverables. '
        'Preserve the original scope and decisions. Present the complete script, inputs and limits for Start; do not execute yet.\n\n'
        '--- ORIGINAL USER REQUEST ---\n'+prior['request'])
    return planning.enqueue(state,{'id':ident,'prompt':prompt,'provider':prior['provider'],'model':prior['model']},action,snapshot)


def current(state, run):
    requested=run;seen=set();pending=None;history=[]
    while run not in seen and len(seen)<20:
        seen.add(run)
        row=state.db.execute('SELECT child,status,error FROM production_continuations WHERE parent=?',(run,)).fetchone()
        if not row:
            row=state.db.execute('''SELECT l.child,CASE WHEN l.child IS NOT NULL THEN 'registered' ELSE p.status END AS status,p.error
                FROM production_stage_links l JOIN production_plans p ON p.id=l.plan_id WHERE l.parent=?''',(run,)).fetchone()
        if not row:break
        if row['status']!='registered':
            pending=dict(row);break
        history.append(run);run=row['child']
    view=next((v for v in pc.inspect(state,run,include_files=False) if v['name']==run),None)
    if not view:raise ValueError('This production is no longer available.')
    labels={'active':'In progress','awaiting_user':'Ready for your review','blocked':'Blocked',
            'completed':'Completed','cancelled':'Cancelled','uncertain':'Needs inspection','paused':'Scheduling paused'}
    lines=['Production: '+run,labels.get(view['status'],view['status'])]
    if view.get('deferred_operations') and view['status'] in ('active','awaiting_user','completed'):
        lines[1]='Preparation in progress; execution pending' if view['status']=='active' else 'Preparation ready; execution pending'
    lines.append('Outcome: '+view['brief'])
    from . import production_review_corrections
    correction=production_review_corrections.text(state,run)
    if correction:lines.extend(['',correction])
    from . import pipelines
    workflow=pipelines.owns_run(state,run)
    from .workflow_files import owner_for_run
    owner=owner_for_run(state,run)
    if owner:
        from .workflow_files import location_text
        lines.append(location_text(state,owner['id']))
    if view.get('deferred_operations'):lines.append(pc.pending_execution_text(view,workflow).lstrip())
    if view['status']=='paused':lines.append('Running workers may finish. Further tasks wait for Resume.')
    if view['status']=='cancelled' and any(t['attempt_state'] in ('launching','running','cancelling','uncertain') for t in view['tasks']):
        lines.append('Worker termination is not yet confirmed. Cancellation remains pending; no new task will start.')
    if requested!=run:lines.append('Current continuation of '+requested)
    if history:lines.append('Earlier stages: '+', '.join(history))
    for task in view['tasks']:
        status=task['status']
        if status=='queued':
            if not task['runnable']:
                status='Waiting for '+', '.join(d['task']+' ('+d['status']+')' for d in task['dependencies'])
            else:status='Queued to start' if view['scheduler_enabled'] else 'Queued; scheduling is off'
        elif status=='running':status='Running'
        elif status=='awaiting_user':status='Waiting for your review'
        elif status=='awaiting_review':status='Waiting for independent review'
        lines.extend(['',f"{task['id']}: {status} · attempt {task['attempts']}/{task['max_attempts']}"])
        from .production_activity import lines as activity_lines,blocker_lines
        lines.extend(blocker_lines(task))
        lines.extend(activity_lines(task))
        target=next((t for t in view['tasks'] if t['id']==task['review_of']),None)
        if target and task.get('latest_attempt') and task.get('review_target')!=target['latest_attempt']:
            lines.append('An earlier review does not approve the current draft.')
    lines.append('')
    if pending:lines.append('Continuation setup: '+pending['status']+(('; '+pending['error'][:700]) if pending['error'] else ''))
    if view['status']=='blocked' and not correction:
        lines.append('Waiting alone will not resolve this blocker.')
        if any(t['status']=='blocked' and t['attempts']>=t['max_attempts'] for t in view['tasks']):
            lines.append('Attempt budget exhausted. An explicit continuation request is needed for more work.')
    if view['status']=='awaiting_user':lines.append('Use a Select button for the exact delivered file, or reply with feedback. '+('Relay will continue the saved workflow after selection; exact host-code Start remains required.' if workflow else 'No later stage starts automatically.'))
    if view['status']=='completed' and not pending:
        from . import pipelines
        lines.append(pipelines.continuation_text(state,run))
    replacements=view.get('artifact_replacements',{})
    if replacements.get('outdated_outputs'):
        lines.append('Outputs needing review after version replacement: '+str(len({r['artifact'] for r in replacements['outdated_outputs']}))+(' or more' if replacements['truncated'] else '')+'. Inspect stage for exact versions and reasons. No rebuild has been authorized.')
    for decision in state.db.execute('''SELECT d.task,d.purpose,a.path FROM production_decisions d
        JOIN production_artifacts a ON a.id=d.artifact WHERE d.run=? ORDER BY d.created DESC LIMIT 10''',(run,)):
        lines.append('Selected '+decision['task']+'/'+decision['path']+' for '+decision['purpose']+'.')
    health=state.get('health:production',{})
    stamp=health.get('last_success')
    if not stamp or time.time()-stamp>30:
        lines.append('Scheduler heartbeat is unavailable or stale; these are the latest recorded states, not proof of live execution.')
    lines.append('Checked '+datetime.now(timezone.utc).strftime('%H:%M:%S UTC'))
    if view['status']=='completed':
        from .result_handoff import saved_text
        try:
            handoff=saved_text(state,run)
            if handoff:lines.extend(['',handoff])
        except (ValueError,OSError,KeyError):pass
    return run,'\n'.join(lines)


def inspection(state,run,key):
    """Save a bounded read-only snapshot for delivery through the existing outbox."""
    from orchestrator.runtime import Runtime,safe_file
    rt=Runtime(pc.root(state),connection=state.db)
    report=rt.status(run)
    from orchestrator.artifact_dependencies import run_lineage
    report['artifact_lineage']=run_lineage(state.db,run)
    from orchestrator.artifact_replacements import view as replacements_view
    report['artifact_replacements']=replacements_view(state.db,run)
    report['backend']=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])['backend']
    report['assignments']=[rt.spec(t) for t in report['tasks']]
    report['registered_inputs']=[]
    for aid in sorted({i['artifact'] for spec in report['assignments'] for i in spec['inputs'] if 'artifact' in i}):
        artifact=rt.artifact(aid)
        report['registered_inputs'].append({k:artifact[k] for k in ('id','run','task','attempt','path','sha256','bytes','purpose')})
    report['decisions']=[dict(d) for d in state.db.execute('SELECT * FROM production_decisions WHERE run=?',(run,))]
    report['events']=[];report['events_omitted']=0;used=0
    for event in state.db.execute('SELECT * FROM production_events WHERE run=? ORDER BY id',(run,)):
        entry=dict(event);size=len(entry['data'].encode())
        if used+size>180000:report['events_omitted']+=1;continue
        entry['data']=json.loads(entry['data']);report['events'].append(entry);used+=size
    report['worker_logs']=[];remaining=128000
    for attempt in report['attempts']:
        attempt['receipt']=json.loads(attempt['receipt']) if attempt['receipt'] else None
        for name in ('events.jsonl','stderr.txt','supervisor.log','operation.json','response.json'):
            relative='workers/'+attempt['id']+'/'+name
            try:
                path=safe_file(rt.root,relative);size=path.stat().st_size
                with path.open('rb') as stream:raw=stream.read(min(remaining,32000))
                remaining-=len(raw)
                report['worker_logs'].append({'attempt':attempt['id'],'file':name,'text':raw.decode('utf-8',errors='replace'),
                    'bytes':size,'truncated':size>len(raw)})
            except (ValueError,OSError):
                report['worker_logs'].append({'attempt':attempt['id'],'file':name,'unavailable':True})
    report['usage_note']='Usage is reported verbatim in attempt receipts when available. Unreported usage and cost are unknown; no price is estimated.'
    report['captured_at']=time.time()
    folder=state.media_dir.parent/'production-inspections';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(key+'.json')
    event='production:'+run+':inspection:'+key
    if state.db.execute('SELECT 1 FROM outbox WHERE id=?',(event,)).fetchone():return
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    pc.notice(state,run,'inspection:'+key,'Stage inspection: '+run+'\nAssignments, exact inputs and outputs, executor, checks, attempts, available logs and recorded usage are attached.')
    state.db.execute('''INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption)
        VALUES (?,?,?,?,?,?)''',('production-inspection:'+key,event,str(path),'stage-inspection.json','original','Recorded stage state: '+run))


def callback(bridge, update):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith(('prodstatus:','prodinspect:','prodexecute:','prodcorrect:')):return False
    state=bridge.state;chat=q.get('message',{}).get('chat',{});user=q.get('from',{})
    if user.get('is_bot') or user.get('id')!=state.get('user_id') or chat.get('type')!='private' or chat.get('id')!=state.get('chat_id'):
        return True
    message='Status refreshed.'
    try:
        bound=state.db.execute('SELECT focus FROM orchestrator_messages WHERE chat_id=? AND message_id=?',(chat['id'],q.get('message',{}).get('message_id'))).fetchone()
        if not bound or not bound['focus'] or token(bound['focus'],raw.split(':')[0])!=raw:
            raise ValueError('This status button does not match a delivered production message.')
        run,text=current(state,bound['focus'])
        from orchestrator.storage import transaction
        with transaction(state.db):
            key=hashlib.sha256(q['id'].encode()).hexdigest()[:24]
            if raw.startswith('prodcorrect:'):
                from . import production_review_corrections
                ident=production_review_corrections.propose(state,bound['focus'])
                message='Correction plan ready: '+ident+'. Use its Start preparation button.'
                pc.notice(state,bound['focus'],'correction-plan:'+key,message)
            elif raw.startswith('prodexecute:'):
                message=plan_execution(state,bound['focus'])
                pc.notice(state,bound['focus'],'execution-plan:'+key,message)
            elif raw.startswith('prodinspect:'):
                inspection(state,run,key);message='Stage inspection queued.'
            else:pc.notice(state,run,'status:'+key,text)
    except (ValueError,OSError,sqlite3.Error) as exc:
        message='Could not read production status. Try again.' if not isinstance(exc,ValueError) else str(exc)
    from task_relay.bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=message[:200])
    except BridgeError:pass
    return True
