"""Read-only prompt/response/reaction indexes over existing execution journals.

Raw journals remain authoritative. An export is an observation, not completion,
acceptance, replay permission, or a backup replacing the original journals.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import time


def reference(path):
    if not path.is_file():return None
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return dict(path=str(path.resolve()),sha256=digest.hexdigest(),bytes=path.stat().st_size)


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return None


def link(ref,label):
    return '['+label+'](<'+ref['path']+'>)' if ref else 'Not recorded'


def compact(value,limit=240):
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
    return text[:limit].replace('\n',' ').replace('|','\\|').replace('<','&lt;')+('…' if len(text)>limit else '')


def model_summary(path):
    value=read(path)
    if not isinstance(value,dict):return ''
    returned=[]
    for choice in value.get('choices',[]):
        message=choice.get('message',{})
        if message.get('content'):returned.append(message['content'])
        returned.extend(t.get('function',{}) for t in message.get('tool_calls',[]))
    for candidate in value.get('candidates',[]):
        for part in candidate.get('content',{}).get('parts',[]):
            if part.get('thought'):continue
            if 'functionCall' in part:returned.append(part['functionCall'])
            elif 'text' in part:returned.append(part['text'])
    for item in value.get('output',[]):
        if item.get('type')=='function_call':returned.append({k:item.get(k) for k in ('name','arguments')})
        elif item.get('type')=='message':returned.extend(p['text'] for p in item.get('content',[]) if p.get('type')=='output_text')
    return compact(returned) if returned else 'Response recorded; see exact envelope'


def export(database,workers,run,destination):
    database=Path(database).resolve();workers=Path(workers).resolve();destination=Path(destination).resolve()
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN')
        row=db.execute('SELECT plan,status FROM production_runs WHERE id=?',(run,)).fetchone()
        if row is None:raise ValueError('Unknown run')
        attempts=[dict(r) for r in db.execute('SELECT id,task,state,frozen,receipt,error FROM production_attempts WHERE run=? ORDER BY rowid',(run,))]
        events=[{**dict(r),'data':json.loads(r['data'])} for r in db.execute('SELECT id,created,task,attempt,kind,data FROM production_events WHERE run=? ORDER BY id',(run,))]
        plan=json.loads(row['plan']);status=row['status']
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'production_tasks','production_assignments'}<=tables:
            from .runtime import run_status
            tasks=[dict(t) for t in db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY rowid',(run,))]
            specs=[json.loads(db.execute('SELECT spec FROM production_assignments WHERE id=?',(t['assignment'],)).fetchone()[0]) for t in tasks]
            status=run_status(status,tasks,specs)
        elif any(a['state']=='uncertain' for a in attempts):
            # Historical journal-only exports may not include scheduler tables.
            status='uncertain'
    report=dict(version=1,run=run,observed_at=time.time(),status=status,stored_status=row['status'],request=plan['brief'],
        plan=plan,events=events,attempts=[],limitations=[
            'Raw journals stay in their original worker folders; preserve those folders with this index.',
            'Active journals can grow after this observation; hashes identify the bytes read at export.',
            'Provider-private instructions or internal inference not exposed by the transport are not reconstructed.',
            'No recorded response does not mean no provider usage. Tool success does not mean accepted delivery.'])
    lines=['# Execution audit: '+run,'','Status at observation: **'+status+'**.','',
        'Each exchange links the exact Relay request (system instructions, context and tools), model response, and Relay tool receipts. Missing responses and uncertainty remain explicit. Codex also has a retained native thread: its native request and sent/event streams below are needed to see the actual incremental wire input. Provider-private instructions are not visible.','']
    for attempt in attempts:
        folder=(workers/attempt['id']).resolve()
        if not folder.is_relative_to(workers):raise ValueError('Attempt leaves worker root')
        frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt']) if attempt['receipt'] else None
        detail=dict(id=attempt['id'],task=attempt['task'],state=attempt['state'],backend=frozen.get('backend'),
            frozen=frozen,receipt=receipt,error=attempt['error'],exchanges=[],native=[],registered=[])
        lines.extend(['## '+attempt['task']+' — '+attempt['id'],'',
            '**'+attempt['state']+'**'+(': '+attempt['error'] if attempt['error'] else ''),''])
        for path in sorted(folder.rglob('codex-*')):
            if path.name not in ('codex-thread-request.json','codex-sent.jsonl','codex-events.jsonl','codex-usage.json','codex-auth.json','codex-wire-measurements.jsonl'):continue
            ref=reference(path);detail['native'].append(ref)
            lines.append('- '+link(ref,str(path.relative_to(folder))))
        lines.extend(['','| Exchange | Exact prompt/context/tools | Model returned | Relay reaction |','| --- | --- | --- | --- |'])
        for path in sorted(folder.glob('api-*.request.json')):
            stem=path.name.removesuffix('.request.json');number=stem.removeprefix('api-')
            response=folder/(stem+'.response.json');outcome=folder/(stem+'.outcome.json');recovery=folder/(stem+'.recovery.json')
            reactions=[]
            for tool in sorted(folder.glob('tool-'+number+'-*.json')):
                value=read(tool) or {}
                reactions.append(dict(name=value.get('name'),arguments=value.get('arguments'),result=value.get('result'),journal=reference(tool)))
            item=dict(id=stem,request=reference(path),response=reference(response),outcome=reference(outcome),recovery=reference(recovery),reactions=reactions,
                response_state='recorded' if response.is_file() else 'not_recorded',outcome_detail=read(outcome))
            detail['exchanges'].append(item)
            label='; '.join(link(t['journal'],t['name'] or 'tool')+': '+compact(t['result']) for t in reactions) or 'No tool reaction recorded'
            if item['outcome']:label+='; '+link(item['outcome'],'outcome')
            if item['recovery']:label+='; '+link(item['recovery'],'recovery')
            returned=link(item['response'],'response')+(': '+model_summary(response) if item['response'] else '')
            lines.append('| '+stem+' | '+link(item['request'],'request')+' | '+returned+' | '+label+' |')
        # Registered source/native steps may not use the agent's API envelope.
        for path in sorted(folder.rglob('*.json')):
            relative=path.relative_to(folder)
            if (path.name in ('request.json','response.json','operation.json','intent.json','outcome.json','operation-dispatch.json','operation-pending.json','operation-materialized.json','host-proposal.json','host-authorization.json','execution-outcome.json')
                    or path.name.startswith(('search-','dispatch-context-'))):
                ref=reference(path);detail['registered'].append(ref)
                lines.append('\n- Registered operation: '+link(ref,str(relative)))
        report['attempts'].append(detail)
        lines.append('')
    lines.extend(['## Controller reactions','',
        'The JSON audit preserves each controller event with its original event ID, timestamp, task, attempt and data. This includes admissions, rejection, state changes, review and recovery.',''])
    destination.mkdir(parents=True,exist_ok=True)
    # Preserve observations instead of overwriting the history while a run is live.
    ident=str(time.time_ns());record=destination/('audit-'+ident+'.json');page=destination/('audit-'+ident+'.md')
    record.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines.append(link(dict(path=str(record)),'Full machine-readable audit and controller events'))
    page.write_text('\n'.join(lines)+'\n')
    (destination/'LATEST.md').write_text('[Latest audit](<'+str(page)+'>)\n\n[JSON](<'+str(record)+'>)\n')
    summary=dict(run=run,attempts=len(attempts),exchanges=sum(len(a['exchanges']) for a in report['attempts']),markdown=str(page),json=str(record))
    (destination/'SUMMARY.json').write_text(json.dumps(summary)+'\n')
    return summary
