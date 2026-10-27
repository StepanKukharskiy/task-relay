"""Receipt-based accounting for one workflow, including its recovery lineage."""
import json
import time
from pathlib import Path
from .usage_tracker import normalize, FIELDS


def report(state,pipeline,*,now=None):
    db=state.db
    p=db.execute('SELECT * FROM relay_pipelines WHERE id=?',(pipeline,)).fetchone()
    if not p:return None
    initial=db.execute('SELECT created FROM orchestrator_chats WHERE id=?',(p['request_id'],)).fetchone()
    started=initial[0] if initial else p['created']
    from .pipeline_lineage import collect
    members=collect(db,pipeline)
    requests=members['requests'];runs=members['runs']
    plans={r['id']:dict(r) for r in db.execute('SELECT * FROM production_plans') if r['id'] in members['plans']}
    entries=[];duration=0;missing_duration=[]
    def add(ident,kind,provider,usage):
        values=usage if isinstance(usage,list) else [usage]
        if not values:values=[None]
        for index,value in enumerate(values):
            entries.append(dict(id=ident+':'+str(index),kind=kind,provider=provider,counts=normalize(provider,value)))
    from orchestrator.executors import provider_for, API_TYPES
    for a in db.execute('SELECT * FROM production_attempts'):
        if a['run'] not in runs:continue
        frozen=json.loads(a['frozen']);receipt=json.loads(a['receipt'] or '{}')
        start,end=receipt.get('started'),receipt.get('finished')
        if isinstance(start,(float,int)) and isinstance(end,(float,int)) and end>=start:duration+=end-start
        else:missing_duration.append(a['id'])
        execution=frozen.get('execution',{})
        from orchestrator.execution import REGISTRY
        metadata=REGISTRY.get(execution.get('capability'),{})
        if metadata.get('kind')=='procedure' and metadata.get('usage_source')!='public-search-journals':continue
        backend=frozen.get('backend',{})
        provider=(provider_for(backend) if backend.get('type') in API_TYPES else 'codex') if not execution else 'gemini'
        worker_usage=receipt.get('usage')
        if metadata.get('usage_source')=='public-search-journals':
            session=json.loads(a['session'] or '{}')
            control=Path(session.get('control','/nonexistent'))
            native=[]
            if control.is_relative_to(state.media_dir.parent):
                for path in sorted(control.glob('query-*/search-*.json')):
                    if path.is_symlink() or path.stat().st_size>16000000:continue
                    saved=json.loads(path.read_text());native.append(saved.get('response',{}).get('usageMetadata'))
            worker_usage=native or worker_usage or None
        add('worker:'+a['id'],'worker',provider,worker_usage)
    for call in db.execute('SELECT * FROM production_plan_calls'):
        plan=plans.get(call['plan_id'])
        if plan:add('planner:'+call['plan_id']+':'+str(call['number']),'planner',plan['provider'],json.loads(call['usage'] or '{}'))
    for request in requests:
        chat=db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(request,)).fetchone()
        if not chat:continue
        import hashlib
        path=state.media_dir.parent/'orchestrator-reads'/(hashlib.sha256(str(request).encode()).hexdigest()+'.json')
        journal=json.loads(path.read_text()) if path.is_file() and not path.is_symlink() and path.stat().st_size<=16000000 else []
        for step in journal:
            response=step.get('response',{})
            add('chat:'+str(request)+':'+str(step['step']),'orchestrator',chat['provider'],response.get('usageMetadata',response.get('usage')))
        if not journal and chat['response'] is not None:add('chat:'+str(request),'orchestrator',chat['provider'],None)
        for search_path in path.with_suffix('').glob('search-*.json'):
            if search_path.is_symlink() or search_path.stat().st_size>16000000:continue
            search=json.loads(search_path.read_text())
            add('search:'+str(request)+':'+search_path.stem,'search','gemini',search.get('response',{}).get('usageMetadata'))
    terminal=db.execute("SELECT created FROM relay_pipeline_events WHERE pipeline=? AND kind='completed' AND step IS NULL ORDER BY id DESC LIMIT 1",(pipeline,)).fetchone()
    end=terminal[0] if terminal else (time.time() if now is None else now)
    totals={field:dict(reported=sum(e['counts'][field] or 0 for e in entries),
                       unknown_records=sum(e['counts'][field] is None for e in entries)) for field in FIELDS}
    return dict(version=1,pipeline=pipeline,status=p['status'],started_at=started,finished_at=terminal[0] if terminal else None,
                elapsed_seconds=max(0,end-started),worker_seconds_reported=duration,worker_duration_unknown=missing_duration,
                runs=sorted(runs),plans=sorted(plans),records=entries,totals=totals,
                accounting='Reported input already includes cached tokens; do not add cached again. Parallel worker time is not wall time. Missing usage remains unknown; no balance or price estimate.')
