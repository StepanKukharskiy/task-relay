"""Delivered, versioned pause/resume/cancel cards; adapter work stays in the scheduler."""
import secrets
import sqlite3

from task_relay import production_control as pc
from task_relay import relay_channels
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS production_control_cards (
      token TEXT PRIMARY KEY, event_id TEXT NOT NULL, run TEXT NOT NULL,
      verb TEXT NOT NULL, epoch INTEGER NOT NULL, digest TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', UNIQUE(event_id,verb));
      CREATE TABLE IF NOT EXISTS production_control_messages (
      chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, token TEXT NOT NULL,
      PRIMARY KEY(chat_id,message_id,token));''')


def controls(state,event,run):
    if not event.startswith('production:') or getattr(state,'channel','telegram')!='telegram' or relay_channels.event_channel(state,event)!='telegram':return []
    view=next(v for v in pc.inspect(state,run,include_files=False) if v['name']==run)
    verbs=[]
    if view['status']=='paused':verbs.append(('resume','Resume'))
    elif pc.review_resume_digest(state,run,view,legacy=True):verbs.append(('resume','Resume remaining work'))
    elif view['status'] in ('active','uncertain') and view['scheduler_enabled']:verbs.append(('pause','Pause scheduling'))
    if view['status'] not in ('completed','cancelled'):verbs.append(('cancel','Cancel stage'))
    buttons=[]
    with transaction(state.db):
        for verb,label in verbs:
            epoch=state.get('production-control-epoch:'+run,0)
            state.db.execute('''INSERT OR IGNORE INTO production_control_cards
                (token,event_id,run,verb,epoch,digest) VALUES (?,?,?,?,?,?)''',
                (secrets.token_hex(12),event,run,verb,epoch,view['contract_digest']))
            card=state.db.execute('SELECT * FROM production_control_cards WHERE event_id=? AND verb=?',(event,verb)).fetchone()
            if card['status']=='pending' and card['epoch']==epoch:
                buttons.append({'text':label,'callback_data':'prodcontrol:'+card['token']})
    return [buttons] if buttons else []


def remember(state,event,chat_id,message_id):
    state.db.execute('''INSERT OR IGNORE INTO production_control_messages
        SELECT ?,?,token FROM production_control_cards WHERE event_id=?''',(chat_id,message_id,event))


def apply(state,token,chat_id,message_id):
    if not state.db.in_transaction:raise ValueError('Control requires a transaction.')
    if getattr(state,'channel','telegram')!='telegram':raise ValueError('Use the original Telegram card.')
    card=state.db.execute('''SELECT c.* FROM production_control_cards c
        JOIN production_control_messages m ON m.token=c.token
        WHERE c.token=? AND m.chat_id=? AND m.message_id=?''',(token,chat_id,message_id)).fetchone()
    if not card:raise ValueError('This control does not match a delivered card.')
    if card['status']=='applied':return 'This control was already applied.'
    run=card['run'];sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(card['event_id'],)).fetchone()
    if not sent or not sent['sent'] or relay_channels.event_channel(state,card['event_id'])!='telegram':
        raise ValueError('Wait for the complete control card in its original channel.')
    if card['epoch']!=state.get('production-control-epoch:'+run,0):raise ValueError('This control is stale. Check status for current controls.')
    rt=Runtime(pc.root(state),connection=state.db)
    digest=pc.runtime_digest(rt,run)
    if card['digest']!=digest:raise ValueError('The stage changed. Check its current status.')
    if card['verb']=='pause':
        if state.get('production-enabled:'+run)!=digest:raise ValueError('Scheduling is already off.')
        rt.pause(run)
        result='Scheduling paused. Running workers may finish; no further task will start until you resume.'
    elif card['verb']=='resume':
        if state.get('production-enabled:'+run)!=digest:
            result=pc.resume_review(state,run,legacy=True)
        else:
            rt.resume(run)
            result='Scheduling resumed within the existing stage authorization.'
    else:
        rt.request_cancel(run)
        state.put('production-enabled:'+run,False)
        state.put('production-review-grant:'+run,False)
        state.db.execute("UPDATE production_revisions SET status='failed',error='Stage cancelled by user' WHERE run=? AND status='queued'",(run,))
        state.db.execute("UPDATE production_continuations SET status='failed',error='Parent stage cancelled by user' WHERE parent=? AND status='queued'",(run,))
        pending=any(a['state']=='cancelling' for a in rt.status(run)['attempts'])
        result='Stage cancelled; no further tasks will start. '+('Running workers have a saved cancellation request; check status for their termination.' if pending else 'No running worker remains. Saved outputs are retained.')
    state.put('production-control-epoch:'+run,card['epoch']+1)
    state.db.execute("UPDATE production_control_cards SET status='applied' WHERE token=?",(token,))
    pc.notice(state,run,'control:'+token,result)
    return result


def callback(bridge,update):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith('prodcontrol:'):return False
    s=bridge.state;user=q.get('from',{});message=q.get('message',{});chat=message.get('chat',{})
    if user.get('is_bot') or user.get('id')!=s.get('user_id') or chat.get('type')!='private' or chat.get('id')!=s.get('chat_id'):return True
    try:
        with transaction(s.db):result=apply(s,raw.split(':',1)[1],chat['id'],message.get('message_id'))
    except (ValueError,OSError,sqlite3.Error) as exc:
        result=str(exc) if isinstance(exc,ValueError) else 'Control could not be saved. Check status and try again.'
    from task_relay.bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=result[:200],show_alert=True)
    except BridgeError:pass
    return True
