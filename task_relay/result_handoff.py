"""Committed result exports and idempotent handoffs, independent of model routing."""
import hashlib
import json
import logging
from pathlib import Path
from orchestrator.storage import transaction
from . import workflow_files as files


def initialize(db):
    # Existing installations must not send a backlog of historical completions.
    db.execute('CREATE TABLE IF NOT EXISTS result_handoff_epoch (id INTEGER PRIMARY KEY, after_created REAL NOT NULL)')
    db.execute('INSERT OR IGNORE INTO result_handoff_epoch SELECT 1,COALESCE(max(created),0) FROM production_decisions')


def channel_for(state,run):
    r=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    return r[0] if r else 'telegram'


def ancestry(state,run):
    """Display ancestry only. Never attaches or advances execution stages."""
    runs=set();plans=set();todo=[('run',run)];root=run
    while todo:
        kind,ident=todo.pop()
        seen=runs if kind=='run' else plans
        if ident in seen:continue
        if len(runs)+len(plans)>=500:raise ValueError('Result ancestry exceeds export limit.')
        seen.add(ident)
        if kind=='run':
            if channel_for(state,ident)!=getattr(state,'channel','telegram'):raise ValueError('Results belong to another channel.')
            todo.extend(('plan',r[0]) for r in state.db.execute('SELECT id FROM production_plans WHERE run=?',(ident,)))
            for table in ('production_stage_links','production_continuations'):
                todo.extend(('run',r[0]) for r in state.db.execute('SELECT parent FROM '+table+' WHERE child=?',(ident,)))
        else:
            r=state.db.execute('SELECT run,parent_id,channel FROM production_plans WHERE id=?',(ident,)).fetchone()
            if not r:raise ValueError('Result plan ancestry is missing.')
            if r['channel']!=getattr(state,'channel','telegram'):raise ValueError('Result plan belongs to another channel.')
            if r['run']:todo.append(('run',r['run']))
            if r['parent_id']:todo.append(('plan',r['parent_id']))
            else:root=ident
    return root,runs,plans


def snapshot(state,run):
    if state.db.in_transaction:raise ValueError('Export results after commit.')
    from orchestrator.runtime import Runtime
    from .production_control import root as runtime_root
    with transaction(state.db,write=False):
        identity,runs,plans=ancestry(state,run)
        row=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()
        if not row:raise ValueError('Missing result production.')
        plan=json.loads(row['plan']);status=Runtime(runtime_root(state),connection=state.db).status(run)['status']
        original=state.db.execute('SELECT request FROM production_plans WHERE id=?',(identity,)).fetchone()
        pid='job-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
        stage=dict(id='results',position=0,status=status,result='',sources=[],runs=sorted(runs),plans=sorted(plans),target=run)
        report=dict(format_version=2,id=pid,title=plan['brief'],request=original[0] if original else plan['brief'],status=status,
                    plan=plan,stages=[stage],artifacts=[],missing_artifacts=[])
        aids=set()
        for ident in plans:
            q=state.db.execute('SELECT context FROM production_plans WHERE id=?',(ident,)).fetchone()
            aids.update(s['artifact'] for s in json.loads(q[0]).get('sources',[]))
        return files.collect_artifacts(state,report,runs,aids)


def sync(state,run):
    owner=files.owner_for_run(state,run)
    if owner:return files.sync(state,owner['id'])
    report=snapshot(state,run);pid=report['id']
    from .host import HOST
    from .production_folders import checked_directory
    parent=checked_directory(files.folder_path(state,pid).parent)
    parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with files._safe(parent/('.'+pid+'.lock')).open('a') as stream:
        HOST.lock(stream)
        return files._sync(state,pid,report)


def saved_text(state,run):
    """Only advertise exported files whose bytes still match the selection."""
    owner=files.owner_for_run(state,run)
    ident=owner['id'] if owner else 'job-'+hashlib.sha256(ancestry(state,run)[0].encode()).hexdigest()[:24]
    root=files.folder_path(state,ident)
    marker=files._inside(root,'.relay-workflow.json')
    if not marker.is_file():return ''
    old=json.loads(marker.read_text())
    if old.get('workflow')!=ident:return ''
    selected=[]
    for a in state.db.execute('''SELECT DISTINCT a.id,a.sha256,a.bytes,a.path FROM production_decisions d
        JOIN production_artifacts a ON a.id=d.artifact JOIN production_tasks t ON t.run=d.run AND t.id=d.task
        WHERE d.run=? AND a.attempt=t.latest AND t.status='completed' ORDER BY a.path''',(run,)):
        relative=old.get('paths',{}).get(a['id'])
        if not relative:return ''
        path=files._inside(root,relative)
        if not path.is_file() or path.stat().st_size!=a['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=a['sha256']:return ''
        selected.append(str(path))
    if not selected:return ''
    return 'Selected results (on the Relay computer):\n'+'\n'.join(selected)+'\n\nAll workflow files:\n'+str(root)


def tick(state):
    """Export after commit, then record one handoff in the original channel."""
    if state.db.in_transaction:return
    from .relay_channels import ScopedState
    from .production_control import root as runtime_root
    from orchestrator.runtime import Runtime
    rt=Runtime(runtime_root(state),connection=state.db)
    # Selection is a durable handoff trigger, including runs completed by a button.
    # Limit pending completed handoffs, not recent selections. Already delivered
    # cards and partial/preparation runs must not hide an older finished result.
    rows=state.db.execute('''SELECT d.run,max(d.created) stamp FROM production_decisions d
        JOIN production_runs r ON r.id=d.run
        WHERE d.created>(SELECT after_created FROM result_handoff_epoch WHERE id=1)
          AND r.status IN ('active','completed')
          AND NOT EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=d.run AND t.status!='completed')
          AND NOT EXISTS (SELECT 1 FROM json_each(r.plan,'$.deferred_operations'))
          AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.id='production:' || d.run || ':files-ready')
        GROUP BY d.run ORDER BY stamp DESC LIMIT 20''').fetchall()
    seen=set()
    for row in rows:
        run=row['run'];scoped=ScopedState(state,channel_for(state,run))
        event='production:'+run+':files-ready'
        try:
            identity=ancestry(scoped,run)[0]
            if identity in seen:continue
            seen.add(identity)
            if state.db.execute('SELECT 1 FROM outbox WHERE id=?',(event,)).fetchone():continue
            view=rt.status(run)
            if view['status']!='completed' or json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0]).get('deferred_operations'):continue
            sync(scoped,run);text=saved_text(scoped,run)
            if not text:continue
            owner=files.owner_for_run(scoped,run)
            title=('Workflow completed — selected results are ready.' if owner and owner['status']=='completed' else
                   'Stage completed — selected results are ready.' if owner else
                   'Completed — your selected results are ready.')
            with transaction(state.db):
                if rt.status(run)['status']!='completed':continue
                state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)',(event,title+'\n\n'+text))
                state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)',(event,scoped.channel))
        except (ValueError,OSError,KeyError) as exc:
            logging.getLogger(__name__).warning('Result handoff failed for %s: %s',run,exc)
