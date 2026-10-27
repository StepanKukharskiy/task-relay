"""Commit delivery intent before transport; reuse receipts, never uncertain sends."""
import hashlib
import json
import time
from orchestrator.storage import transaction


class UncertainDelivery(ValueError):pass


def initialize(db):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_delivery_effects'").fetchone()
    db.execute('''CREATE TABLE IF NOT EXISTS relay_delivery_effects(
        id TEXT PRIMARY KEY,event_id TEXT NOT NULL,digest TEXT NOT NULL,
        status TEXT NOT NULL,attempts INTEGER NOT NULL,receipt TEXT,error TEXT,updated REAL NOT NULL)''')

    if exists:return
    from .relay_channels import event_channel
    from types import SimpleNamespace
    state=SimpleNamespace(db=db)
    # Earlier versions could crash after transport but before marking sent.
    # Preserve that ambiguity during migration; attempts=0 is not proof of safety.
    pending=[('text:'+r['event_id']+':'+str(r['part']),r['event_id']) for r in db.execute('SELECT * FROM outbox_parts WHERE sent=0')]
    pending += [('media:'+r['id']+':'+r['kind'],r['event_id']) for r in db.execute("SELECT * FROM media_outbox WHERE status IN ('pending','sending','retry','uncertain')")]
    for ident,event in pending:
        if event_channel(state,event)!='telegram':continue
        db.execute("INSERT INTO relay_delivery_effects VALUES (?,?,?,'uncertain',0,NULL,?,?)",
                   (ident,event,'legacy-unknown','Earlier sender did not record dispatch intent; reconcile before resending.',time.time()))


def send(state,ident,event_id,payload,transport):
    if state.db.in_transaction:raise ValueError('External delivery must dispatch after commit')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with transaction(state.db):
        old=state.db.execute('SELECT * FROM relay_delivery_effects WHERE id=?',(ident,)).fetchone()
        if old:
            if old['digest']=='legacy-unknown':raise UncertainDelivery(old['error'])
            if old['digest']!=digest:raise UncertainDelivery('Delivery payload changed; inspect the saved intent.')
            if old['status']=='confirmed':return json.loads(old['receipt'])
            if old['status'] in ('submitting','uncertain'):raise UncertainDelivery('Delivery outcome is uncertain; inspect its receipt before resending.')
        state.db.execute('''INSERT INTO relay_delivery_effects VALUES (?,?,?,'submitting',1,NULL,NULL,?)
            ON CONFLICT(id) DO UPDATE SET status='submitting',attempts=attempts+1,error=NULL,updated=excluded.updated''',
            (ident,event_id,digest,time.time()))
    try:
        response=transport()
        if not isinstance(response,dict) or not response.get('message_id'):raise UncertainDelivery('Transport returned no confirmed message identity.')
    except BaseException as exc:
        from . import channel_policy
        # Explicit transport refusal means no accepted send. An ambiguous I/O
        # failure or process interruption is never an automatic retry grant.
        from .bridge import TelegramError
        rejected=isinstance(exc,(channel_policy.ChannelPaused,FileNotFoundError)) or isinstance(exc,TelegramError) and exc.status in (400,401,403,413,429)
        with transaction(state.db):
            state.db.execute('UPDATE relay_delivery_effects SET status=?,error=?,updated=? WHERE id=?',
                ('rejected' if rejected else 'uncertain',type(exc).__name__+': '+str(exc),time.time(),ident))
        raise
    with transaction(state.db):
        state.db.execute("UPDATE relay_delivery_effects SET status='confirmed',receipt=?,updated=? WHERE id=?",(json.dumps(response),time.time(),ident))
    return response


def uncertain(db, ident):
    row=db.execute('SELECT status FROM relay_delivery_effects WHERE id=?',(ident,)).fetchone()
    return bool(row and row['status'] in ('submitting','uncertain'))
