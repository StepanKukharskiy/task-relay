"""One SQLite store, explicit offline legacy import, and composable transactions."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

TABLES=('runs','assignments','tasks','attempts','artifacts','events','decisions')
MIGRATION='production-runtime-v1'
SCHEMA='''
        CREATE TABLE IF NOT EXISTS production_runs(id TEXT PRIMARY KEY, plan TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS production_assignments(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL,
            version INTEGER NOT NULL, spec TEXT NOT NULL, UNIQUE(run,task,version));
        CREATE TABLE IF NOT EXISTS production_tasks(run TEXT NOT NULL, id TEXT NOT NULL, assignment TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, latest TEXT, PRIMARY KEY(run,id));
        CREATE TABLE IF NOT EXISTS production_attempts(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL,
            assignment TEXT NOT NULL, state TEXT NOT NULL, resource TEXT, frozen TEXT NOT NULL,
            session TEXT NOT NULL, receipt TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS production_artifacts(id TEXT PRIMARY KEY, run TEXT, task TEXT, attempt TEXT,
            path TEXT NOT NULL, blob TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
            purpose TEXT NOT NULL, source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS production_events(id INTEGER PRIMARY KEY, created REAL NOT NULL, run TEXT,
            task TEXT, attempt TEXT, kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS production_decisions(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL,
            artifact TEXT NOT NULL, purpose TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS production_replacement_heads(id TEXT PRIMARY KEY, scope TEXT NOT NULL,
            purpose TEXT NOT NULL, current_decision TEXT NOT NULL, revision INTEGER NOT NULL, members TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS production_replacements(id TEXT PRIMARY KEY, head TEXT NOT NULL,
            revision INTEGER NOT NULL, old_decision TEXT NOT NULL, new_decision TEXT NOT NULL,
            note TEXT NOT NULL, created REAL NOT NULL, UNIQUE(head,revision));
        CREATE TABLE IF NOT EXISTS production_artifact_validity(artifact TEXT NOT NULL, head TEXT NOT NULL,
            replacement TEXT NOT NULL, outdated INTEGER NOT NULL, reason TEXT NOT NULL,
            PRIMARY KEY(artifact,head));
        '''


def database_path(root):
    root=Path(root).resolve()
    # The main relay and CLI share private/state.sqlite. Isolated runtimes keep
    # their own single state.sqlite under their explicitly selected root.
    from task_relay.relay_paths import PATHS
    if root==PATHS.runtime:return PATHS.state
    parent=root.parent/'state.sqlite'
    return parent if root.name=='orchestrator' and parent.exists() else root/'state.sqlite'


def initialize(db,legacy=None):
    if legacy and Path(legacy).exists():
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_migrations'").fetchone()
        if not exists or not db.execute('SELECT 1 FROM storage_migrations WHERE id=?',(MIGRATION,)).fetchone():
            raise RuntimeError('Legacy runtime database needs offline migration before use. Run python3 -m orchestrator.storage with both database paths after stopping the relay.')
    for statement in SCHEMA.split(';'):
        if statement.strip():db.execute(statement)
    db.execute('CREATE TABLE IF NOT EXISTS storage_migrations(id TEXT PRIMARY KEY, applied REAL NOT NULL, evidence TEXT NOT NULL)')


@contextmanager
def transaction(db,write=True):
    """Nested calls cannot commit their caller's request/assignment transaction."""
    nested=db.in_transaction;name='sp_'+uuid.uuid4().hex
    db.execute('SAVEPOINT '+name if nested else 'BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield
        db.execute('RELEASE '+name if nested else 'COMMIT')
    except BaseException:
        if nested:
            db.execute('ROLLBACK TO '+name);db.execute('RELEASE '+name)
        else:db.execute('ROLLBACK')
        raise


def fingerprint(db,table):
    digest=hashlib.sha256();count=0
    for row in db.execute('SELECT rowid,* FROM "'+table+'" ORDER BY rowid'):
        digest.update(json.dumps(tuple(row),ensure_ascii=True,separators=(',',':')).encode()+b'\n');count+=1
    return {'rows':count,'sha256':digest.hexdigest()}


def migrate(state_path,legacy_path,verify_files=True):
    """Caller stops writers first. Source stays unchanged; target commits once."""
    state_path=Path(state_path).resolve();legacy_path=Path(legacy_path).resolve()
    if state_path==legacy_path or not state_path.is_file() or not legacy_path.is_file():
        raise ValueError('Supply distinct existing state and legacy runtime databases.')
    target=sqlite3.connect(state_path,timeout=5,isolation_level=None)
    source=sqlite3.connect(legacy_path,timeout=5,isolation_level=None)
    try:
        exists=target.execute("SELECT 1 FROM sqlite_master WHERE name='storage_migrations'").fetchone()
        old=target.execute('SELECT evidence FROM storage_migrations WHERE id=?',(MIGRATION,)).fetchone() if exists else None
        if old:
            evidence=json.loads(old[0])
            if evidence['source']!=str(legacy_path):raise ValueError('A different legacy database was already imported.')
            return {'already_migrated':True,**evidence}
        # Also prevents an accidentally still-running old scheduler from writing
        # during import. The service must remain stopped until new code is started.
        source.execute('BEGIN IMMEDIATE')
        with transaction(target):
            exists=target.execute("SELECT 1 FROM sqlite_master WHERE name='storage_migrations'").fetchone()
            if exists:
                old=target.execute('SELECT evidence FROM storage_migrations WHERE id=?',(MIGRATION,)).fetchone()
                if old:
                    evidence=json.loads(old[0])
                    if evidence['source']!=str(legacy_path):raise ValueError('A different legacy database was already imported.')
                    return {'already_migrated':True,**evidence}
            for db in (source,target):
                if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Database integrity check failed.')
            actual={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if actual!=set(TABLES):raise ValueError('Unexpected legacy schema; no tables were imported.')
            if source.execute("SELECT 1 FROM sqlite_master WHERE type IN ('index','trigger','view') AND sql IS NOT NULL").fetchone():
                raise ValueError('Unexpected legacy indexes, triggers or views; inspect before migrating.')
            initialize(target)
            evidence={'source':str(legacy_path),'target':str(state_path),'tables':{},'files_checked':0}
            for name in TABLES:
                dest='production_'+name
                if target.execute('SELECT count(*) FROM '+dest).fetchone()[0]:raise ValueError('Production tables are already populated; refusing to merge histories.')
                columns=[r[1:] for r in source.execute('PRAGMA table_info('+name+')')]
                if columns!=[r[1:] for r in target.execute('PRAGMA table_info('+dest+')')]:raise ValueError('Schema mismatch: '+name)
                rows=source.execute('SELECT rowid,* FROM '+name)
                placeholders=','.join('?' for _ in range(len(columns)+1))
                names='rowid,'+','.join('"'+c[0]+'"' for c in columns)
                target.executemany('INSERT INTO '+dest+' ('+names+') VALUES ('+placeholders+')',rows)
                before=fingerprint(source,name);after=fingerprint(target,dest)
                if before!=after:raise ValueError('Migration verification failed: '+name)
                evidence['tables'][name]=before
            if verify_files:
                from .runtime import file_hash
                for blob,digest,size in target.execute('SELECT blob,sha256,bytes FROM production_artifacts'):
                    p=Path(blob)
                    if not p.is_file() or p.stat().st_size!=size or file_hash(p)!=digest:raise ValueError('Registered artifact missing or changed: '+blob)
                    evidence['files_checked']+=1
            if target.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Migrated database integrity check failed.')
            target.execute('INSERT INTO storage_migrations VALUES (?,?,?)',(MIGRATION,time.time(),json.dumps(evidence)))
        return evidence
    finally:
        source.rollback();source.close();target.close()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Offline production database consolidation; stop relay and runtime writers first.')
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--legacy',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(migrate(args.state,args.legacy),indent=2))
