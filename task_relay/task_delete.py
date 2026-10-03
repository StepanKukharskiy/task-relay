"""Guarded deletion of one Relay-managed provider conversation.

Only Relay-local records with exact task ownership are removed. External provider
conversations, channel messages and native/input files are outside this action.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from orchestrator.storage import transaction
from .job_delete import _database, _ids, _table
from .relay_paths import PATHS


class TaskDeleteError(ValueError):
    pass


def _independent_media(db, task_id, jobs, rows, add, blockers, retained):
    """Own one direct media request, never a pipeline stage or reused task."""
    linked = []
    for kind in ('image','video'):
        linked.extend((kind, row) for row in _ids(db, 'orchestrator_'+kind+'_requests',
                                                   'task_id', {task_id}))
    if not linked:
        return set()
    if len(linked) != 1 or len(jobs) != 1:
        blockers.append('A media task has multiple requests or turns.')
        return set()
    kind, media = linked[0]
    request_id = media['job_id']
    if media['backend_job_id'] != jobs[0]['id'] or not isinstance(request_id, int):
        blockers.append('Media request and provider turn disagree.')
        return set()
    if _ids(db,'relay_pipeline_task_links','task_id',{task_id}):
        blockers.append('A saved pipeline owns this media task.')
        return set()
    chat = _ids(db,'orchestrator_chats','id',{request_id})
    dispatch = _ids(db,'capability_dispatches','job_id',{request_id})
    incoming = _ids(db,'incoming','id',{request_id})
    try:
        action = json.loads(dispatch[0]['action']) if len(dispatch) == 1 else {}
    except (ValueError, TypeError):
        action = {}
    run = _ids(db,'gemini_runs','job_id',{jobs[0]['id']})
    if (len(chat) != 1 or chat[0]['status'] != 'answered' or chat[0]['focus'] is not None or
            len(dispatch) != 1 or dispatch[0]['thread_id'] != task_id or
            dispatch[0]['executor'] != 'orchestrator_'+kind+'_requests' or
            action.get('kind') != 'generate_'+kind or
            len(incoming) != 1 or incoming[0]['thread_id'] is not None or
            incoming[0]['status'] != 'handled' or
            len(run) != 1 or run[0]['capability'] != kind):
        blockers.append('Media request lacks a complete single-owner dispatch chain.')
        return set()
    if any(_ids(db,table,column,{request_id}) for table,column in (
            ('orchestrator_proposals','job_id'),('reference_packs','job_id'),
            ('production_plans','request_id'),('relay_pipeline_requests','request_id'),
            ('orchestrator_guide_choices','job_id'),('orchestrator_chat_errors','job_id'))):
        blockers.append('Another stage or unresolved decision uses this media request.')
        return set()
    if (_table(db,'browser_research_requests') and
            db.execute("SELECT 1 FROM browser_research_requests WHERE source=? LIMIT 1",
                       ('orchestrator:'+str(request_id),)).fetchone()):
        blockers.append('Browser research uses this media request.')
        return set()
    for batch in _ids(db,'relay_attachment_batches','request_id',{request_id}):
        members = _ids(db,'relay_attachment_members','batch',{batch['id']})
        uploads = _ids(db,'production_uploads','id',{m['upload_id'] for m in members})
        if (not members or len(uploads) != len(members) or
                batch['notified_count'] != len(members) or
                any(u['status'] not in ('ready','used','replaced') for u in uploads)):
            blockers.append('An attachment batch is unfinished or missing its saved uploads.')
            return set()
        # Preserve the batch to prevent a late album member from queueing the
        # original caption again. Its request ID is retained in the tombstone.
        retained.extend((table,row) for table,records in (
            ('relay_attachment_batches',[batch]),
            ('relay_attachment_members',members),('production_uploads',uploads))
                        for row in records)
    for table, column in (('orchestrator_chats','id'),
                          ('capability_dispatches','job_id'),
                          ('orchestrator_'+kind+'_requests','job_id'),
                          ('incoming','id'),('relay_request_channels','request_id')):
        add(table,column,{request_id})
    event_ids = set()
    for prefix in ('orchestrator:','image-request:','video-request:',
                   'capability-request:','routed:','uncertain:'):
        exact = prefix+str(request_id)
        event_ids.add(exact)
        event_ids.update(row['id'] for row in db.execute(
            'SELECT id FROM outbox WHERE id=? OR substr(id,1,?)=?',
            (exact,len(exact)+1,exact+':')))
    add('outbox','id',event_ids)
    add('kv','key',{kind+'-artifact-inputs:'+str(request_id),
                    'orchestrator-attachments:'+str(request_id)})
    return {request_id}


def _rows(db, task_id, paths):
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{1,179}', task_id):
        raise TaskDeleteError('Choose an exact Relay task.')
    watched = _ids(db, 'watched', 'id', {task_id})
    if len(watched) != 1:
        raise TaskDeleteError('That task is no longer in Relay history. Refresh the list.')
    rows = {'watched': watched}
    retained = []
    def add(table, column, values):
        found = _ids(db, table, column, values)
        combined = {r['_delete_rowid']: r for r in rows.get(table, ())}
        combined.update({r['_delete_rowid']: r for r in found})
        rows[table] = list(combined.values())
        return found

    backend = add('backend_tasks', 'id', {task_id})
    jobs = add('backend_jobs', 'thread_id', {task_id})
    job_ids = {r['id'] for r in jobs}
    update_ids = {r['update_id'] for r in jobs}
    blockers = []
    if len(backend) != 1:
        blockers.append('Only Relay-managed provider tasks can be deleted here.')
    if watched[0]['status'] != 'idle':
        blockers.append('Task is active or uncertain.')
    if any(r['status'] != 'completed' for r in jobs):
        blockers.append('A provider turn is unfinished, failed, or uncertain.')
    for table, column in (
        ('watch_checkpoints','thread_id'), ('task_emojis','thread_id'),
        ('gemini_models','thread_id'), ('incoming','thread_id'),
        ('incoming_files','thread_id'), ('artifacts','thread_id'),
        ('gemini_history','thread_id'), ('api_history','thread_id'),
        ('outbox','thread_id'), ('media_outbox','thread_id'),
        ('messages','thread_id'), ('desktop_commands','task_id'),
        ('desktop_creations','task_id'), ('relay_channel_bindings','entity')):
        add(table, column, {task_id})
    media_requests = _independent_media(db, task_id, jobs, rows, add, blockers, retained)
    for table in ('gemini_runs','gemini_history','gemini_tool_runs',
                  'api_runs','api_history','api_tool_calls','api_steps'):
        add(table, 'job_id', job_ids)
    events = {r['id'] for r in rows.get('outbox', ())}
    for table in ('outbox_parts','relay_event_channels','media_outbox'):
        add(table, 'event_id', events)
    if any(r['kind'] != 'task' for r in rows.get('relay_channel_bindings', ())):
        blockers.append('A channel binding has another owner.')
    if any(r['replaying'] for r in rows.get('watch_checkpoints', ())):
        blockers.append('Task history is replaying.')
    if any(r['status'] not in ('completed','handled') for r in rows.get('incoming', ())):
        blockers.append('An incoming request is unfinished or uncertain.')
    if any(r['status'] not in ('completed','failed','forgotten') for r in rows.get('incoming_files', ())):
        blockers.append('An input transfer is unfinished or uncertain.')
    if any(not r['sent'] for r in rows.get('outbox', ())):
        blockers.append('A channel delivery is pending.')
    if any(not r['sent'] for r in rows.get('outbox_parts', ())):
        blockers.append('A channel delivery part is pending.')
    if any(r['status'] != 'sent' for r in rows.get('media_outbox', ())):
        blockers.append('A media delivery is pending or unresolved.')
    if any(r['status'] not in ('accepted','rejected') for r in rows.get('desktop_commands', ())):
        blockers.append('A desktop instruction is unfinished or uncertain.')
    if any(r['status'] not in ('accepted','rejected') for r in rows.get('desktop_creations', ())):
        blockers.append('Task creation is unfinished or uncertain.')
    if any(r['stage'] != 'complete' for r in rows.get('gemini_runs', ())):
        blockers.append('A Gemini provider run is unfinished or uncertain.')
    if any(r['stage'] != 'complete' for r in rows.get('api_runs', ())):
        blockers.append('An API provider run is unfinished or uncertain.')
    if any(r['stage'] != 'complete' for r in rows.get('gemini_tool_runs', ())):
        blockers.append('A Gemini tool run is unfinished or uncertain.')
    if any(r['job_id'] not in job_ids for r in rows.get('artifacts', ()) if r['job_id']):
        blockers.append('An artifact belongs to another provider turn.')
    if any(r['job_id'] not in job_ids for r in rows.get('gemini_history', ()) + rows.get('api_history', ())):
        blockers.append('Provider history belongs to another task.')
    if backend:
        provider = backend[0]['backend']
        required = ('gemini_runs','gemini_history') if provider == 'gemini' else (
            ('api_runs','api_history') if provider in ('openai','qwen','deepseek','openrouter') else ())
        if any({r['job_id'] for r in rows.get(table, ())} != job_ids for table in required):
            blockers.append('A completed provider turn has missing history records.')

    # Selection is a preference, not a second owner. Remove only exact pointers;
    # other preference references make the task ineligible.
    for key, value in db.execute('SELECT key,value FROM kv') if _table(db, 'kv') else ():
        if key in {prefix+str(r) for r in media_requests for prefix in
                   ('image-artifact-inputs:','video-artifact-inputs:',
                    'orchestrator-attachments:')}:
            continue
        if task_id not in key and task_id not in value:
            continue
        if (key in ('selected','messages:selected') and value == json.dumps(task_id)) or key == 'gemini-reply-capability:' + task_id:
            add('kv', 'key', {key})
        else:
            blockers.append('Another saved preference references this task.')

    # Unknown typed references cannot be deleted or silently orphaned. A linked
    # pipeline/media stage, speech route, workflow or active approval blocks here.
    references = (('thread_id',{task_id}),('task_id',{task_id}),
                  ('source_id',{task_id}),('entity',{task_id}),
                  ('job_id',job_ids),('job_id',media_requests),
                  ('backend_job_id',job_ids),
                  ('request_id',media_requests),
                  ('event_id',events),('update_id',update_ids),
                  ('update_id',media_requests))
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        columns = {r[1] for r in db.execute('PRAGMA table_info("' + table.replace('"','""') + '")')}
        selected = {r['_delete_rowid'] for r in rows.get(table, ())}
        selected.update(r['_delete_rowid'] for t,r in retained if t == table)
        for column, values in references:
            if column not in columns or not values:
                continue
            if any(r['_delete_rowid'] not in selected for r in _ids(db, table, column, values)):
                blockers.append('Another Relay record references this task or provider turn.')
                break
    # The routing map is local to Relay; external channel messages survive. Do
    # not remove a route that another local card or deletion request still uses.
    for route in rows.get('messages', ()):
        for table in ('approval_messages','production_plan_messages','production_selection_messages',
                      'production_control_messages','production_replacement_messages',
                      'production_visual_review_messages','orchestrator_messages','provider_deletions'):
            if not _table(db, table): continue
            if db.execute('SELECT 1 FROM "' + table + '" WHERE chat_id=? AND message_id=? LIMIT 1',
                          (route['chat_id'],route['message_id'])).fetchone():
                blockers.append('A shared channel record uses this message route.')
                break
    # An explicit artifact reference in another plan is a cross-job dependency.
    artifact_ids = {r['id'] for r in rows.get('artifacts', ())}
    if artifact_ids and _table(db, 'production_plans'):
        for plan in db.execute('SELECT context,options FROM production_plans'):
            if any(ident in (plan['context'] or '') or ident in (plan['options'] or '') for ident in artifact_ids):
                blockers.append('A production plan references a task artifact.')
                break

    cleanup = []
    expected = {}
    for job in jobs:
        ident = job['id']
        if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', ident):
            blockers.append('A provider job ID is unsafe for cleanup.')
            continue
        expected[ident] = {
            paths.data/'results'/(ident+'.md'),
            paths.data/'gemini-runs'/(ident+'.input.json'),
            paths.data/'gemini-runs'/(ident+'.json'),
            paths.data/'api-runs'/(ident+'.json'),
            paths.data/'api-runs'/(ident+'.context.json')}
    locations = set()
    for table, column in (('backend_jobs','result_path'),('gemini_runs','response_path'),
                          ('gemini_history','input_path'),('gemini_history','response_path'),
                          ('gemini_tool_runs','response_path'),('api_runs','response_path')):
        for row in rows.get(table, ()):
            path = Path(row[column]) if row[column] else None
            ident = row['id'] if table == 'backend_jobs' else row['job_id']
            if path and path not in expected.get(ident, set()):
                blockers.append('A provider trace has an unclassified path.')
            elif path:
                locations.add(path)
    for ident, candidates in expected.items():
        locations.update(path for path in candidates if path.is_file())
        for directory in (paths.data/'results',paths.data/'gemini-runs',paths.data/'api-runs'):
            if directory.is_symlink():
                blockers.append('A provider trace directory is a symbolic link.')
                continue
            if directory.is_dir():
                for path in directory.glob(ident+'.*'):
                    if path not in candidates:
                        blockers.append('A provider turn has an unclassified private trace.')
    for path in sorted(locations):
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
            blockers.append('A provider trace path is a symbolic link.')
        elif path.exists() and not path.is_file():
            blockers.append('A provider trace is not a regular file.')
        else:
            cleanup.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None})

    digest = hashlib.sha256()
    for table in sorted(rows):
        unique = {r['_delete_rowid']:r for r in rows[table]}
        rows[table] = list(unique.values())
        for row in sorted(unique.values(), key=lambda r:r['_delete_rowid']):
            digest.update(json.dumps([table,list(row)],default=str,ensure_ascii=True).encode()+b'\n')
    digest.update(json.dumps(cleanup,sort_keys=True).encode()+b'\n')
    for table,row in sorted(retained,key=lambda item:(item[0],item[1]['_delete_rowid'])):
        digest.update(json.dumps(['retained',table,list(row)],default=str,ensure_ascii=True).encode()+b'\n')
    return {'id':task_id,'title':watched[0]['title'],'backend':backend[0]['backend'] if backend else 'external',
            'turns':len(jobs),'counts':{table:len(found) for table,found in rows.items() if found},
            'blockers':sorted(set(blockers)),'digest':digest.hexdigest(),
            'media_requests':sorted(media_requests),
            'retained_attachment_batches':sum(table == 'relay_attachment_batches' for table,_ in retained),
            'external_messages_preserved':True,'native_files_preserved':True,
            '_rows':rows,'_cleanup':cleanup}


def preview(task_id, paths=PATHS):
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        result = _rows(db, task_id, paths)
        return {k:v for k,v in result.items() if not k.startswith('_')}


def _receipt(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_task_delete_receipts(
        id TEXT PRIMARY KEY,digest TEXT NOT NULL,status TEXT NOT NULL,
        created REAL NOT NULL,error TEXT,files TEXT NOT NULL,
        media_requests TEXT NOT NULL DEFAULT '[]')''')
    if 'media_requests' not in {r[1] for r in db.execute('PRAGMA table_info(relay_task_delete_receipts)')}:
        db.execute("ALTER TABLE relay_task_delete_receipts ADD COLUMN media_requests TEXT NOT NULL DEFAULT '[]'")


def delete(task_id, digest, paths=PATHS):
    if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise TaskDeleteError('Review the exact task before deleting it.')
    with closing(_database(paths,writable=True)) as db:
        with transaction(db):
            _receipt(db)
            prior = db.execute('SELECT digest FROM relay_task_delete_receipts WHERE id=?',(task_id,)).fetchone()
            if prior:
                if prior['digest'] != digest: raise TaskDeleteError('Deletion confirmation is stale.')
            else:
                result = _rows(db, task_id, paths)
                if result['digest'] != digest: raise TaskDeleteError('Task changed. Review it again.')
                if result['blockers']: raise TaskDeleteError('Deletion blocked: '+' '.join(result['blockers']))
                for table, records in result['_rows'].items():
                    db.executemany('DELETE FROM "'+table.replace('"','""')+'" WHERE rowid=?',
                                   ((r['_delete_rowid'],) for r in records))
                db.execute('''INSERT INTO relay_task_delete_receipts
                    (id,digest,status,created,error,files,media_requests)
                    VALUES (?,?,?, ?,NULL,?,?)''',
                    (task_id,digest,'cleanup_pending',time.time(),
                     json.dumps(result['_cleanup'],sort_keys=True),
                     json.dumps(result['media_requests'])))
    return recover(task_id, paths)


def recover(task_id, paths=PATHS):
    with closing(_database(paths,writable=True)) as db:
        _receipt(db)
        receipt = db.execute('SELECT * FROM relay_task_delete_receipts WHERE id=?',(task_id,)).fetchone()
        if not receipt: raise TaskDeleteError('No task deletion receipt exists.')
        if receipt['status'] == 'complete': return {'id':task_id,'status':'complete'}
    try:
        for item in json.loads(receipt['files']):
            path = Path(item['path'])
            relative = path.relative_to(paths.data)
            if len(relative.parts) != 2 or relative.parts[0] not in ('results','gemini-runs','api-runs') or not re.fullmatch(r'[A-Za-z0-9-]{1,80}(?:\.input|\.context)?\.(?:md|json)',relative.name):
                raise ValueError('Provider trace receipt has an unsafe path.')
            if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
                raise ValueError('Provider trace path is a symbolic link.')
            if path.exists():
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                    raise ValueError('Provider trace changed after deletion review.')
                path.unlink()
        with closing(_database(paths,writable=True)) as db, transaction(db):
            db.execute("UPDATE relay_task_delete_receipts SET status='complete',error=NULL WHERE id=?",(task_id,))
        return {'id':task_id,'status':'complete'}
    except Exception as exc:
        with closing(_database(paths,writable=True)) as db, transaction(db):
            db.execute("UPDATE relay_task_delete_receipts SET status='cleanup_pending',error=? WHERE id=?",(str(exc),task_id))
        return {'id':task_id,'status':'cleanup_pending','error':str(exc)}


def pending(paths=PATHS):
    if not paths.state.is_file(): return []
    with closing(_database(paths)) as db:
        if not _table(db,'relay_task_delete_receipts'): return []
        return [dict(r) for r in db.execute("SELECT id,status,error FROM relay_task_delete_receipts WHERE status='cleanup_pending' ORDER BY created")]


def recover_pending(paths=PATHS):
    return [recover(row['id'],paths) for row in pending(paths)]
