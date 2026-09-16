"""Readable workflow deliverables with immutable artifact provenance."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile

from orchestrator.storage import transaction


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()


def folder_path(state, pid):
    if not re.fullmatch(r'(?:pipe|job)-[a-f0-9]{24}', pid):
        raise ValueError('Invalid workflow folder identity.')
    from .relay_paths import PATHS
    data = state.media_dir.parent.absolute()
    base = PATHS.generated if data == PATHS.data else data/'generated'
    return base/'workflows'/pid


def location_text(state, pid):
    return 'Workflow files (on the Relay computer):\n'+str(folder_path(state, pid))


def owner_for_run(state, run):
    """Find a display folder through ancestry, without granting workflow scope."""
    from . import pipelines
    todo=[run];seen=set()
    while todo and len(seen)<500:
        current=todo.pop()
        if current in seen:continue
        seen.add(current)
        owner=pipelines.owner_of_run(state,current)
        if owner:
            channel=state.db.execute('SELECT channel FROM relay_pipelines WHERE id=?',(owner['id'],)).fetchone()[0]
            if channel==getattr(state,'channel','telegram'):return owner
            return None
        for table in ('production_stage_links','production_continuations'):
            todo.extend(r[0] for r in state.db.execute('SELECT parent FROM '+table+' WHERE child=?',(current,)))
    return None


def _safe(path):
    from .production_folders import checked_directory
    checked_directory(path.parent)
    if path.is_symlink():
        raise ValueError('Workflow copies must not contain symbolic links.')
    return path


def _put(path, data):
    """Publish a complete copy once. Keep any existing user-edited file."""
    _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        return 'present' if path.is_file() and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest() else 'user_modified'
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.copy-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        try:
            os.link(name, path)
        except FileExistsError:
            return 'user_modified'
    finally:
        os.unlink(name)
    return 'copied'


def _replace(path, data):
    _safe(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.index-')
    try:
        with os.fdopen(fd, 'wb') as stream:stream.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):os.unlink(name)


def _snapshot(state, pid):
    """Read one committed state, including the recorded recovery ancestry."""
    if state.db.in_transaction:
        raise ValueError('Export workflow files after the database commit.')
    with transaction(state.db, write=False):
        p = state.db.execute('SELECT * FROM relay_pipelines WHERE id=?', (pid,)).fetchone()
        if not p or p['channel'] != getattr(state, 'channel', 'telegram'):
            raise ValueError('Workflow is not available in this channel.')
        report = {'format_version':2, 'id':pid, 'title':p['title'], 'request':p['request'], 'status':p['status'],
                  'plan':json.loads(p['spec']), 'stages':[], 'artifacts':[], 'missing_artifacts':[]}
        from . import procedures
        procedure = procedures.run_context(state, pid)
        if procedure:report['procedure'] = procedure
        artifact_ids = set()
        runs = set()
        plans = set()
        for row in state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position', (pid,)):
            stage = dict(row)
            for k in ('choices','sources'):
                stage[k] = json.loads(stage[k] or '[]')
            stage_plans, stage_runs = set(), set()
            todo = [('run' if row['target_kind']=='production_run' else 'plan', row['target'])] if row['target_kind'] in ('production_run','plan_production') and row['target'] else []
            todo.extend(('run',r[0]) for r in state.db.execute('SELECT preparation FROM production_auto_repairs WHERE pipeline=? AND step=? AND preparation IS NOT NULL',(pid,row['id'])))
            while todo:
                kind, ident = todo.pop()
                seen = stage_runs if kind=='run' else stage_plans
                if ident in seen:
                    continue
                seen.add(ident)
                if len(stage_runs)+len(stage_plans)>500:
                    raise ValueError('Workflow ancestry exceeds the export limit.')
                if kind=='plan':
                    q = state.db.execute('SELECT run,parent_id,context FROM production_plans WHERE id=?', (ident,)).fetchone()
                    if q:
                        if q['run']:todo.append(('run',q['run']))
                        if q['parent_id']:todo.append(('plan',q['parent_id']))
                        artifact_ids.update(s['artifact'] for s in json.loads(q['context']).get('sources',[]))
                    todo.extend(('run',r[0]) for r in state.db.execute('SELECT parent FROM production_stage_links WHERE plan_id=?',(ident,)))
                else:
                    from . import pipelines
                    todo.extend(('plan',r[0]) for r in state.db.execute('SELECT id FROM production_plans WHERE run=?',(ident,)))
                    for table in ('production_stage_links','production_continuations'):
                        todo.extend(('run',r[0]) for r in state.db.execute('SELECT parent FROM '+table+' WHERE child=?',(ident,)))
                        for child in state.db.execute('SELECT child FROM '+table+' WHERE parent=? AND child IS NOT NULL',(ident,)):
                            owner=pipelines.owner_of_run(state,child[0])
                            if not owner or owner['id']==pid:todo.append(('run',child[0]))
            runs.update(stage_runs); plans.update(stage_plans)
            stage['runs'] = sorted(stage_runs); stage['plans'] = sorted(stage_plans)
            artifact_ids.update(s['artifact'] for s in stage['sources'])
            if row['target_kind']=='generate_image':
                artifact_ids.update('media-'+r[0] for r in state.db.execute("SELECT id FROM artifacts WHERE job_id=? AND role='output'",(row['target'],)))
            for r in state.db.execute('SELECT inputs FROM relay_pipeline_requests WHERE pipeline=? AND step=?', (pid,row['id'])):
                artifact_ids.update(s['artifact'] for s in json.loads(r[0]).get('sources',[]))
            report['stages'].append(stage)
        return collect_artifacts(state, report, runs, artifact_ids)


def collect_artifacts(state, report, runs, artifact_ids):
    report['productions'] = []
    for run in sorted(runs):
        artifact_ids.update(r[0] for r in state.db.execute('SELECT id FROM production_artifacts WHERE run=?',(run,)))
        tasks = [dict(t) for t in state.db.execute('SELECT id,status,latest,attempts FROM production_tasks WHERE run=?',(run,))]
        attempts = [dict(a) for a in state.db.execute('SELECT id,task,state,error,receipt,frozen FROM production_attempts WHERE run=? ORDER BY rowid',(run,))]
        for a in attempts:
            a['receipt'] = json.loads(a['receipt']) if a['receipt'] else None
            a['frozen'] = json.loads(a['frozen'])
            artifact_ids.update(i['artifact'] for i in a['frozen'].get('inputs',[]) if i.get('artifact'))
        decisions = [dict(d) for d in state.db.execute('SELECT * FROM production_decisions WHERE run=? ORDER BY id',(run,))]
        report['productions'].append({'run':run,'tasks':tasks,'attempts':attempts,'decisions':decisions})
    for aid in sorted(artifact_ids):
        if aid.startswith('media-'):
            a = state.db.execute("SELECT job_id AS run,NULL AS task,NULL AS attempt,filename AS path,'Generated media' AS purpose,sha256,size AS bytes,path AS blob FROM artifacts WHERE id=? AND role='output'",(aid[6:],)).fetchone()
        else:
            a = state.db.execute('SELECT id,run,task,attempt,path,purpose,sha256,bytes,blob FROM production_artifacts WHERE id=?',(aid,)).fetchone()
        if not a:
            report['missing_artifacts'].append(aid)
            continue
        a = dict(a);a['id']=aid
        if not re.fullmatch(r'(?:[a-f0-9]{32}|media-[a-f0-9]{20,64})', aid):
            raise ValueError('Invalid registered artifact identity.')
        name = re.sub(r'[^A-Za-z0-9._-]+','-',Path(a['path'] or 'artifact').name).strip('.-')[:150] or 'artifact'
        a['copy_path'] = 'files/'+a['id']+'/'+name
        report['artifacts'].append(a)
    return report

def _name(value):
    return re.sub(r'[^A-Za-z0-9._-]+', '-', str(value)).strip('.-')[:150] or 'artifact'


def _inside(root, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p in ('.', '..') for p in path.parts):
        raise ValueError('Invalid workflow relative path.')
    return _safe(root/path)


def _layout(report, old):
    """Derive folders from recorded stages and decisions, independently of tools."""
    versions = dict(old.get('versions', {}))
    selected = {s['artifact'] for stage in report['stages'] for s in stage['sources']}
    # Keep the latest decision for each producer/path; old acceptance remains in receipts.
    by_id = {a['id']: a for a in report['artifacts']}
    latest = {}
    for run in report['productions']:
        for d in run['decisions']:
            a = by_id.get(d['artifact'])
            if a:
                key = (a['task'], a['path'])
                if key not in latest or d['created'] > latest[key]['created']:
                    latest[key] = d
    selected_keys = {(by_id[aid]['task'], by_id[aid]['path']) for aid in selected if aid in by_id}
    selected.update(d['artifact'] for key,d in latest.items() if key not in selected_keys)
    occupied = {}
    for stage in report['stages']:
        stage['folder'] = f'{stage["position"]+1:02d}-{_name(stage["id"])}'
    for a in report['artifacts']:
        stage = next((s for s in report['stages'] if any(i['artifact']==a['id'] for i in s['sources'])), None)
        if stage is None:
            stage = next((s for s in report['stages'] if a['run'] in s['runs']+s['plans'] or a['run'] and a['run']==s['target']), None)
        base = stage['folder'] if stage else 'inputs'
        a['stage'] = stage['id'] if stage else None
        a['selected'] = a['id'] in selected
        task = _name(a['task'] or 'inputs')
        # Persist human version numbers so newly discovered artifacts cannot rename old files.
        version_key = json.dumps([base, task, a['run'], a['attempt']])
        if version_key not in versions:
            prefix = [base, task]
            versions[version_key] = 1 + max((v for k,v in versions.items() if json.loads(k)[:2]==prefix), default=0)
        version = f'version-{versions[version_key]:02d}'
        if a['selected']:
            directory = base+'/selected'
        elif a['task'] and a['path'].startswith('delivery/'):
            directory = base+'/drafts/'+task+'/'+version
        elif a['task']:
            directory = base+'/reviews/'+task+'/'+version
        else:
            directory = base+'/support/'+task+'/'+version
        name = _name(Path(a['path'] or 'artifact').name)
        candidate = directory+'/'+name
        # Exact basename collisions remain distinct and retain their own identities.
        n = 2
        while candidate in occupied:
            candidate = directory+'/'+Path(name).stem+f'-{n}'+Path(name).suffix
            n += 1
        occupied[candidate] = a['id']
        a['copy_path'] = candidate
    return versions


def _relocate(root, relative, destination, digest):
    """Move an unchanged published file, never a registered blob or a user edit."""
    if not relative or relative == destination:
        return
    source = _inside(root, relative)
    target = _inside(root, destination)
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
        return
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.link(source, target)
    except FileExistsError:
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            return
    source.unlink()


def _owned(root, relative, data, hashes):
    """Refresh a generated index only while it still matches our last write."""
    path = _inside(root, relative)
    if path.exists() and (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=hashes.get(relative)):
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _replace(path, data)
    hashes[relative] = hashlib.sha256(data).hexdigest()


def sync(state, pid):
    # Serialize filesystem publication separately from database transactions.
    from .host import HOST
    from .production_folders import checked_directory
    report = _snapshot(state, pid)
    parent = checked_directory(folder_path(state,pid).parent)
    parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with _safe(parent/('.'+pid+'.lock')).open('a') as stream:
        HOST.lock(stream)
        return _sync(state,pid,report)


def _sync(state, pid, report):
    from .production_folders import checked_directory
    from . import production_control as pc
    from orchestrator.runtime import safe_file
    root = checked_directory(folder_path(state,pid))
    marker = _safe(root/'.relay-workflow.json')
    if root.exists():
        if not marker.is_file() or json.loads(marker.read_text()).get('workflow') != pid:
            raise ValueError('Workflow folder already exists without its ownership marker; files preserved.')
    else:
        root.mkdir(parents=True,mode=0o700)
        _put(marker,encoded({'workflow':pid}))
    old = json.loads(marker.read_text())
    state_signature = hashlib.sha256(encoded(report)).hexdigest()
    versions = _layout(report, old)
    def stamp(a):
        path=_inside(root,old.get('paths',{}).get(a['id'],a['copy_path']))
        if not path.is_file():return None
        st=path.stat()
        return [st.st_size,st.st_mtime_ns,st.st_ctime_ns]
    if (old.get('format_version')==2 and old.get('state_signature') == state_signature and not old.get('errors')
            and all(stamp(a)==old.get('file_stats',{}).get(a['id']) and stamp(a) is not None for a in report['artifacts'])):
        return root
    previous = dict(old.get('paths', {}))
    if old.get('format_version')!=2 and old.get('snapshot'):
        legacy = _inside(root,'snapshots/'+old['snapshot']+'/manifest.json')
        if legacy.is_file():
            previous.update({a['id']:a['copy_path'] for a in json.loads(legacy.read_text())['artifacts']})
    # Check every managed destination before starting migration.
    for a in report['artifacts']:
        _inside(root,a['copy_path'])
        if a['id'] in previous:_inside(root,previous[a['id']])
    errors = []
    # Vacate old selected paths before promoting their replacement. The staging path
    # also makes a process interruption recoverable without changing source artifacts.
    for a in report['artifacts']:
        prior = previous.get(a['id'])
        if prior and prior != a['copy_path']:
            _relocate(root,prior,'.relay/moving/'+a['id'],a['sha256'])
    for a in report['artifacts']:
        try:
            _relocate(root,'.relay/moving/'+a['id'],a['copy_path'],a['sha256'])
            from . import gemini
            source_root = gemini.GENERATED.resolve() if a['id'].startswith('media-') else pc.root(state)
            path = safe_file(source_root,str(Path(a['blob']).relative_to(source_root)))
            raw = path.read_bytes()
            if len(raw)!=a['bytes'] or hashlib.sha256(raw).hexdigest()!=a['sha256']:
                raise ValueError('Registered artifact hash mismatch.')
            a['copy_status'] = _put(_inside(root,a['copy_path']),raw)
            if a['copy_status']=='user_modified':
                # Keep the user's version and expose the exact registered one alongside it.
                name=Path(a['copy_path'])
                exact=name.with_name(name.stem+'-registered'+name.suffix)
                n=2
                while (_inside(root,str(exact)).exists() and
                       (not (root/exact).is_file() or hashlib.sha256((root/exact).read_bytes()).hexdigest()!=a['sha256'])):
                    exact=name.with_name(name.stem+f'-registered-{n}'+name.suffix);n+=1
                a['user_edit_path']=a['copy_path']
                a['copy_path']=str(exact)
                a['copy_status']=_put(_inside(root,a['copy_path']),raw)
        except (ValueError,OSError) as exc:
            a['copy_status'] = 'unavailable';errors.append({'artifact':a['id'],'error':str(exc)})
    report['copy_errors'] = errors
    for a in report['artifacts']:a.pop('blob')
    signature = hashlib.sha256(encoded(report)).hexdigest()
    report['snapshot'] = signature
    archive = '.relay/snapshots/'+signature
    _put(root/'request.txt',preamble_request(report))
    hashes = dict(old.get('managed_hashes', {}))
    if old.get('readme_sha256'):hashes.setdefault('README.md',old['readme_sha256'])
    lines=['# '+report['title'], '', 'Status: '+report['status'], '',
           'Open the numbered stage folders to inspect the workflow. Native model files retain their original formats.', '',
           '- `selected/`: recorded selections, including selected preparation inputs.',
           '- `drafts/`: outputs without a current recorded selection, grouped by producer and version.',
           '- `reviews/` and `support/`: review evidence, scripts, contracts and inputs.',
           '- `.relay/`: workflow history and execution receipts.', '',
           'Editing these files does not change registered inputs or recorded decisions.', '', '## Stages', '']
    for stage in report['stages']:
        prefix = stage['folder']
        _put(root/archive/'stages'/prefix/'stage.json',encoded(stage))
        if stage['result']:
            result=stage['result'].encode()
            _put(root/archive/'stages'/prefix/'result.md',result)
            _owned(root,prefix+'/result.md',result,hashes)
        stage_lines=['# '+stage['id'], '', 'Status: '+stage['status'], '']
        if stage['result']:stage_lines+=['[Stage result](result.md)', '']
        for a in report['artifacts']:
            if a['stage']!=stage['id']:continue
            rel=os.path.relpath(a['copy_path'],prefix)
            status='Recorded selection' if a['selected'] else 'Not selected'
            stage_lines.append(f'- [{Path(rel).name}]({rel}) — {status}; {a["copy_status"]}. {a["purpose"]}')
        _owned(root,prefix+'/README.md',('\n'.join(stage_lines)+'\n').encode(),hashes)
        lines.append(f'- [{prefix}]({prefix}/README.md) — {stage["status"]}')
        for a in report['artifacts']:
            if a['stage']==stage['id'] and a['selected']:
                lines.append(f'  - [{Path(a["copy_path"]).name}]({a["copy_path"]})')
    for run in report['productions']:
        from orchestrator.contracts import label
        _put(root/archive/'records'/(label(run['run'])+'.json'),encoded(run))
    _put(root/archive/'manifest.json',encoded(report))
    _owned(root,'manifest.json',encoded(report),hashes)
    if errors or report['missing_artifacts']:lines+=['','Some recorded files are unavailable; see manifest.json.']
    lines+=['', '[Full file manifest](manifest.json)', '']
    _owned(root,'README.md','\n'.join(lines).encode(),hashes)
    # Retain old indexes, receipts and any user edits without cluttering the results.
    if old.get('format_version')!=2:
        for name in ('files','stages','records','snapshots'):
            source=_inside(root,name)
            if source.exists():
                destination=_inside(root,'.relay/legacy-layout/'+name)
                if destination.exists():
                    raise ValueError('Legacy archive destination already exists; files preserved.')
                destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                source.rename(destination)
    old.update(format_version=2, snapshot=signature, state_signature=state_signature,
               errors=bool(errors or report['missing_artifacts']), versions=versions,
               paths={a['id']:a['copy_path'] for a in report['artifacts']}, managed_hashes=hashes)
    old['file_stats']={a['id']:stamp(a) for a in report['artifacts']}
    _replace(marker,encoded(old))
    return root


def preamble_request(report):
    return report['request'].encode()


def sync_recent(state):
    if state.db.in_transaction:
        return
    from .relay_channels import ScopedState
    for row in state.db.execute('SELECT id,channel FROM relay_pipelines ORDER BY created DESC LIMIT 20').fetchall():
        try:
            sync(ScopedState(state,row['channel']),row['id'])
        except (ValueError,OSError) as exc:
            logging.getLogger(__name__).warning('Workflow folder export failed for %s: %s',row['id'],exc)
