"""Immutable evidence and append-only decisions in a separate pilot database."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'private/learning/state.sqlite'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identifier(prefix):
    return prefix + ':' + uuid.uuid4().hex


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT NOT NULL,
            kind TEXT NOT NULL, raw BLOB NOT NULL, details TEXT NOT NULL,
            imported_at REAL NOT NULL, UNIQUE(path,sha256,kind));
          CREATE TABLE IF NOT EXISTS dataset_sources (
            dataset TEXT NOT NULL, workflow TEXT NOT NULL,
            source_id TEXT NOT NULL REFERENCES sources(id),
            PRIMARY KEY(dataset,workflow,source_id));
          CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
            ordinal INTEGER NOT NULL, role TEXT NOT NULL, timestamp TEXT,
            line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
            text TEXT NOT NULL, details TEXT NOT NULL,
            UNIQUE(source_id,ordinal));
          CREATE TABLE IF NOT EXISTS analysis_runs (
            id TEXT PRIMARY KEY, dataset TEXT NOT NULL, status TEXT NOT NULL,
            created_at REAL NOT NULL, details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES analysis_runs(id),
            details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(id),
            status TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
            details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id),
            action TEXT NOT NULL, created_at REAL NOT NULL, details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id),
            created_at REAL NOT NULL, details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS evaluations (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id),
            application_id TEXT NOT NULL REFERENCES applications(id),
            run_id TEXT NOT NULL REFERENCES analysis_runs(id), details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS suggestion_links (
            run_id TEXT NOT NULL, proposal_id TEXT NOT NULL REFERENCES proposals(id),
            PRIMARY KEY(run_id,proposal_id));
          CREATE TABLE IF NOT EXISTS continuity_states (
            id TEXT PRIMARY KEY, project TEXT NOT NULL,
            previous_id TEXT REFERENCES continuity_states(id),
            run_id TEXT REFERENCES analysis_runs(id), created_at REAL NOT NULL,
            details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS continuity_reviews (
            id TEXT PRIMARY KEY, state_id TEXT NOT NULL REFERENCES continuity_states(id),
            created_at REAL NOT NULL, details TEXT NOT NULL);
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(dataset_sources)')}
        if 'selected_at' not in columns:
            self.db.execute('ALTER TABLE dataset_sources ADD COLUMN selected_at REAL NOT NULL DEFAULT 0')
        from internal_jobs import initialize
        initialize(self.db)
        self.db.commit()
        self.path.chmod(0o600)

    def get(self, table, key):
        if table not in {'sources', 'events', 'analysis_runs', 'findings', 'proposals',
                         'applications', 'evaluations', 'internal_jobs', 'continuity_states'}:
            raise ValueError('Unknown record type')
        row = self.db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown {table} record: {key}')
        result = dict(row)
        if 'details' in result:
            result['details'] = json.loads(result['details'])
        return result

    def sources(self, dataset, workflow=None):
        sql = ('SELECT s.*,d.workflow FROM sources s JOIN dataset_sources d ON s.id=d.source_id '
               'WHERE d.dataset=?')
        args = [dataset]
        if workflow is not None:
            sql += ' AND d.workflow=?'
            args.append(workflow)
        rows = self.db.execute(sql + ' ORDER BY d.selected_at,s.imported_at,s.id', args).fetchall()
        # Analyze only the newest imported revision per explicitly selected path/workflow.
        latest = {}
        for row in rows:
            latest[(row['path'], row['kind'], row['workflow'])] = dict(row)
        return list(latest.values())

    def evidence(self, dataset, workflow=None):
        result = []
        for source in self.sources(dataset, workflow):
            for row in self.db.execute('SELECT * FROM events WHERE source_id=? ORDER BY ordinal', (source['id'],)):
                item = dict(row)
                item['details'] = json.loads(item['details'])
                item.update(workflow=source['workflow'], kind=source['kind'], path=source['path'],
                            source_hash=source['sha256'])
                result.append(item)
        return result

    def citations(self, refs, allowed=None):
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) for r in refs):
            raise ValueError('Evidence must contain nonempty event IDs')
        for ref in refs:
            self.get('events', ref)
            if allowed is not None and ref not in allowed:
                raise ValueError(f'Citation outside supplied evidence: {ref}')

    def decision(self, proposal, action, details):
        self.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',
                        (identifier('decision'), proposal, action, time.time(), encoded(details)))

    def update_run(self, run, status, details):
        with self.db:
            self.db.execute('UPDATE analysis_runs SET status=?,details=? WHERE id=?',
                            (status, encoded(details), run))

    def close(self):
        self.db.close()
