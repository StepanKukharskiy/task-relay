"""Attempt-bound typed checkpoints in the shared database; exports are projections."""
from contextlib import contextmanager
import json
import sqlite3

from . import operation_contracts as contracts
from .storage import transaction

SCHEMA='''
CREATE TABLE IF NOT EXISTS operation_record_sets (
 attempt TEXT PRIMARY KEY, binding TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS operation_records (
 attempt TEXT NOT NULL, key TEXT NOT NULL, ordinal INTEGER NOT NULL, value TEXT NOT NULL,
 PRIMARY KEY(attempt,key), UNIQUE(attempt,ordinal));
CREATE TABLE IF NOT EXISTS operation_submissions (
 attempt TEXT NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL, receipt TEXT NOT NULL,
 PRIMARY KEY(attempt,request_key));
'''


def initialize(db):
    for statement in SCHEMA.split(';'):
        if statement.strip():db.execute(statement)


def audit_context(frozen, read):
    from .research_quality import load_json
    import hashlib
    binding=frozen['computer_review'];research=binding['research']
    for item in frozen['inputs']:
        if hashlib.sha256(read(item['path'])).hexdigest()!=item['sha256']:
            raise ValueError('Frozen operation input changed')
    raw=read(binding['path'])
    if hashlib.sha256(raw).hexdigest()!=binding['sha256']:raise ValueError('Raw source binding changed')
    pack=load_json(raw)
    if pack['research']!=research:raise ValueError('Research units differ from the frozen binding')
    sources={o['observation']:o['text'] for o in pack['observations']}
    sources['coverage']=pack['coverage_note']
    return dict(sources=sources,units=research['units'])


class Store:
    def __init__(self,frozen,db=None):
        contracts.validate_assignment(frozen)
        self.frozen=frozen;self.contract=frozen['operation_contract'];self.db=db
        self.attempt=frozen['assignment_id'];self.binding=contracts.digest(frozen)
        self.family=contracts.identity({k:self.contract[k] for k in ('id','version')})

    @contextmanager
    def connection(self):
        db=self.db
        if db is None:
            # mode=rw prevents accidental creation of another authority.
            from pathlib import Path
            uri=Path(self.frozen['operation_store']).resolve().as_uri()+'?mode=rw'
            db=sqlite3.connect(uri,uri=True,timeout=30,isolation_level=None)
        try:
            with transaction(db):
                row=db.execute('SELECT frozen FROM production_attempts WHERE id=?',(self.attempt,)).fetchone()
                if not row or contracts.digest(json.loads(row[0]))!=self.binding:
                    raise ValueError('Operation attempt differs from its authoritative frozen assignment')
                yield db
        finally:
            if self.db is None:db.close()

    def _state(self,db):
        row=db.execute('SELECT binding,revision FROM operation_record_sets WHERE attempt=?',(self.attempt,)).fetchone()
        if row and row[0]!=self.binding:raise ValueError('Stale operation binding')
        records=[json.loads(r[0]) for r in db.execute('SELECT value FROM operation_records WHERE attempt=? ORDER BY ordinal',(self.attempt,))]
        return (row[1] if row else 0),records

    def progress(self):
        with self.connection() as db:
            revision,records=self._state(db)
        result=dict(revision=revision,committed=len(records),maximum=self.maximum())
        if self.contract['id']=='research.audit':
            done={r['claim'] for r in records}
            missing=[u for u in self.frozen['computer_review']['research']['units'] if u['claim'] not in done]
            result.update(remaining=len(missing),next_claims=missing[:self.family['batch']])
        return result

    def maximum(self):
        if self.contract['id']=='research.audit':return len(self.frozen['computer_review']['research']['units'])
        return self.contract['parameters']['max_records']

    def document(self,records):
        if self.contract['id']=='research.audit':
            binding=self.frozen['computer_review'];research=binding['research']
            return {**{k:research[k] for k in ('summary_sha256','evidence_sha256','post_count','max_posts')},
                    'raw_sha256':binding['sha256'],'claims':sorted(records,key=lambda r:r['claim'])}
        return {'contract':{k:self.contract[k] for k in ('id','version')},
                'parameters':self.contract['parameters'],'records':records}

    def submit(self,args,context):
        contracts.fields(args,('request_key','revision','records'));contracts.text(args['request_key'],120)
        if type(args['revision']) is not int or args['revision']<0:raise ValueError('Expected a current revision')
        values=args['records']
        if not isinstance(values,list) or not 1<=len(values)<=self.family['batch']:
            raise ValueError('Record batch exceeds contract limit')
        if len(contracts.encoded(args).encode())>16000:raise ValueError('Record batch byte bound exceeded')
        keys=[self.family['validate'](v,self.contract['parameters'],context) for v in values]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate record in submission')
        request_hash=contracts.digest(args)
        with self.connection() as db:
            prior=db.execute('SELECT request_hash,receipt FROM operation_submissions WHERE attempt=? AND request_key=?',
                (self.attempt,args['request_key'])).fetchone()
            if prior:
                if prior[0]!=request_hash:raise ValueError('Conflicting request key; committed data is unchanged')
                return json.loads(prior[1])
            revision,records=self._state(db)
            if revision!=args['revision']:raise ValueError('Stale record revision; no records committed')
            existing={self.family['validate'](v,self.contract['parameters']):v for v in records}
            if set(keys)&set(existing):raise ValueError('Record already committed; use its original request key for an identical retry')
            if len(records)+len(values)>self.maximum():raise ValueError('Frozen record ceiling exceeded')
            if self.contract['id']=='research.audit':
                pending=[str(u['claim']) for u in context['units'] if str(u['claim']) not in existing][:self.family['batch']]
                if keys!=pending[:len(keys)]:raise ValueError('Submit only the next frozen claim IDs in order')
            complete=records+values
            raw=contracts.encoded(self.document(complete)).encode()
            if len(raw)>self.frozen['limits']['output_bytes']:raise ValueError('Contract output byte ceiling exceeded')
            if not revision:db.execute('INSERT INTO operation_record_sets VALUES (?,?,0)',(self.attempt,self.binding))
            for offset,(key,value) in enumerate(zip(keys,values),len(records)):
                db.execute('INSERT INTO operation_records VALUES (?,?,?,?)',(self.attempt,key,offset,contracts.encoded(value)))
            revision+=1
            db.execute('UPDATE operation_record_sets SET revision=? WHERE attempt=?',(revision,self.attempt))
            receipt=dict(revision=revision,committed=len(complete),record_ids=[contracts.digest([self.attempt,k]) for k in keys],
                         projection_sha256=contracts.digest(self.document(complete)))
            db.execute('INSERT INTO operation_submissions VALUES (?,?,?,?)',(self.attempt,args['request_key'],request_hash,contracts.encoded(receipt)))
        return receipt

    def export(self,files,*,complete=False):
        # A failed file write cannot roll back accepted records; retry only this
        # projection, never a model request or native action.
        with self.connection() as db:_,records=self._state(db)
        if complete and ((not records and self.contract['id']!='research.batch') or (self.contract['id']=='research.audit' and len(records)!=self.maximum())):
            raise ValueError('Contract completion requires all frozen claims or a nonempty candidate ledger')
        if not records and self.contract['id']!='research.batch':return
        raw=(contracts.encoded(self.document(records))+'\n').encode();path=self.contract['output']
        if sum(n for p,n in files.written.items() if p!=path)+len(raw)>self.frozen['limits']['output_bytes']:
            raise ValueError('Output byte budget exceeded')
        from task_relay.filesystem import FILES
        FILES.write(files.grant(),path,raw);files.written[path]=len(raw)

    def verify_export(self,read):
        with self.connection() as db:_,records=self._state(db)
        if (not records and self.contract['id']!='research.batch') or (self.contract['id']=='research.audit' and len(records)!=self.maximum()):raise ValueError('Incomplete operation record set')
        if read(self.contract['output'])!=(contracts.encoded(self.document(records))+'\n').encode():
            raise ValueError('Contract output differs from committed records')


def freeze(frozen,db):
    if not frozen.get('operation_contract'):return
    contracts.validate_assignment(frozen)
    path=next((r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main'),None)
    if not path:raise ValueError('Durable operations need the shared on-disk database')
    frozen['operation_store']=path
    if frozen['operation_contract']['id']=='research.audit':
        from .executors import request_limit
        n=len(frozen['computer_review']['research']['units'])
        minimum=(n+2)//3+2  # one finish plus one bounded correction/inspection
        if request_limit(frozen)<minimum or frozen['limits']['tool_calls']<minimum:
            raise ValueError(f'Typed audit needs at least {minimum} frozen requests/tools for {n} claims; replan without resetting attempts')
