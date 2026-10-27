"""Save authored node documents, without creating plans, runs or execution authority."""
import hashlib
import json
import re
import uuid

from orchestrator import node_spec
from .app_updates import read, write
from .host import HOST
from .relay_paths import PATHS


def dispatch(action, value):
    root = PATHS.data / 'node-drafts'
    if not isinstance(value, dict):
        raise ValueError('Expected draft settings')
    if action == 'node-drafts':
        if set(value)-{'include_archived'} or type(value.get('include_archived',False)) is not bool: raise ValueError('Choose whether to include deleted drafts')
        archived=set()
        state=PATHS.data/'state.sqlite'
        if state.exists():
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(state.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_job_archives'").fetchone():
                    archived={r[0] for r in db.execute("SELECT id FROM desktop_job_archives WHERE kind='draft'")}
        items = []
        for path in sorted(root.glob('*.json')):
            record = read(path)
            if path.stem in archived and not value.get('include_archived'):continue
            items.append(dict(id=path.stem, title=record['title'], kind='draft', status='draft', channel='desktop',archived=path.stem in archived,stamp=path.stat().st_mtime))
        return dict(items=items, execution_authorized=False)
    allowed = {'id'} if action == 'node-draft' else {'id', 'revision', 'title', 'workflow'}
    if set(value) != allowed:
        raise ValueError('Supply exactly the documented draft fields')
    ident = value['id']
    if ident is not None and (not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident)):
        raise ValueError('Invalid draft identity')
    if action == 'node-draft':
        if ident is None: raise ValueError('Choose a saved draft')
        result = read(root / (ident + '.json'))
        if result is None: raise ValueError('Draft not found')
        if result.get('origin',{}).get('mode')=='input':
            from .desktop_node_runs import project_result_sources
            return project_result_sources(dict(id=ident,**result,execution_authorized=False))
        return dict(id=ident, **result, execution_authorized=False)
    if action != 'node-draft-save': raise ValueError('Unknown draft action')
    title = value['title']
    if not isinstance(title, str) or not title.strip() or len(title) > 180:
        raise ValueError('Choose a title of 1–180 characters')
    # The same document validator used by node_run owns ports, types and cycles.
    from .desktop_node_files import lookup
    checked = node_spec.resolve_workflow(value['workflow'],artifact=lookup)
    document = checked['document']
    if len(json.dumps(document).encode()) > 500_000: raise ValueError('Draft is too large')
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.lock').open('a') as lock:
        HOST.lock(lock)
        ident = ident or uuid.uuid4().hex
        path = root / (ident + '.json')
        old = read(path)
        if value['id'] is not None and old is None:raise ValueError('This draft no longer exists. Start a new job instead.')
        if value['revision'] != (old['revision'] if old else None):
            raise ValueError('This draft changed elsewhere. Reopen it before saving.')
        revision = hashlib.sha256(json.dumps(dict(title=title, workflow=document), sort_keys=True).encode()).hexdigest()
        record = dict(title=title, workflow=document, revision=revision)
        if old and old.get('origin'):record['origin']=old['origin']
        if record.get('origin',{}).get('mode')=='input':
            from .desktop_node_runs import project_result_sources
            projected=project_result_sources(record)
        else:projected=record
        write(path, record)
    return dict(id=ident, **projected, missing_inputs=checked['missing_inputs'], execution_authorized=False)
