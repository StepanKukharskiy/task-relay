"""CLI transport for the same bounded record tools used by declared-file workers.

No scheduler, provider calls, new authority or domain-specific document writer.
"""
import json
from pathlib import Path
import sys
import sqlite3


def call(frozen,action,args=None):
    from .record_lifecycle import verify_implementation
    from .operation_records import Store
    verify_implementation(frozen)
    from .operation_records import initialize
    from .operation_contracts import encoded
    root=Path(frozen['workspace'])/'.relay'
    if root.is_symlink() or (root/'record-transport.sqlite').is_symlink():raise ValueError('Linked record transport')
    db=sqlite3.connect(root/'record-transport.sqlite',isolation_level=None)
    db.execute('CREATE TABLE IF NOT EXISTS production_attempts (id TEXT PRIMARY KEY,frozen TEXT,state TEXT)')
    db.execute('INSERT OR IGNORE INTO production_attempts VALUES (?,?,?)',(frozen['assignment_id'],encoded(frozen),'running'))
    initialize(db)
    try:return local_call(frozen,action,args,Store(frozen,db),root)
    finally:db.close()


def local_call(frozen,action,args,store,root):
    from .operation_contracts import tool,digest
    from .gemini_worker import Files
    from .workers import atomic
    if not store.family.get('local_record_tool'):raise ValueError('This family has no registered CLI fragment transport')
    if action=='schema':return tool(frozen['operation_contract'])
    if action=='progress':return store.progress()
    if action=='submit':
        receipt=store.submit(args,{})
        store.export(Files(frozen))
        with store.connection(write=False) as db:_,records=store._state(db)
        atomic(root/'record-transport.json',dict(binding=digest(frozen),records=records))
        return {**receipt,'authority':'workspace_staged'}
    if action=='export':
        files=Files(frozen);store.export(files,complete=True);store.verify_export(files.read_bytes)
        return dict(complete=True,outputs=sorted(store.owned_outputs()),acceptance=False)
    raise ValueError('Use schema, progress, submit or export')


def reconcile(frozen,db):
    """Import untrusted workspace fragments through the authoritative Store.

    Called only during confirmed terminal collection. CLI commands never gain
    write access to the production database outside their workspace sandbox.
    """
    from .operation_contracts import identity,digest
    contract=frozen.get('operation_contract')
    if frozen['backend']['type']!='codex-cli' or not contract:return
    if not identity({k:contract[k] for k in ('id','version')}).get('local_record_tool'):return
    from .runtime import safe_file
    from .research_quality import load_json
    from .operation_records import Store
    from .record_lifecycle import verify_implementation
    verify_implementation(frozen)
    path=safe_file(Path(frozen['workspace'])/'.relay','record-transport.json')
    if path.stat().st_size>2000000:raise ValueError('CLI record transport exceeds its byte bound')
    value=load_json(path.read_bytes())
    if not isinstance(value,dict) or set(value)!={'binding','records'} or value['binding']!=digest(frozen):raise ValueError('CLI fragments differ from their exact assignment')
    Store(frozen,db).ingest_local(value['records'])


def main(workspace):
    frozen=json.loads((Path(workspace)/'.relay/ASSIGNMENT.json').read_text())
    action=sys.argv[1] if len(sys.argv)>1 else 'progress'
    from .research_quality import load_json
    args=load_json(sys.stdin.read()) if action=='submit' else None
    print(json.dumps(call(frozen,action,args),sort_keys=True))


def prepare(workspace,frozen):
    """Write the bound entry point only; never run a fragment/model at launch."""
    from .operation_contracts import identity,encoded,tool
    from .runtime import file_hash
    contract=frozen.get('operation_contract')
    if not contract or not identity({k:contract[k] for k in ('id','version')}).get('local_record_tool'):return ''
    if frozen.get('runtime_sources',{}).get('record_tool.py')!=file_hash(Path(__file__)):
        raise ValueError('CLI record transport differs from the frozen implementation')
    root=Path(workspace)/'.relay'
    entry=root/'record_tool.py'
    entry.write_text('import sys\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]))+')\n'
        'from orchestrator.record_tool import main\nmain('+repr(str(workspace))+')\n')
    (root/'record-schema.json').write_text(encoded(tool(contract)))
    import shlex
    command=shlex.quote(sys.executable)+' .relay/record_tool.py'
    return ('\nThis output is code owned. Do not write the declared JSON output or invent its envelope. '
        'Read .relay/record-schema.json. Submit bounded fragments using '+command+' submit < fragment-request.json; '
        'each request has request_key, current revision and records as declared in that schema. '
        'Use '+command+' progress to inspect committed state and '+command+' export after submitting the completion seal. '
        'The shared record engine validates and writes the actual output locally; the controller imports these exact fragments at confirmed completion. Then return the normal final report. '
        'A failed local call may be corrected within this assignment; identical request keys return the saved receipt.\n')
