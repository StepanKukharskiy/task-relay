"""Exact, delivered-output choices over the existing runtime decision record."""
import secrets
import json
import sqlite3
from pathlib import Path

from task_relay import production_control as pc
from task_relay import relay_channels
from orchestrator.runtime import Runtime, file_hash, safe_file
from orchestrator.storage import transaction


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS production_selection_cards (
        token TEXT PRIMARY KEY, event_id TEXT NOT NULL, run TEXT NOT NULL,
        task TEXT NOT NULL, assignment TEXT NOT NULL, attempt TEXT NOT NULL,
        artifact TEXT NOT NULL, sha256 TEXT NOT NULL, purpose TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', UNIQUE(event_id,artifact));
      CREATE TABLE IF NOT EXISTS production_selection_messages (
        chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, token TEXT NOT NULL,
        PRIMARY KEY(chat_id,message_id,token));''')
    if 'members' not in {r[1] for r in db.execute('PRAGMA table_info(production_selection_cards)')}:
        db.execute("ALTER TABLE production_selection_cards ADD COLUMN members TEXT NOT NULL DEFAULT '[]'")


def controls(state,event):
    if getattr(state,'channel','telegram')!='telegram' or not event.startswith('production:') or relay_channels.event_channel(state,event)!='telegram':
        return []
    run=event.split(':')[1]
    rt=Runtime(pc.root(state),connection=state.db)
    buttons=[]
    with transaction(state.db):
        active=state.db.execute("SELECT 1 FROM production_runs WHERE id=? AND status='active'",(run,)).fetchone()
        if not active:return []
        for task in state.db.execute("SELECT * FROM production_tasks WHERE run=? AND status='awaiting_user' ORDER BY id",(run,)).fetchall():
            purpose=rt.decision_purpose(task)
            if not purpose:continue
            artifacts=state.db.execute('SELECT * FROM production_artifacts WHERE attempt=? AND task=? ORDER BY path',(task['latest'],task['id'])).fetchall()
            selected=rt.selection_paths(task)
            if selected:
                by_path={a['path']:a for a in artifacts}
                if not set(selected)<=set(by_path):continue
                groups=[[by_path[p] for p in selected]]
            else:groups=[[a] for a in artifacts]
            for group in groups:
                artifact=group[0]
                members=json.dumps([{'artifact':a['id'],'sha256':a['sha256'],'path':a['path']} for a in group])
                state.db.execute('''INSERT OR IGNORE INTO production_selection_cards
                    (token,event_id,run,task,assignment,attempt,artifact,sha256,purpose,members)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',(secrets.token_hex(12),event,run,task['id'],task['assignment'],task['latest'],artifact['id'],artifact['sha256'],purpose,members))
                card=state.db.execute('SELECT * FROM production_selection_cards WHERE event_id=? AND artifact=?',(event,artifact['id'])).fetchone()
                if card['status']=='pending':
                    label='Select set: '+' + '.join(a['path'] for a in group) if selected else 'Select '+task['id']+'/'+artifact['path']
                    if rt.quality_review(task):label='Accept these outputs with noted concerns'
                    buttons.append([{'text':label, 'callback_data':'prodselect:'+card['token']}])
                    if len(buttons)==30:return buttons
    return buttons


def remember(state,event,chat_id,message_id):
    state.db.execute('''INSERT OR IGNORE INTO production_selection_messages
        SELECT ?,?,token FROM production_selection_cards WHERE event_id=?''',(chat_id,message_id,event))


def apply(state,token,chat_id,message_id):
    if getattr(state,'channel','telegram')!='telegram':raise ValueError('Use the Telegram selection card.')
    if not state.db.in_transaction:raise ValueError('Selection requires a transaction.')
    card=state.db.execute('''SELECT c.* FROM production_selection_cards c
        JOIN production_selection_messages m ON m.token=c.token
        WHERE c.token=? AND m.chat_id=? AND m.message_id=?''',(token,chat_id,message_id)).fetchone()
    if not card:raise ValueError('This choice does not match a delivered selection card.')
    if card['status']=='selected':return 'This selection is already recorded.'
    if card['status']!='pending':raise ValueError('This choice is no longer current.')
    sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(card['event_id'],)).fetchone()
    media=state.db.execute("SELECT status FROM media_outbox WHERE id=?",('production-output:'+card['artifact'],)).fetchone()
    if not sent or not sent['sent'] or not media or media['status']!='sent':
        raise ValueError('Wait for the selected output file to finish delivery.')
    if relay_channels.event_channel(state,card['event_id'])!='telegram':raise ValueError('Use the original channel.')
    if state.db.execute("SELECT 1 FROM orchestrator_chats WHERE focus=? AND status IN ('queued','sending','guides_pending')",(card['run'],)).fetchone():
        raise ValueError('A reply is still being processed; wait before selecting an output.')
    if state.db.execute("SELECT 1 FROM production_revisions WHERE run=? AND status='queued'",(card['run'],)).fetchone():
        raise ValueError('A revision is pending; this output cannot be selected yet.')
    rt=Runtime(pc.root(state),connection=state.db)
    task=rt.task(card['run'],card['task']);artifact=rt.artifact(card['artifact'])
    if task['assignment']!=card['assignment'] or task['latest']!=card['attempt'] or artifact['sha256']!=card['sha256']:
        raise ValueError('The output or assignment changed; use its current selection card.')
    blob=safe_file(rt.root,str(Path(artifact['blob']).relative_to(rt.root)))
    if file_hash(blob)!=card['sha256'] or blob.stat().st_size!=artifact['bytes']:
        raise ValueError('The registered output changed; selection was not recorded.')
    members=json.loads(card['members']) or [{'artifact':artifact['id'],'sha256':artifact['sha256'],'path':artifact['path']}]
    for member in members:
        current=rt.artifact(member['artifact'])
        if current['sha256']!=member['sha256'] or current['path']!=member['path']:
            raise ValueError('The output selection set changed')
        delivered=state.db.execute('SELECT status FROM media_outbox WHERE id=?',('production-output:'+member['artifact'],)).fetchone()
        if not delivered or delivered['status']!='sent':raise ValueError('Wait for every file in the selection set to finish delivery.')
    names=' + '.join(m['path'] for m in members)
    note='Telegram selection of '+names+' from delivered message '+str(message_id)
    rt.select(card['run'],card['task'],card['artifact'],card['purpose'],note,artifacts=[m['artifact'] for m in members])
    state.db.execute("UPDATE production_selection_cards SET status='stale' WHERE run=? AND task=? AND status='pending'",(card['run'],card['task']))
    state.db.execute("UPDATE production_selection_cards SET status='selected' WHERE token=?",(token,))
    resumed=pc.resume_review(state,card['run']) if pc.review_resume_digest(state,card['run']) else ''
    pc.notice(state,card['run'],'selected:'+card['artifact'],'Selected '+names+' for '+card['purpose']+'.'+
              ('\n'+resumed if resumed else ''))
    return 'Selection recorded.'


def callback(bridge,update):
    query=update['callback_query'];raw=query.get('data','')
    if not raw.startswith('prodselect:'):return False
    state=bridge.state;user=query.get('from',{});message=query.get('message',{});chat=message.get('chat',{})
    if user.get('is_bot') or user.get('id')!=state.get('user_id') or chat.get('id')!=state.get('chat_id') or chat.get('type')!='private':return True
    try:
        with transaction(state.db):result=apply(state,raw.split(':',1)[1],chat['id'],message.get('message_id'))
    except (ValueError,OSError,sqlite3.Error) as exc:
        result=str(exc) if isinstance(exc,ValueError) else 'Selection could not be recorded. Check status and try again.'
    from task_relay.bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=query['id'],text=result[:200],show_alert=True)
    except BridgeError:pass
    return True
