"""Delivered decision cards for explicit scoped artifact replacement; no workers."""
import json
import secrets
import sqlite3
import time

from orchestrator import artifact_replacements as ar
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from task_relay import production_control as pc
from task_relay import relay_channels

SCHEMA={'type':'object','additionalProperties':False,'required':['kind','old_decision','new_decision'],
        'properties':{'kind':{'const':'replace_selection'},'old_decision':{'type':'string'},'new_decision':{'type':'string'}}}


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS production_replacement_cards(
        token TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, request_id INTEGER UNIQUE NOT NULL,
        run TEXT NOT NULL, old_decision TEXT NOT NULL, new_decision TEXT NOT NULL,
        revision INTEGER NOT NULL, preview TEXT NOT NULL, request TEXT NOT NULL,
        status TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS production_replacement_messages(
        token TEXT NOT NULL, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
        PRIMARY KEY(token,chat_id,message_id));''')


def validate_action(action,snapshot):
    if set(action)!={'kind','old_decision','new_decision'} or any(not isinstance(action[k],str) or not action[k] for k in ('old_decision','new_decision')):raise ValueError('Choose exact old and new saved decisions')
    known={d['id'] for run in snapshot.get('production_runs',[]) for d in run.get('selections',[]) if d.get('id')}
    for run in snapshot.get('production_runs',[]):
        for h in run.get('artifact_replacements',{}).get('heads',[]):known.update(h['members'])
    if action['old_decision'] not in known or action['new_decision'] not in known:raise ValueError('Selections are not in the current catalog; inspect the relevant stages first')


def propose(state,job,action):
    if getattr(state,'channel','telegram')!='telegram':raise ValueError('Replacement decision cards currently require Telegram')
    if not state.db.in_transaction:raise ValueError('Replacement proposal requires a transaction')
    row=state.db.execute('SELECT * FROM production_replacement_cards WHERE request_id=?',(job['id'],)).fetchone()
    if row:return 'Replacement decision card already prepared; no rebuild started.'
    rt=Runtime(pc.root(state),connection=state.db);p=ar.preview(rt,action['old_decision'],action['new_decision'])
    token=secrets.token_hex(12);event='orchestrator:'+str(job['id']);run=p['new']['run']
    state.db.execute('INSERT INTO production_replacement_cards VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (token,event,job['id'],run,action['old_decision'],action['new_decision'],p['expected_revision'],json.dumps(p),job['prompt'],'pending',time.time()+86400))
    state.db.execute('UPDATE orchestrator_chats SET focus=? WHERE id=?',(run,job['id']))
    lines=['Replace selected version for '+p['purpose']+'?', 'Job scope: '+p['scope'],
        'Old: '+p['old']['version']['path']+' · '+p['old']['version']['sha256'][:12],
        'New: '+p['new']['version']['path']+' · '+p['new']['version']['sha256'][:12],
        str(p['affected_count'])+' recorded outputs would need review (including superseded selections).']
    for a in p['affected_outputs'][:8]:lines.append('• '+a['run']+' / '+a['path'])
    if p['affected_count']>8:lines.append('More outputs are listed in Inspect stage after the decision.')
    lines.append('This also tracks later results using the old version in this job. Earlier decisions remain saved. No assignments change and no rebuild starts.')
    return '\n'.join(lines)


def controls(state,event):
    if getattr(state,'channel','telegram')!='telegram':return None
    row=state.db.execute("SELECT token FROM production_replacement_cards WHERE event_id=? AND status='pending' AND expires>?",(event,time.time())).fetchone()
    if not row:return None
    return {'inline_keyboard':[[{'text':'Replace selected version','callback_data':'prodreplace:apply:'+row['token']},
                              {'text':'Keep current version','callback_data':'prodreplace:dismiss:'+row['token']}]]}


def remember(state,event,chat,mid):
    state.db.execute('INSERT OR IGNORE INTO production_replacement_messages SELECT token,?,? FROM production_replacement_cards WHERE event_id=?',(chat,mid,event))


def apply(state,token,chat,mid,dismiss=False):
    if not state.db.in_transaction:raise ValueError('Replacement needs a transaction')
    row=state.db.execute('''SELECT c.* FROM production_replacement_cards c JOIN production_replacement_messages m ON m.token=c.token
        WHERE c.token=? AND m.chat_id=? AND m.message_id=?''',(token,chat,mid)).fetchone()
    if not row:raise ValueError('This replacement does not match a delivered card')
    if row['status']!='pending':return 'This replacement decision is already recorded.'
    if row['expires']<=time.time():raise ValueError('Replacement card expired; request a fresh card')
    sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(row['event_id'],)).fetchone()
    if not sent or not sent['sent'] or relay_channels.event_channel(state,row['event_id'])!='telegram':raise ValueError('Use the delivered Telegram replacement card')
    if dismiss:
        state.db.execute("UPDATE production_replacement_cards SET status='dismissed' WHERE token=?",(token,))
        return 'Current version retained.'
    job_scope=ar.scope(state.db,row['run'])
    pending=state.db.execute("SELECT focus FROM orchestrator_chats WHERE id!=? AND status IN ('queued','sending','guides_pending') AND focus IN (SELECT id FROM production_runs)",(row['request_id'],)).fetchall()
    if any(ar.scope(state.db,r['focus'])==job_scope for r in pending):raise ValueError('New feedback is still being processed; wait before replacing this version')
    rt=Runtime(pc.root(state),connection=state.db)
    current=ar.describe(rt,row['old_decision'],row['new_decision'])
    saved=json.loads(row['preview'])
    if any(current[k]!=saved[k] for k in ('scope','purpose','head','expected_revision','old','new')):
        raise ValueError('The replacement versions or state changed; request a fresh card')
    rt.replace_selection(row['old_decision'],row['new_decision'],row['revision'],token,row['request'])
    state.db.execute("UPDATE production_replacement_cards SET status='applied' WHERE token=?",(token,))
    pc.notice(state,row['run'],'replacement:'+token,'Selected version replaced for this job and purpose. Affected outputs are marked for review. No rebuild started; describe the update work to plan its bounded scope.')
    return 'Replacement recorded. No rebuild started.'


def callback(bridge,update):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith('prodreplace:'):return False
    state=bridge.state;user=q.get('from',{});message=q.get('message',{});chat=message.get('chat',{})
    if user.get('is_bot') or user.get('id')!=state.get('user_id') or chat.get('id')!=state.get('chat_id') or chat.get('type')!='private':return True
    try:
        _,verb,token=raw.split(':')
        if verb not in ('apply','dismiss'):raise ValueError('Unknown replacement choice')
        with transaction(state.db):result=apply(state,token,chat['id'],message.get('message_id'),verb=='dismiss')
    except (ValueError,OSError,sqlite3.Error) as exc:result=str(exc) if isinstance(exc,ValueError) else 'Replacement could not be recorded. Inspect the current status.'
    from task_relay.bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=result[:200],show_alert=True)
    except BridgeError:pass
    return True
