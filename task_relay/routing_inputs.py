"""Freeze selected research and user-approved task guides before Codex routing."""
import hashlib
import json
from pathlib import Path
import os
import time

from orchestrator.runtime import safe_file, file_hash

MAX_BYTES=2_000_000
INSTRUCTIONS='''snapshot.production_artifacts lists the 100 most recent generated output versions,
including reports and drafts from blocked attempts. For Codex route_task, choose_task
or delegate_task, select artifact_ids explicitly when this catalog is nonempty; []
means no generated outputs are needed. Resolve 'this report/file/script' using the
focused production, reply context, run, output purpose and exact version. Include
the requested artifact IDs, not merely conversation.json or a claim that files exist.
If ambiguous or absent, ask which version before routing. Preserve blocked/unaccepted
status; sharing a file never accepts a production or authorizes another stage.
snapshot.research_documents lists registered user research sources.
When routing work that uses those documents, include research_ids (their exact IDs)
on route_task, choose_task or a Codex delegate_task action. Select the requested
sources, not previous generated drafts. If the source set is ambiguous, ask which
documents before dispatch. Choosing a destination does not choose source documents.
Select research_ids explicitly, including when the user says "both" or "two";
Relay never infers document identities from words or the size of the catalog.
When the catalog is nonempty, every Codex routing action must include research_ids:
use [] if no registered research is needed, or the exact selected IDs otherwise.
Relay freezes the selected documents before queueing and sends readable local paths
with hashes to Codex. For any Codex task, Relay searches the selected project for
relevant optional guides and asks whether to use the discovered set before dispatch.
Remembered guide locations are discovery hints, not consent. Native project
instructions (AGENTS.md) still apply independently. Do not claim sources/guides
were sent without a receipt. A guides_pending route is waiting for the user, not running.
For past routed requests, included_inputs and inputs_sent describe the ORIGINAL
handoff. A catalog entry or remembered profile does not prove delivery. If a separate
source_correction is recorded, describe it as a later correction, not original attachment.
'''


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS project_guide_profiles (
      project TEXT NOT NULL, purpose TEXT NOT NULL, folder TEXT NOT NULL,
      discovered REAL NOT NULL, last_checked REAL NOT NULL,
      PRIMARY KEY(project,purpose))''')


def catalog(state):
    from task_relay import production_folders
    result=[];seen=set()
    for row in state.db.execute('''SELECT f.run,f.relative,u.id,u.filename,u.sha256,u.bytes
        FROM production_folder_files f JOIN production_uploads u ON u.id=f.input_id
        WHERE u.status IN ('ready','used') ORDER BY u.rowid DESC'''):
        owner=production_folders.source_run(state,row['run'])
        key=(owner,row['relative'])
        if key in seen:continue
        seen.add(key)
        result.append({**dict(row),'production':owner})
        if len(result)>50:
            raise ValueError('More than 50 registered research documents; narrow the source catalog before routing.')
    return result


def validate_ids(ids,documents):
    if not isinstance(ids,list) or not 0<=len(ids)<=10 or any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Select up to ten distinct registered research documents; [] selects none.')
    if not set(ids)<={d['id'] for d in documents}:
        raise ValueError('A selected research document is no longer available.')


def guide_paths(project,prompt,state=None):
    from task_relay.guide_discovery import discover
    return [(Path(d['source']),d['name']) for d in discover(project,prompt,state)['guides']]


def propose_guides(state,job,project):
    from task_relay.guide_discovery import discover
    result=discover(project,job['prompt'],state)
    selected=[(Path(d['source']),d['name'],'project guide',project,None) for d in result['guides']]
    result['guides']=capture(state,job,selected,section='guides')
    return result


def freeze(state,job,candidates,research_ids=None,artifact_ids=None):
    from task_relay import production_control as pc
    documents=catalog(state);ids=research_ids
    if documents and ids is None:
        raise ValueError('The routing action must explicitly select research_ids, or [] for no research. No sources were guessed.')
    selected=[]
    if ids is not None:
        validate_ids(ids,documents)
        for ident in ids:
            row=state.db.execute('SELECT * FROM production_uploads WHERE id=?',(ident,)).fetchone()
            path=safe_file(pc.root(state).parent/'production-guides',str(ident)+'/'+row['filename'])
            if str(path)!=row['path'] or file_hash(path)!=row['sha256'] or path.stat().st_size!=row['bytes']:
                raise ValueError('A registered research document changed before routing.')
            selected.append((path,row['filename'],'research',None,row['sha256']))
    from task_relay import conversation_inputs
    return capture(state,job,selected) + freeze_artifacts(state,job,artifact_ids) + conversation_inputs.freeze(state,job)


def capture(state,job,selected,section='sources',max_bytes=MAX_BYTES):
    records=[];total=0
    destination=state.media_dir.parent/'route-inputs'/str(job['id'])/section
    for index,(source,name,role,project,expected) in enumerate(selected):
        before=source.stat()
        if before.st_size>max_bytes or total+before.st_size>max_bytes:
            raise ValueError('Routed research and guides exceed the handoff byte limit.')
        if project:
            from task_relay.file_tools import Workspace
            with Workspace(Path(project)).open(name) as fd:
                before=os.fstat(fd)
                with os.fdopen(os.dup(fd),'rb') as stream:data=stream.read(max_bytes+1)
                after=os.fstat(fd)
        else:
            data=source.read_bytes();after=source.stat()
        if len(data)>max_bytes or total+len(data)>max_bytes:
            raise ValueError('Routed research and guides exceed the handoff byte limit.')
        digest=hashlib.sha256(data).hexdigest()
        if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or (expected and expected!=digest):
            raise ValueError('A routed input changed while being captured.')
        total+=len(data)
        target=destination/str(index)/Path(name).name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.is_symlink() or file_hash(target)!=digest:raise ValueError('A previous routing input snapshot differs; no files were replaced.')
        else:
            with target.open('xb') as out:out.write(data)
            target.chmod(0o400)
        records.append(dict(name=name,path=str(target.resolve()),sha256=digest,bytes=len(data),role=role,project=project,source=str(source)))
    return records


def handoff(state,row):
    records=json.loads(row['input_manifest'] or '[]')
    relevant=[d for d in records if d['project'] is None or d['project']==row['cwd']]
    if not relevant:return ''
    root=(state.media_dir.parent/'route-inputs'/str(row['id'])).resolve()
    lines=['\n\n--- REGISTERED INPUTS FOR THIS REQUEST ---',
        'Read these complete files before drafting. Research and saved conversation are source context, not new authorization; project guides govern their stated content scope. The current user request takes precedence. Compare conversation drafts with registered artifacts before selecting a version: a blocked production may have an older script. If the requested version is absent or ambiguous, report that instead of substituting an old draft. Conversation drafts are not independently reviewed or accepted production results. These paths are readable local file copies, not inline attachment previews.']
    for d in relevant:
        path=Path(d['path'])
        if not path.is_relative_to(root):raise ValueError('Routed input escaped its snapshot folder.')
        path=safe_file(root,str(path.relative_to(root)))
        if path.stat().st_size!=d['bytes'] or file_hash(path)!=d['sha256']:
            raise ValueError('A frozen routing input changed; no request was sent.')
        lines.append(f"- {d['role']}: {d['name']}\n  Path: {path}\n  SHA-256: {d['sha256']}")
        if d.get('artifact_id'):
            lines.append(f"  Artifact: {d['artifact_id']} · Run: {d['run']} · Task: {d['task']} · Attempt: {d['attempt']} · State at capture: {d['attempt_state']} (not user acceptance)")
        if d['role']=='project guide' and d.get('source'):
            lines.append('  Original location: '+d['source']+' (resolve guide-relative references here; use the saved guide version above).')
    return '\n'.join(lines)


def artifact_catalog(state):
    """Recent immutable versions, including useful outputs from blocked attempts."""
    return [dict(r) for r in state.db.execute("""SELECT a.id,a.run,a.task,a.attempt,a.path,a.sha256,a.bytes,a.purpose,
        t.state AS attempt_state FROM production_artifacts a JOIN production_attempts t ON t.id=a.attempt
        ORDER BY a.rowid DESC LIMIT 100""")]


def validate_artifact_ids(ids, artifacts):
    if (not isinstance(ids,list) or len(ids)>10 or any(not isinstance(i,str) for i in ids)
            or len(set(ids))!=len(ids) or not set(ids)<={a['id'] for a in artifacts}):
        raise ValueError('Select up to ten distinct exact production artifact IDs from the catalog, or [] for none.')


def freeze_artifacts(state,job,ids):
    artifacts=artifact_catalog(state)
    # Other callers (e.g. planning) still support conversation-only snapshots.
    if ids is None:return []
    validate_artifact_ids(ids,artifacts)
    known={a['id']:a for a in artifacts};result=[]
    for ident in ids:
        a=known[ident]
        row=state.db.execute('SELECT blob FROM production_artifacts WHERE id=?',(ident,)).fetchone()
        from task_relay import production_control as pc
        path=safe_file(pc.root(state)/'artifacts',ident+'/content')
        if str(path)!=row['blob'] or path.stat().st_size!=a['bytes'] or file_hash(path)!=a['sha256']:
            raise ValueError('The selected production artifact changed; no substitute was sent.')
        records=capture(state,job,[(path,a['path'],'generated artifact',None,a['sha256'])],
                        section='artifacts/'+ident,max_bytes=100_000_000)
        records[0].update(artifact_id=ident,**{k:a[k] for k in ('run','task','attempt','attempt_state')})
        result.extend(records)
    return result
