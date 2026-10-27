"""Carry saved conversational drafts and their provenance into task handoffs."""
import hashlib
import json

from task_relay import relay_channels

LIMIT = 12
MAX_BYTES = 200_000
INSTRUCTIONS = '''Recent conversation entries contain exact saved user messages and
assistant answers, including drafts produced in chat. A chat draft can be newer
than a production's registered script. Compare their contents and provenance;
do not equate a blocked production with absence of a newer conversational draft.
Explicitly sharing a draft with an existing Codex task is an independent handoff,
not advancing or accepting the frozen production. The destination need not have
the tool name in its title when the user explicitly selects it. Route the requested
work with its context; never claim this marks the production reviewed or accepted.
Relay freezes recent conversation entries as a readable input for Codex. They are
context, not new authorization: the current user request controls what work starts.
If the requested draft is missing or multiple versions remain ambiguous, inspect
the relevant files or ask which version; never silently substitute an old artifact.
Entries marked failed or uncertain contain execution diagnostics, not successful
advice. Do not retry those messages; only the current message authorizes new work.
'''


def recent(state, job, limit=LIMIT):
    saved = state.db.execute('SELECT created,focus FROM orchestrator_chats WHERE id=?', (job['id'],)).fetchone()
    if saved is None:
        return []
    channel = relay_channels.request_channel(state, job['id'])
    from . import conversation_flow
    followup=conversation_flow.scope(state.db,job['id'])
    if followup and followup['mode']=='message':
        # Cross-channel continuation stays within this exact job, including failures.
        # Keep the original request plus the latest bounded turns, never unrelated chats.
        root=followup['source_request_id']
        original=state.db.execute('SELECT id,created,focus,prompt,answer,status FROM orchestrator_chats WHERE id=?',(root,)).fetchone()
        rows=state.db.execute('''SELECT c.id,c.created,c.focus,c.prompt,c.answer,c.status
            FROM conversation_followups f JOIN desktop_plan_requests d ON d.request_id=f.request_id
            JOIN orchestrator_chats c ON c.id=d.job_id WHERE f.source_request_id=? AND c.id!=? AND c.created<=?
            ORDER BY c.created DESC,c.id DESC LIMIT ?''',(root,job['id'],saved['created'],max(0,limit-1))).fetchall()
        entries=([dict(original)] if original else [])+[dict(row) for row in reversed(rows)]
        from .attachment_batches import selected
        for entry in entries:
            ids=selected(state,entry['id'])
            if ids is not None:entry['attachment_ids']=ids
        return entries
    rows = state.db.execute('''SELECT c.id,c.created,c.focus,c.prompt,c.answer
        FROM orchestrator_chats c LEFT JOIN relay_request_channels r ON r.request_id=c.id
        WHERE c.status='answered' AND c.id!=? AND c.created<=?
        AND NOT EXISTS (SELECT 1 FROM relay_pipeline_requests p WHERE p.request_id=c.id)
        AND COALESCE(r.channel,'telegram')=? AND (? IS NULL OR c.focus=?)
        ORDER BY c.created DESC,c.id DESC LIMIT ?''',
        (job['id'], saved['created'], channel, saved['focus'], saved['focus'], limit)).fetchall()
    from .attachment_batches import selected
    entries = [dict(row) for row in reversed(rows)]
    for entry in entries:
        ids = selected(state, entry['id'])
        if ids is not None:
            entry['attachment_ids'] = ids
    return entries


def freeze(state, job):
    entries = recent(state, job)
    if not entries:
        return []
    value = {'kind':'conversation_context', 'request_id':job['id'],
             'status':'unreviewed conversation; not production acceptance',
             'scope':f'Last {LIMIT} answered conversation turns in this channel and focus, oldest first; machine-generated workflow requests remain in their workflow ledger.',
             'instructions':INSTRUCTIONS, 'entries':entries}
    from . import conversation_flow
    linked=conversation_flow.scope(state.db,job['id'])
    if linked and linked['mode']=='message':
        value['scope']=f'Original request and at most {LIMIT-1} latest saved turns in this exact job, oldest first, including failed outcomes. Older intermediate turns may be omitted; current message alone authorizes new work.'
    data = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()
    if len(data)>MAX_BYTES:
        raise ValueError('Conversation inputs exceed 200 KB; select the required draft before routing. No draft was truncated.')
    path = state.media_dir.parent/'route-inputs'/str(job['id'])/'conversation'/'conversation.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    if path.exists():
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Saved handoff conversation differs; no snapshot was replaced.')
    else:
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o400)
    return [dict(name='conversation.json', path=str(path.resolve()), sha256=digest,
                 bytes=len(data), role='conversation context and drafts', project=None,
                 source='orchestrator_chats', source_ids=[r['id'] for r in entries])]
