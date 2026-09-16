"""Delivered bounded recovery cards for visual reviews and local code budgets."""
import copy
import json
import secrets
import sqlite3
import time
from orchestrator import contracts as c
from orchestrator.runtime import Runtime,file_hash
from orchestrator.storage import transaction
from . import production_control as pc,relay_channels


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS production_visual_review_cards(
      token TEXT PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,run TEXT NOT NULL,request TEXT NOT NULL,
      baseline TEXT NOT NULL,spec TEXT NOT NULL,status TEXT NOT NULL,expires REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS production_visual_review_messages(
      token TEXT NOT NULL,chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
      PRIMARY KEY(token,chat_id,message_id));''')


def snapshot(state,run):
    rt=Runtime(pc.root(state),connection=state.db);status=rt.status(run)
    bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    if (bound[0] if bound else 'telegram')!=getattr(state,'channel','telegram'):raise ValueError('Recover review in its original channel.')
    if state.db.execute('SELECT 1 FROM production_auto_repairs WHERE preparation=?',(run,)).fetchone():
        from . import production_repairs
        return production_repairs.recovery_snapshot(state,run,rt,status)
    stage=state.db.execute("SELECT s.*,p.status AS pipeline_status FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline LEFT JOIN production_plans plan ON s.target=plan.id WHERE plan.run=? OR (s.target_kind='production_run' AND s.target=?)",(run,run)).fetchone()
    if stage and (stage['pipeline_status']!='blocked' or stage['error']!='Production blocked; no attempts reset.'):
        raise ValueError('Resolve the workflow pause before review recovery.')
    failed=[t for t in status['tasks'] if t['status']=='blocked']
    if status['status']!='blocked' or len(failed)!=1:raise ValueError('One stopped blocked task is required.')
    task=failed[0];spec=rt.spec(task)
    if spec.get('tools')==['files','python'] and not spec.get('review_of'):
        from . import production_budget_recovery
        return production_budget_recovery.snapshot(state,run,rt,status,task,stage)
    if not spec.get('review_of') or not spec.get('browser'):raise ValueError('Not a browser review failure.')
    if any(a['state'] in ('launching','running','cancelling','uncertain') for a in status['attempts']):raise ValueError('Active or uncertain work prevents review recovery.')
    target=rt.task(run,spec['review_of']);attempt=next(a for a in status['attempts'] if a['id']==task['latest'])
    receipt=json.loads(attempt['receipt'] or '{}');frozen=json.loads(state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(attempt['id'],)).fetchone()[0])
    if (receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
        or receipt.get('pending_requests') or receipt.get('browser',{}).get('uncertain_actions')
        or not isinstance(receipt.get('browser',{}).get('actions'),list)
        or any(a.get('status')!='observed' for a in receipt['browser']['actions'])):
        raise ValueError('Confirmed read-only review receipt required; no uncertain replay.')
    if target['status']!='awaiting_review' or target['latest']!=frozen.get('review_target'):raise ValueError('The exact candidate is no longer waiting for this review.')
    png=[i['path'] for i in frozen['inputs'] if i.get('media_type')=='image/png']
    if not png or spec['browser'].get('visual_inputs'):raise ValueError('This recovery is for a reviewer without selected PNG pixels.')
    for item in frozen['inputs']:
        artifact=rt.artifact(item['artifact'])
        if artifact['sha256']!=item['sha256'] or file_hash(artifact['blob'])!=item['sha256']:raise ValueError('Review source changed.')
    if any(t['attempts'] and task['id'] in rt.spec(t)['dependencies'] for t in status['tasks']):raise ValueError('Downstream work already started.')
    baseline={'run':run,'tasks':status['tasks'],'attempts':status['attempts'],
              'pipeline_stage':dict(stage) if stage else None,'review_frozen':frozen,'digest':pc.runtime_digest(rt,run),'epoch':state.get('production-control-epoch:'+run,0)}
    new=copy.deepcopy(spec);new['browser']['visual_inputs']=png;new['max_attempts']=task['attempts']+1
    new['instruction']='Inspect the exact selected PNG pixels attached to your request and read their provenance. Evaluate the original criteria on the saved candidate. Canvas pages can have empty DOM text; do not require a second website visit to review these pixels. Never infer user acceptance.\n\n'+new['instruction']
    new['revision']={'kind':'visual_review_recovery','instruction':'Review exact saved pixels after a metadata-only blocker.','previous_attempt':task['latest']}
    return baseline,c.assignment(new)


def propose(state,job,run):
    if not state.db.in_transaction:raise ValueError('Review proposal requires a transaction.')
    if getattr(state,'channel','telegram')!='telegram':raise ValueError('Use the paired Telegram chat for the recovery Start card.')
    baseline,spec=snapshot(state,run)
    existing=state.db.execute("SELECT * FROM production_visual_review_cards WHERE run=? AND status='pending' AND expires>?",(run,time.time())).fetchone()
    if existing:return 'Use the existing recovery Start card. No duplicate attempt was added.'
    token=secrets.token_hex(12);event='orchestrator:'+str(job['id'])
    state.db.execute('INSERT INTO production_visual_review_cards VALUES (?,?,?,?,?,?,?,?)',
        (token,event,run,job['prompt'],c.encoded(baseline),c.encoded(spec),'pending',time.time()+86400))
    rt=Runtime(pc.root(state),connection=state.db);task=rt.task(run,spec['id'])
    frozen=baseline['review_frozen']
    if spec['revision']['kind']=='script_repair_recovery':
        return ('Script repair recovery ready for '+run+'\nAI: '+frozen['backend']['model']+
            '\nStart approves '+str(spec['max_attempts']-task['attempts'])+' additional preparation/review attempt(s), including any correction after review. '+
            'Each attempt: '+str(spec['limits']['seconds'])+' seconds, '+str(spec['limits']['tool_calls'])+' tool calls; '+
            str(spec['limits'].get('provider_requests',8))+' provider requests for API workers. '+
            'Response limit: '+str(spec['limits'].get('response_tokens',4096))+' author / '+str(baseline['repair_updates']['review_repair']['limits'].get('response_tokens',4096))+' reviewer tokens. '+
            'Uses the exact original failure, script, checks and rejected review. Earlier attempts remain preserved. '+
            'This Start approves file preparation only. Rhino/Blender execution still requires a separate Start on the reviewed exact script.')
    if spec['revision']['kind']=='code_budget_recovery':
        return ('Preparation recovery ready for '+run+'\nTask: '+spec['id']+'\nAI: '+frozen['backend']['model']+
            '\nStart uses the remaining approved preparation attempt with '+str(spec['limits']['provider_requests'])+' provider requests, '+str(spec['limits']['tool_calls'])+' tool calls and '+str(spec['limits']['seconds'])+' seconds. Completed tasks and exact inputs are retained. Old attempts are not reset. Independent review and the remaining approved workflow follow the new draft.'+
            ('\nUnstarted preparation/review task request limits: '+', '.join(t+': '+str(s['limits']['provider_requests']) for t,s in baseline['budget_updates'].items()) if baseline.get('budget_updates') else ''))
    images=[i for i in frozen['inputs'] if i['path'] in spec['browser']['visual_inputs']]
    return ('Visual review repair ready for '+run+'\nStart sends only these saved PNG pixels to '+frozen['backend']['model']+' for one independent review:\n'+
            '\n'.join(i['path']+' · '+i['sha256'][:12] for i in images)+
            '\nTask limit: '+str(spec['limits']['seconds'])+' seconds. Original website permissions and tool limits remain fixed. The screenshot and plant photos will not be recreated. If review passes, the remaining approved workflow resumes.')


def controls(state,event):
    row=state.db.execute("SELECT token,spec FROM production_visual_review_cards WHERE event_id=? AND status='pending' AND expires>?",(event,time.time())).fetchone()
    if not row:return None
    label='Start preparation' if json.loads(row['spec'])['revision']['kind'] in ('code_budget_recovery','script_repair_recovery') else 'Start visual review'
    return {'inline_keyboard':[[{'text':label,'callback_data':'visualreview:start:'+row['token']}]]}


def remember(state,event,chat,mid):
    state.db.execute('INSERT OR IGNORE INTO production_visual_review_messages SELECT token,?,? FROM production_visual_review_cards WHERE event_id=?',(chat,mid,event))


def apply(state,token,chat,mid):
    if not state.db.in_transaction:raise ValueError('Review Start requires a transaction.')
    row=state.db.execute('''SELECT c.* FROM production_visual_review_cards c JOIN production_visual_review_messages m ON c.token=m.token
      WHERE c.token=? AND m.chat_id=? AND m.message_id=?''',(token,chat,mid)).fetchone()
    if not row:raise ValueError('Use the delivered visual review card.')
    if row['status']!='pending':return 'This review Start is already recorded.'
    sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(row['event_id'],)).fetchone()
    if row['expires']<=time.time() or not sent or not sent[0] or relay_channels.event_channel(state,row['event_id'])!='telegram':raise ValueError('Use the current delivered Telegram Start card.')
    baseline,spec=snapshot(state,row['run'])
    if baseline!=json.loads(row['baseline']) or spec!=json.loads(row['spec']):raise ValueError('Review inputs or state changed; request a new repair.')
    rt=Runtime(pc.root(state),connection=state.db)
    spec['revision'].update(instruction=row['request'],source='visual_review_start:'+token)
    aid=rt.new_assignment(row['run'],spec)
    state.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,row['run'],spec['id']))
    kind='code_budget_retry_approved' if spec['revision']['kind']=='code_budget_recovery' else 'visual_review_retry_approved'
    if spec['revision']['kind']=='script_repair_recovery':kind='script_repair_recovery_approved'
    rt.event(row['run'],spec['id'],spec['revision']['previous_attempt'],kind,{'request':row['request'],'card':token,'limits':spec['limits'],'visual_inputs':spec.get('browser',{}).get('visual_inputs',[]),'attempts_reset':False})
    for tid,updated in baseline.get('budget_updates',{}).items():
        assignment=rt.new_assignment(row['run'],updated)
        state.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?',(assignment,row['run'],tid))
        rt.event(row['run'],tid,None,'provider_request_limit_approved',{'card':token,'limits':updated['limits']})
    for tid,updated in baseline.get('repair_updates',{}).items():
        assignment=rt.new_assignment(row['run'],updated)
        state.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(assignment,row['run'],tid))
        rt.event(row['run'],tid,updated['revision']['previous_attempt'],kind,{'card':token,'limits':updated['limits'],'attempts_reset':False})
    if baseline.get('repair_row'):
        from . import production_repairs
        production_repairs.resume_preparation(state,baseline,token)
    state.put('production-enabled:'+row['run'],pc.runtime_digest(rt,row['run']))
    state.put('production-control-epoch:'+row['run'],baseline['epoch']+1)
    if baseline['pipeline_stage']:
        from . import pipelines
        stage=baseline['pipeline_stage']
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(stage['pipeline'],))
        state.db.execute("UPDATE relay_pipeline_steps SET status='running',error=NULL WHERE pipeline=? AND id=?",(stage['pipeline'],stage['id']))
        pipelines.event(state,stage['pipeline'],stage['id'],kind,{'run':row['run'],'card':token,'attempts_reset':False})
    state.db.execute("UPDATE production_visual_review_cards SET status='started' WHERE token=?",(token,))
    if kind=='script_repair_recovery_approved':return 'Script correction and independent review scheduled. Native execution still waits for exact-code Start.'
    return 'Preparation scheduled using its remaining attempt. Completed work is retained.' if kind=='code_budget_retry_approved' else 'Visual review scheduled. The exact candidate and completed photos are retained.'


def callback(bridge,update):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith('visualreview:'):return False
    state=bridge.state;user=q.get('from',{});message=q.get('message',{});chat=message.get('chat',{})
    if user.get('is_bot') or user.get('id')!=state.get('user_id') or chat.get('id')!=state.get('chat_id') or chat.get('type')!='private':return True
    try:
        _,verb,token=raw.split(':')
        if verb!='start':raise ValueError('Unknown review action.')
        with transaction(state.db):result=apply(state,token,chat['id'],message.get('message_id'))
    except (ValueError,OSError,sqlite3.Error) as exc:result=str(exc) if isinstance(exc,ValueError) else 'Review recovery could not be recorded.'
    from .bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=result[:200],show_alert=True)
    except BridgeError:pass
    return True
