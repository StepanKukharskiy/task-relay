"""Read-only local session adapters. Paths are configurable; no OS shell commands."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time

from task_relay.usage_tracker import FIELDS, health, normalize, record, unpack


def default_roots():
    codex=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    claude=Path(os.environ.get('CLAUDE_CONFIG_DIR',str(Path.home()/'.claude')))
    return [('codex',codex/'sessions'),('codex',codex/'archived_sessions'),('claude',claude/'projects')]


def timestamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError):return None


def consume(db,provider,event,meta):
    """Return updated counters while storing only usage metadata, never messages."""
    if provider=='codex':
        p=event.get('payload') or {}
        if event.get('type')=='session_meta':
            meta.update(session=p.get('id'),project=p.get('cwd'))
            if p.get('forked_from_id'):meta['fork_baseline']=True
        if event.get('type')=='turn_context':
            meta.update(model=p.get('model') or meta.get('model'),project=p.get('cwd') or meta.get('project'))
        if p.get('type')!='token_count' or not isinstance(p.get('info'),dict):return
        info=p['info'];total=info.get('total_token_usage')
        if not isinstance(total,dict):meta['missing_counters']=True;return
        counts=normalize('codex',total);previous=meta.get('counts')
        if previous is None and meta.get('fork_baseline'):
            meta['counts']=counts;return
        if previous==counts:return  # rate-limit-only updates repeat usage
        reset=previous and any(v is not None and previous.get(k) is not None and v<previous[k] for k,v in counts.items())
        if reset:
            # A compacted/rebased total is not fresh usage. Skip ambiguous reset
            # event, retain a warning, then continue from its new baseline.
            meta['counter_reset']=True;meta['counts']=counts;return
        delta={k:(v-(previous.get(k) or 0) if previous else v) if v is not None else None for k,v in counts.items()}
        meta['counts']=counts
        if not any(v for v in delta.values()):return
        # Cloned/archived history retains event timestamp and counter payload.
        # Dedup shared prefix records across files, without storing their text.
        identity=json.dumps([event.get('timestamp'),meta.get('project'),total],sort_keys=True)
        ident='codex-event:'+hashlib.sha256(identity.encode()).hexdigest()
        # Already-normalized fields are mapped back to the generic receipt names.
        raw={**delta,'reasoning_output_tokens':delta['reasoning_tokens'],'cache_write_input_tokens':delta['cache_write_tokens']}
        record(db,ident,'local_codex','codex',meta.get('model'),meta.get('project'),meta.get('session'),timestamp(event.get('timestamp')),raw)
    else:
        message=event.get('message') or {}
        if event.get('type')!='assistant' or not isinstance(message.get('usage'),dict):return
        session=event.get('sessionId') or meta.get('session')
        message_id=message.get('id');request_id=event.get('requestId')
        if not message_id:meta['missing_identity']=True;return
        # Streaming assistant fragments share a request/message ID. Prefer the
        # largest observed counters for that identity rather than summing them.
        ident='claude-message:'+hashlib.sha256(json.dumps([request_id,message_id]).encode()).hexdigest()
        usage=message['usage'];before=db.execute('SELECT counts FROM usage_events WHERE id=?',(ident,)).fetchone()
        counts=normalize('claude',usage)
        if before:
            old=json.loads(before['counts'])
            if (counts['total_tokens'] or 0)<=(old['total_tokens'] or 0):return
        record(db,ident,'local_claude','claude',message.get('model'),event.get('cwd'),session,timestamp(event.get('timestamp')),usage)


def collect_local(db,roots,max_bytes=32000000):
    if not 1<=max_bytes<=2000000000:raise ValueError('Refresh byte budget must be 1..2,000,000,000.')
    remaining=max_bytes
    for provider,root in roots:
        root=Path(root).expanduser()
        if not root.is_dir() or root.is_symlink():
            with db:health(db,str(root),{'status':'unavailable','provider':provider})
            continue
        files=sorted((p for p in root.rglob('*.jsonl') if not p.is_symlink()),key=lambda p:p.stat().st_mtime,reverse=True)
        pending=0;errors=0;warnings=set()
        for path in files:
            try:
                st=path.stat();identity=str(st.st_dev)+':'+str(st.st_ino)
                old=db.execute('SELECT * FROM usage_cursors WHERE path=?',(str(path),)).fetchone()
                offset=old['offset'] if old else 0;meta=unpack(old['metadata'],{}) if old else {}
                if old and (old['identity']!=identity or st.st_size<offset or (st.st_size==offset and st.st_mtime!=old['modified'])):
                    offset=0;meta={};warnings.add('rotated_or_rewritten')
                if remaining<=0:pending+=max(0,st.st_size-offset);continue
                with path.open('rb') as stream,db:
                    stream.seek(offset);budget=min(remaining,8000000)
                    while budget>0:
                        start=stream.tell();line=stream.readline(min(1000000,max(0,st.st_size-start)))
                        if not line:break
                        used=len(line);budget-=used;remaining-=used
                        if not line.endswith(b'\n'):
                            if stream.tell()>=st.st_size:
                                stream.seek(start);break  # incomplete append; read it later
                            meta['skipping_line']=True;continue
                        if meta.pop('skipping_line',False):continue
                        # Ignore text/tool/image records before JSON decoding.
                        if not any(tag in line for tag in (b'"token_count"',b'"session_meta"',b'"turn_context"',b'"usage"')):continue
                        try:
                            event=json.loads(line)
                            if isinstance(event,dict):consume(db,provider,event,meta)
                        except (ValueError,TypeError,KeyError,AttributeError):errors+=1
                    offset=stream.tell()
                    db.execute('INSERT OR REPLACE INTO usage_cursors VALUES (?,?,?,?,?,?)',
                        (str(path),identity,offset,json.dumps(meta),st.st_size,st.st_mtime))
                pending+=max(0,st.st_size-offset)
                warnings.update(k for k in ('counter_reset','missing_counters','missing_identity','fork_baseline') if meta.get(k))
            except OSError:errors+=1
        with db:health(db,str(root),{'provider':provider,'status':'partial' if pending or errors or warnings else 'read',
                                   'files':len(files),'pending_bytes':pending,'errors':errors,'warnings':sorted(warnings)})
