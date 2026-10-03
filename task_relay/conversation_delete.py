"""Reviewed local deletion for terminal, standalone Desktop conversations.

Retain submission/delivery identities so deleting text cannot permit replay.
Database changes commit before private trace cleanup; retries use the receipt.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import time

from .desktop_plans import DesktopPlanError, _database
from .relay_paths import PATHS
from orchestrator.storage import transaction


class ConversationDeleteError(DesktopPlanError):
    pass


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_conversation_deletions (
        id TEXT PRIMARY KEY, request_id TEXT NOT NULL, digest TEXT NOT NULL,
        status TEXT NOT NULL, counts TEXT NOT NULL, files TEXT NOT NULL,
        error TEXT, created REAL NOT NULL, submission_sha256 TEXT)''')
    if 'submission_sha256' not in {r[1] for r in db.execute('PRAGMA table_info(desktop_conversation_deletions)')}:
        db.execute('ALTER TABLE desktop_conversation_deletions ADD COLUMN submission_sha256 TEXT')


def submission_identity(goal,constraints,project,parent,previous,mode,entry_mode,files):
    return hashlib.sha256(json.dumps([goal,constraints,project,parent,previous,mode,entry_mode,files],sort_keys=True).encode()).hexdigest()


def _ident(value):
    if not isinstance(value,str) or not re.fullmatch(r'-[1-9][0-9]{0,18}',value) or int(value)<-9223372036854775808:
        raise ConversationDeleteError('Choose a saved Desktop conversation.')
    return int(value)


def _table(db,name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _rows(db,table,column,value):
    return [dict(r) for r in db.execute('SELECT * FROM "'+table.replace('"','""')+'" WHERE "'+column+'"=? ORDER BY rowid',(value,))]


def _trace_paths(ident,paths):
    stem=hashlib.sha256(str(ident).encode()).hexdigest();folder=paths.data/'orchestrator-reads'
    candidates=[folder/(stem+suffix+'.json') for suffix in ('','-source-correction','-workflow-correction')]
    directory=folder/stem
    if directory.is_symlink() or folder.is_symlink() or paths.data.is_symlink():
        raise ConversationDeleteError('A conversation trace path is linked; inspect before deletion.')
    if directory.exists():
        candidates.extend(p for p in directory.rglob('*') if p.is_symlink() or p.is_file())
    if len(candidates)>1000:
        raise ConversationDeleteError('Conversation trace cleanup exceeds its bounded file limit.')
    result=[]
    for path in candidates:
        if any(p.is_symlink() for p in (path,*path.parents) if p!=paths.data.parent):
            raise ConversationDeleteError('A conversation trace path is linked; inspect before deletion.')
        if path.exists():
            if not path.is_file():raise ConversationDeleteError('A conversation trace is not a regular file.')
            result.append({'path':str(path.relative_to(paths.data)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return sorted(result,key=lambda item:item['path'])


def _review(db,ident,paths):
    number=_ident(ident)
    chats=_rows(db,'orchestrator_chats','id',number)
    requests=_rows(db,'desktop_plan_requests','job_id',number)
    if len(chats)!=1 or len(requests)!=1:
        raise ConversationDeleteError('That standalone Desktop conversation is unavailable.')
    row=chats[0];entry=requests[0];request_id=entry['request_id'];event='orchestrator:'+ident
    records={'orchestrator_chats':chats,'desktop_plan_requests':requests,
             'desktop_plan_inputs':_rows(db,'desktop_plan_inputs','request_id',request_id),
             'desktop_request_modes':_rows(db,'desktop_request_modes','request_id',request_id),
             'desktop_plan_preferences':_rows(db,'desktop_plan_preferences','request_id',request_id),
             'relay_request_channels':_rows(db,'relay_request_channels','request_id',number),
             'outbox':_rows(db,'outbox','id',event),'outbox_parts':_rows(db,'outbox_parts','event_id',event),
             'media_outbox':_rows(db,'media_outbox','event_id',event)}
    blockers=[]
    if (row['status'] not in ('answered','failed') or entry['status']!='accepted'):
        blockers.append('The request is active or uncertain.')
    if row['focus'] or records['desktop_request_modes']!=[{'request_id':request_id,'entry_mode':'conversation'}]:
        blockers.append('This record belongs to a job or planning stage.')
    if records['relay_request_channels']!=[{'request_id':number,'channel':'desktop'}]:
        blockers.append('Use the original channel or job controls for this record.')
    try:
        from .orchestrator_chat import response_json
        proposed=response_json(row['response']) if row['response'] else {}
        if isinstance(proposed,dict) and proposed.get('action') is not None:
            blockers.append('The conversation proposed work; inspect its job ownership first.')
    except (ValueError,TypeError):
        if row['status']!='failed':blockers.append('The saved response cannot establish a direct answer.')
    if any(r['sent']!=1 or r['thread_id'] is not None for r in records['outbox']):
        blockers.append('A delivery is pending or belongs to a task.')
    if any(r['sent']!=1 for r in records['outbox_parts']) or any(r['status']!='sent' for r in records['media_outbox']):
        blockers.append('A delivery part is pending or uncertain.')
    # A direct Desktop reply has one exact event. Any other event or typed request
    # owner is a dependency, not permission to erase another job's state.
    if db.execute('SELECT 1 FROM outbox WHERE substr(id,1,?)=? AND id!=?',(len(event)+1,event+':',event)).fetchone():
        blockers.append('An additional delivery references this conversation.')
    allowed=set(records)|{'orchestrator_chat_errors'}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table in allowed or table=='desktop_conversation_deletions':continue
        columns={r[1] for r in db.execute('PRAGMA table_info("'+table.replace('"','""')+'")')}
        if any(_rows(db,table,column,number) for column in ('request_id','job_id','source_request_id','choice_source_id') if column in columns):
            blockers.append('Another Relay record references this conversation.');break
        if 'request_id' in columns and _rows(db,table,'request_id',request_id):
            blockers.append('Another Relay record references this conversation.');break
        if 'event_id' in columns and table not in ('relay_event_channels',) and _rows(db,table,'event_id',event):
            blockers.append('Another Relay record references its delivery.');break
    records['orchestrator_chat_errors']=_rows(db,'orchestrator_chat_errors','job_id',number)
    keys=['orchestrator-presentation:','orchestrator-response-notes:','orchestrator-answer-recovery:',
          'orchestrator-workflow-correction:','orchestrator-type-correction:','orchestrator-source-correction:',
          'orchestrator-handoff-binding:','orchestrator-action-defaults:']
    records['kv']=[dict(r) for prefix in keys for r in db.execute('SELECT * FROM kv WHERE key=?',(prefix+ident,))]
    files=_trace_paths(number,paths)
    counts={table:len(rows) for table,rows in records.items()}
    digest=hashlib.sha256(json.dumps({'records':records,'files':files},sort_keys=True).encode()).hexdigest()
    inputs=records['desktop_plan_inputs'][0] if len(records['desktop_plan_inputs'])==1 else None
    if inputs is None:blockers.append('Frozen submission inputs are unavailable.')
    identity=(submission_identity(inputs['goal'],inputs['constraints_text'],entry['project'],entry['parent_id'],inputs['previous_run'],
              records['desktop_plan_preferences'][0]['research_mode'] if records['desktop_plan_preferences'] else 'suggest','conversation',
              [item['source'] for item in json.loads(inputs['manifest'])]) if inputs else None)
    return {'id':ident,'request_id':request_id,'title':row['prompt'].split('\n')[0] or row['prompt'].strip().split('\n')[0],
            'digest':digest,'counts':counts,'trace_files':len(files),'blockers':list(dict.fromkeys(blockers)),
            '_records':records,'_files':files,'_submission_sha256':identity}


def preview(ident,paths=PATHS):
    with closing(_database(paths)) as db:
        db.execute('BEGIN');value=_review(db,ident,paths)
    return {k:v for k,v in value.items() if not k.startswith('_')}


def delete(ident,digest,paths=PATHS):
    _ident(ident)
    if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):
        raise ConversationDeleteError('Review the exact conversation before deleting it.')
    with closing(_database(paths,writable=True)) as db, transaction(db):
        initialize(db)
        prior=db.execute('SELECT digest FROM desktop_conversation_deletions WHERE id=?',(ident,)).fetchone()
        if prior:
            if prior['digest']!=digest:raise ConversationDeleteError('Deletion confirmation is stale.')
        else:
            review=_review(db,ident,paths)
            if review['digest']!=digest:raise ConversationDeleteError('The conversation changed. Review it again.')
            if review['blockers']:raise ConversationDeleteError('Deletion blocked: '+' '.join(review['blockers']))
            number=int(ident);request_id=review['request_id'];event='orchestrator:'+ident
            db.execute('DELETE FROM orchestrator_chats WHERE id=?',(number,))
            db.execute('DELETE FROM orchestrator_chat_errors WHERE job_id=?',(number,))
            for row in review['_records']['kv']:db.execute('DELETE FROM kv WHERE key=?',(row['key'],))
            db.execute("UPDATE desktop_plan_requests SET prompt='',project=NULL,status='deleted',result='Conversation history deleted; submission identity retained.' WHERE request_id=?",(request_id,))
            db.execute("UPDATE desktop_plan_inputs SET goal='',constraints_text='' WHERE request_id=?",(request_id,))
            db.execute("UPDATE outbox SET text='' WHERE id=?",(event,))
            if 'entities' in {r[1] for r in db.execute('PRAGMA table_info(outbox_parts)')}:
                db.execute("UPDATE outbox_parts SET text='',entities='[]' WHERE event_id=?",(event,))
            else:db.execute("UPDATE outbox_parts SET text='' WHERE event_id=?",(event,))
            db.execute("UPDATE media_outbox SET caption='' WHERE event_id=?",(event,))
            db.execute('INSERT INTO desktop_conversation_deletions VALUES (?,?,?,?,?,?,NULL,?,?)',
                       (ident,request_id,digest,'cleanup_pending',json.dumps(review['counts']),json.dumps(review['_files']),time.time(),review['_submission_sha256']))
    return recover(ident,paths)


def recover(ident,paths=PATHS):
    _ident(ident)
    with closing(_database(paths)) as db:
        if not _table(db,'desktop_conversation_deletions'):raise ConversationDeleteError('No deletion receipt exists.')
        row=db.execute('SELECT * FROM desktop_conversation_deletions WHERE id=?',(ident,)).fetchone()
        if not row:raise ConversationDeleteError('No deletion receipt exists.')
        receipt=dict(row)
    if receipt['status']=='complete':return {'id':ident,'status':'complete'}
    try:
        stem=hashlib.sha256(ident.encode()).hexdigest()
        for item in json.loads(receipt['files']):
            relative=Path(item['path'])
            if (relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0]!='orchestrator-reads'
                    or not (relative.as_posix() in {'orchestrator-reads/'+stem+s+'.json' for s in ('','-source-correction','-workflow-correction')}
                            or len(relative.parts)>=3 and relative.parts[1]==stem)):
                raise ConversationDeleteError('Trace cleanup receipt has an unsafe path.')
            path=paths.data/relative
            if any(p.is_symlink() for p in (path,*path.parents) if p!=paths.data.parent):
                raise ConversationDeleteError('Trace cleanup path is linked.')
            if path.exists():
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                    raise ConversationDeleteError('A trace changed after deletion review.')
                path.unlink()
        status='complete';error=None
    except (ValueError,OSError,TypeError,KeyError) as exc:
        status='cleanup_pending';error=str(exc)
    with closing(_database(paths,writable=True)) as db, transaction(db):
        db.execute('UPDATE desktop_conversation_deletions SET status=?,error=? WHERE id=?',(status,error,ident))
    return {'id':ident,'status':status,**({'error':error} if error else {})}


def pending(paths=PATHS):
    if not paths.state.is_file():return []
    with closing(_database(paths)) as db:
        if not _table(db,'desktop_conversation_deletions'):return []
        return [dict(r) for r in db.execute("SELECT id,status,error FROM desktop_conversation_deletions WHERE status='cleanup_pending' ORDER BY created")]
