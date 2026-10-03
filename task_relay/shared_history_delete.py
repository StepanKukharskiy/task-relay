"""Forget owned Telegram conversation text after a standalone job deletion.

Delivery identities, deduplication records, reply routes, and external messages
stay intact. Legacy receipts cannot be backfilled by guessing from prefixes.
"""
from contextlib import closing
import hashlib
import json
import re
import time

from orchestrator.storage import transaction
from .job_delete import _database, _ids, _table
from .relay_paths import PATHS


class SharedHistoryDeleteError(ValueError):
    pass


def _record(db, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'job-[a-f0-9]{24}', job_id):
        raise SharedHistoryDeleteError('Choose an exact deleted Relay job.')
    if not _table(db, 'relay_delete_receipts'):
        raise SharedHistoryDeleteError('No Relay deletion receipt exists.')
    receipt = db.execute('SELECT * FROM relay_delete_receipts WHERE id=?',
                         (job_id,)).fetchone()
    if receipt is None:
        raise SharedHistoryDeleteError('No Relay deletion receipt exists for this job.')
    if 'shared_history' not in receipt.keys() or not receipt['shared_history']:
        raise SharedHistoryDeleteError(
            'This older deletion has no exact shared-delivery ownership record.')
    try:
        frozen = json.loads(receipt['shared_history'])
    except (TypeError, ValueError):
        raise SharedHistoryDeleteError('The shared-delivery ownership record is unreadable.') from None
    if (not isinstance(frozen, dict) or
            set(frozen) != {'version','channel','event_ids','request_ids'} or
            frozen['version'] != 2 or frozen['channel'] != 'telegram' or
            not isinstance(frozen['event_ids'], list) or not frozen['event_ids'] or
            len(frozen['event_ids']) != len(set(frozen['event_ids'])) or
            any(not isinstance(v,str) or not v or len(v)>300 for v in frozen['event_ids']) or
            not isinstance(frozen['request_ids'],list) or not frozen['request_ids'] or
            len(frozen['request_ids']) != len(set(frozen['request_ids'])) or
            any(type(v) is not int or v <= 0 for v in frozen['request_ids'])):
        raise SharedHistoryDeleteError('Only exact sent Telegram history is supported.')
    return receipt, frozen


def _graph(db, job_id):
    receipt, frozen = _record(db, job_id)
    event_ids = set(frozen['event_ids'])
    request_ids = set(frozen['request_ids'])
    outbox = _ids(db, 'outbox', 'id', event_ids)
    parts = _ids(db, 'outbox_parts', 'event_id', event_ids)
    routes = _ids(db, 'relay_event_channels', 'event_id', event_ids)
    media = _ids(db, 'media_outbox', 'event_id', event_ids)
    chats = _ids(db, 'orchestrator_chats', 'id', request_ids)
    incoming = _ids(db, 'incoming', 'id', request_ids)
    request_routes = _ids(db, 'relay_request_channels', 'request_id', request_ids)
    blockers = []
    if receipt['status'] != 'complete':
        blockers.append('Private job cleanup is still pending.')
    if len(outbox) != len(event_ids):
        blockers.append('A retained delivery is missing.')
    if len(chats) != len(request_ids):
        blockers.append('A retained conversation request is missing.')
    if any(r['status'] not in ('answered','failed','completed') for r in chats):
        blockers.append('A retained conversation request is active or uncertain.')
    if len(incoming) != len(request_ids) or any(
            r['status'] != 'handled' or r['thread_id'] is not None for r in incoming):
        blockers.append('A retained request lacks a completed deduplication record.')
    if len(request_routes) != len(request_ids) or any(
            r['channel'] != 'telegram' for r in request_routes):
        blockers.append('A retained request belongs to another channel.')
    if any(r['sent'] != 1 or r['thread_id'] is not None for r in outbox):
        blockers.append('A retained delivery is pending or belongs to a task.')
    if any(r['sent'] != 1 for r in parts):
        blockers.append('A retained delivery part is pending.')
    if any(r['channel'] != 'telegram' for r in routes):
        blockers.append('A retained delivery has another channel.')
    if any(r['status'] != 'sent' for r in media):
        blockers.append('A retained media delivery is pending or uncertain.')
    for ident in request_ids:
        prefix = 'orchestrator:'+str(ident)
        if db.execute('SELECT 1 FROM outbox WHERE (id=? OR substr(id,1,?)=?) '
                      'AND id NOT IN ('+','.join('?' for _ in event_ids)+') LIMIT 1',
                      (prefix,len(prefix)+1,prefix+':',*sorted(event_ids))).fetchone():
            blockers.append('A conversation request has an unrecorded delivery.')
            break
        if _table(db,'browser_research_requests') and db.execute(
                'SELECT 1 FROM browser_research_requests WHERE source=? LIMIT 1',
                (prefix,)).fetchone():
            blockers.append('Browser research still references a conversation request.')
            break
    if _table(db, 'relay_shared_history_receipts') and db.execute(
            'SELECT 1 FROM relay_shared_history_receipts WHERE job_id=?',
            (job_id,)).fetchone():
        blockers.append('Local delivery text was already deleted.')
    # Any new typed event owner outside the acknowledgement/routing tables is a
    # cross-job or interactive dependency. Never infer it from an event prefix.
    allowed = {'outbox','outbox_parts','relay_event_channels','media_outbox'}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table in allowed:
            continue
        columns = {r[1] for r in db.execute('PRAGMA table_info("'+table.replace('"','""')+'")')}
        if 'event_id' in columns and _ids(db, table, 'event_id', event_ids):
            blockers.append('Another Relay record references a retained delivery.')
            break
    allowed_requests = {'orchestrator_chats','incoming','relay_request_channels'}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table in allowed_requests:
            continue
        columns = {r[1] for r in db.execute('PRAGMA table_info("'+table.replace('"','""')+'")')}
        if any(_ids(db,table,column,request_ids) for column in ('request_id','job_id','source_request_id')
               if column in columns):
            blockers.append('Another Relay record references a retained conversation request.')
            break
    if _table(db, 'relay_delete_receipts'):
        for other in db.execute('SELECT id,shared_history FROM relay_delete_receipts WHERE id!=? '
                                'AND shared_history IS NOT NULL', (job_id,)):
            try:
                data = json.loads(other['shared_history'])
            except (TypeError, ValueError):
                blockers.append('Another deletion has unreadable delivery ownership.')
                break
            if isinstance(data,dict) and (event_ids.intersection(data.get('event_ids', ())) or
                                          request_ids.intersection(data.get('request_ids', ()))):
                blockers.append('Another deleted job shares channel history.')
                break
    digest = hashlib.sha256()
    digest.update(json.dumps(list(receipt),default=str,ensure_ascii=True).encode()+b'\n')
    for table, records in (('outbox',outbox),('outbox_parts',parts),
                           ('orchestrator_chats',chats),
                           ('incoming',incoming),('relay_request_channels',request_routes),
                           ('relay_event_channels',routes),('media_outbox',media)):
        for row in records:
            digest.update(json.dumps([table,list(row)],default=str,
                                     ensure_ascii=True).encode()+b'\n')
    return {'id':job_id,'channel':'telegram','events':len(event_ids),
            'requests':len(request_ids),
            'parts':len(parts),'blockers':sorted(set(blockers)),
            'digest':digest.hexdigest(),'external_messages_preserved':True,
            'delivery_receipts_preserved':True,
            '_outbox':outbox,'_parts':parts,'_chats':chats,
            '_event_ids':sorted(event_ids),'_request_ids':sorted(request_ids)}


def preview(job_id, paths=PATHS):
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        result = _graph(db,job_id)
        return {k:v for k,v in result.items() if not k.startswith('_')}


def available(paths=PATHS):
    if not paths.state.is_file():
        return []
    with closing(_database(paths)) as db:
        if not _table(db,'relay_delete_receipts') or 'shared_history' not in {
                r[1] for r in db.execute('PRAGMA table_info(relay_delete_receipts)')}:
            return []
        result = []
        for row in db.execute('SELECT id FROM relay_delete_receipts WHERE shared_history IS NOT NULL '
                              'AND status=\'complete\' ORDER BY created DESC'):
            try:
                review = _graph(db,row['id'])
            except SharedHistoryDeleteError:
                continue
            if not review['blockers']:
                result.append({'id':row['id'],'events':review['events'],
                               'channel':review['channel']})
        return result


def forget(job_id, digest, paths=PATHS):
    if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):
        raise SharedHistoryDeleteError('Review exact local delivery text first.')
    with closing(_database(paths,writable=True)) as db:
        with transaction(db):
            db.execute('''CREATE TABLE IF NOT EXISTS relay_shared_history_receipts(
                job_id TEXT PRIMARY KEY,digest TEXT NOT NULL,created REAL NOT NULL,
                event_ids TEXT NOT NULL,request_ids TEXT NOT NULL,
                events INTEGER NOT NULL,parts INTEGER NOT NULL,requests INTEGER NOT NULL)''')
            existing = db.execute('SELECT digest FROM relay_shared_history_receipts '
                                  'WHERE job_id=?',(job_id,)).fetchone()
            if existing:
                if existing['digest'] != digest:
                    raise SharedHistoryDeleteError('History confirmation is stale.')
                return {'id':job_id,'status':'complete'}
            result = _graph(db,job_id)
            if result['digest'] != digest:
                raise SharedHistoryDeleteError('Local delivery history changed. Review it again.')
            if result['blockers']:
                raise SharedHistoryDeleteError('History deletion blocked: '+' '.join(result['blockers']))
            db.executemany("UPDATE outbox SET text='' WHERE rowid=?",
                           ((r['_delete_rowid'],) for r in result['_outbox']))
            db.executemany("UPDATE outbox_parts SET text='' WHERE rowid=?",
                           ((r['_delete_rowid'],) for r in result['_parts']))
            db.executemany('DELETE FROM orchestrator_chats WHERE rowid=?',
                           ((r['_delete_rowid'],) for r in result['_chats']))
            db.execute('''INSERT INTO relay_shared_history_receipts
                VALUES (?,?,?,?,?,?,?,?)''',
                (job_id,digest,time.time(),json.dumps(result['_event_ids']),
                 json.dumps(result['_request_ids']),
                 result['events'],result['parts'],result['requests']))
    return {'id':job_id,'status':'complete','events':result['events'],
            'parts':result['parts'],'requests':result['requests']}
