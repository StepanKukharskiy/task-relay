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
CREATE TABLE IF NOT EXISTS operation_record_versions (
 attempt TEXT NOT NULL, key TEXT NOT NULL, revision INTEGER NOT NULL, value TEXT NOT NULL,
 PRIMARY KEY(attempt,key,revision));
'''


def initialize(db):
    for statement in SCHEMA.split(';'):
        if statement.strip():db.execute(statement)
    from .record_recovery import initialize as initialize_resume
    initialize_resume(db)


def audit_context(frozen, read):
    from .record_lifecycle import audit_context as context
    return context(frozen, read)



class Store:
    def __init__(self,frozen,db=None):
        contracts.validate_assignment(frozen)
        self.frozen=frozen;self.contract=frozen['operation_contract'];self.db=db
        self.attempt=frozen['assignment_id'];self.binding=contracts.digest(frozen)
        self.family=contracts.identity({k:self.contract[k] for k in ('id','version')})
        self.lifecycle=self.family['lifecycle']

    def context(self, fallback=None, read=None):
        if self.lifecycle.context is None:return fallback or {}
        if read is None:
            from .runtime import safe_file
            read=lambda p:safe_file(self.frozen['workspace'],p).read_bytes()
        return self.lifecycle.context(self.frozen,read)

    def sourcing_context(self):
        # Historical public helper; lifecycle dispatch is registry-owned.
        return self.context()


    def owned_outputs(self):
        return {self.contract['output']} | {self.contract['parameters'][k]
            for k in self.lifecycle.owned_parameters if self.contract['parameters'].get(k)}


    @contextmanager
    def connection(self, *, write=True):
        # Observation must not promote a live read snapshot to a writer.
        # SQLite waits for genuine write contention within the existing timeout;
        # never replay a transaction body or an external operation on lock errors.
        db=self.db
        if db is None:
            # mode=rw prevents accidental creation of another authority.
            from pathlib import Path
            uri=Path(self.frozen['operation_store']).resolve().as_uri()+('?mode=rw' if write else '?mode=ro')
            db=sqlite3.connect(uri,uri=True,timeout=30,isolation_level=None)
        try:
            with transaction(db,write=write):
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
        # Revision zero can be an exact immutable checkpoint, not an empty draft.
        # Materialize it atomically with the first change; observation never writes.
        if not row:records=self.lifecycle.initial_records(self)
        return (row[1] if row else 0),records

    def progress(self):
        with self.connection(write=False) as db:
            revision,records=self._state(db)
        return dict(revision=revision,committed=len(records),maximum=self.maximum(),
                    **self.lifecycle.progress(self,records))

    def _materialize(self,db,records):
        if db.execute('SELECT 1 FROM operation_record_sets WHERE attempt=?',(self.attempt,)).fetchone():return
        db.execute('INSERT INTO operation_record_sets VALUES (?,?,0)',(self.attempt,self.binding))
        for ordinal,record in enumerate(records):
            db.execute('INSERT INTO operation_records VALUES (?,?,?,?)',
                (self.attempt,self.family['validate'](record,self.contract['parameters']),ordinal,contracts.encoded(record)))


    def maximum(self):
        return self.lifecycle.maximum(self)


    def document(self,records):
        return self.lifecycle.document(self,records)

    def validate_fragment(self,value,path):
        # Validate the advertised wire shape before semantic hooks. Their compact
        # domain errors cannot identify a malformed nested field for correction.
        from .parameter_contracts import validate
        schema=self.family.get('schema_for',lambda p:self.family['schema'])(self.contract['parameters'])
        validate(value,schema,path)


    def submit(self,args,context):
        context=self.context(context)
        contracts.fields(args,('request_key','revision','records'));contracts.text(args['request_key'],120)
        if type(args['revision']) is not int or args['revision']<0:raise ValueError('Expected a current revision')
        values=args['records']
        if not isinstance(values,list) or not 1<=len(values)<=self.family['batch']:
            raise ValueError('Record batch exceeds contract limit')
        size=len(contracts.encoded(args).encode())
        if size>contracts.MAX_SUBMISSION_BYTES:raise ValueError(f'Record batch byte bound exceeded: {size} UTF-8 bytes; maximum {contracts.MAX_SUBMISSION_BYTES}')
        for index,value in enumerate(values):self.validate_fragment(value,f'records[{index}]')
        values=[self.lifecycle.normalize(v,context) for v in values]
        keys=[self.family['validate'](v,self.contract['parameters'],context) for v in values]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate record in submission')
        request_hash=contracts.digest(args)
        with self.connection() as db:
            prior=db.execute('SELECT request_hash,receipt FROM operation_submissions WHERE attempt=? AND request_key=?',
                (self.attempt,args['request_key'])).fetchone()
            if prior:
                if prior[0]!=request_hash:raise ValueError('Conflicting request key; committed data is unchanged')
                return json.loads(prior[1])
            if self.lifecycle.require_active:self.require_writable(db)
            revision,records=self._state(db)
            if revision!=args['revision']:raise ValueError('Stale record revision; no records committed')
            existing={self.family['validate'](v,self.contract['parameters']):v for v in records}
            if set(keys)&set(existing):raise ValueError('Record already committed; use its original request key for an identical retry')
            if len(records)+len(values)>self.maximum():raise ValueError('Frozen record ceiling exceeded')
            if self.lifecycle.order:self.lifecycle.order(self,keys,existing,context)
            complete=records+values
            raw=contracts.encoded(self.document(complete)).encode()
            if len(raw)>self.frozen['limits']['output_bytes']:raise ValueError('Contract output byte ceiling exceeded')
            self._materialize(db,records)
            for offset,(key,value) in enumerate(zip(keys,values),len(records)):
                db.execute('INSERT INTO operation_records VALUES (?,?,?,?)',(self.attempt,key,offset,contracts.encoded(value)))
            revision+=1
            db.execute('UPDATE operation_record_sets SET revision=? WHERE attempt=?',(revision,self.attempt))
            receipt=dict(revision=revision,committed=len(complete),record_ids=[contracts.digest([self.attempt,k]) for k in keys],
                         projection_sha256=contracts.digest(self.document(complete)))
            db.execute('INSERT INTO operation_submissions VALUES (?,?,?,?)',(self.attempt,args['request_key'],request_hash,contracts.encoded(receipt)))
        return receipt

    def require_writable(self,db):
        row=db.execute('SELECT state FROM production_attempts WHERE id=?',(self.attempt,)).fetchone()
        from pathlib import Path
        if not row or row[0] not in ('launching','running') or (Path(self.frozen['workspace'])/'.relay/result.json').exists() and not getattr(self,'_local_collection',False):
            raise ValueError('Finished or stopped sourcing attempts cannot be amended or submitted')

    def ingest_local(self,records):
        """Confirmed CLI transport, same validation/commit path as API fragments."""
        if (self.db is None or self.frozen['backend']['type']!='codex-cli' or not self.family.get('local_record_tool')
                or not isinstance(records,list) or not 1<=len(records)<=self.maximum()):
            raise ValueError('Invalid local fragment transport')
        with self.connection() as db:
            row=db.execute('SELECT state,receipt FROM production_attempts WHERE id=?',(self.attempt,)).fetchone()
            receipt=json.loads(row[1] or '{}')
            if (row[0] not in ('launching','running') or receipt.get('status')!='finished' or receipt.get('exit_code')!=0
                    or receipt.get('reason') or receipt.get('pending_requests') or receipt.get('external_outcome')=='unknown'):
                raise ValueError('CLI fragment import requires confirmed successful termination')
            self._local_collection=True
            try:
                for index,value in enumerate(records):
                    self.submit(dict(request_key='cli-'+str(index),revision=index,records=[value]),{})
                # Validate complete before committing any partial authoritative batch.
                if not self.lifecycle.complete(self,records):raise ValueError(self.lifecycle.completion_error)
            finally:self._local_collection=False

    def amend(self,args,context):
        if not self.lifecycle.amendable:raise ValueError('This record family does not allow amendments')
        context=self.context(context)
        contracts.fields(args,('request_key','revision','expected_record_sha256','record'))
        contracts.text(args['request_key'],120)
        if type(args['revision']) is not int or args['revision']<0:raise ValueError('Expected current revision')
        size=len(contracts.encoded(args).encode())
        if size>contracts.MAX_SUBMISSION_BYTES:raise ValueError(f'Record amendment byte bound exceeded: {size} UTF-8 bytes; maximum {contracts.MAX_SUBMISSION_BYTES}')
        self.validate_fragment(args['record'],'record')
        key=self.family['validate'](args['record'],self.contract['parameters'],context)
        request_hash=contracts.digest(['amend',args])
        if context.get('base_records') and not self.contract['parameters'].get('allow_baseline_amend'):
            args={**args,'record':self.lifecycle.normalize(args['record'],context)}
            self.family['validate'](args['record'],self.contract['parameters'],context)
        with self.connection() as db:
            prior=db.execute('SELECT request_hash,receipt FROM operation_submissions WHERE attempt=? AND request_key=?',(self.attempt,args['request_key'])).fetchone()
            if prior:
                if prior[0]!=request_hash:raise ValueError('Conflicting request key; committed data is unchanged')
                return json.loads(prior[1])
            self.require_writable(db)
            revision,records=self._state(db)
            old=next((r for r in records if self.family['validate'](r,self.contract['parameters'])==key),None)
            if revision!=args['revision'] or old is None or contracts.digest(old)!=args['expected_record_sha256']:
                raise ValueError('Stale sourcing amendment; no records committed')
            self._materialize(db,records)
            updated=[args['record'] if self.family['validate'](r,self.contract['parameters'])==key else r for r in records]
            raw=contracts.encoded(self.document(updated)).encode()
            if len(raw)>self.frozen['limits']['output_bytes']:raise ValueError('Contract output byte ceiling exceeded')
            db.execute('INSERT INTO operation_record_versions VALUES (?,?,?,?)',(self.attempt,key,revision,contracts.encoded(old)))
            db.execute('UPDATE operation_records SET value=? WHERE attempt=? AND key=?',(contracts.encoded(args['record']),self.attempt,key))
            db.execute('UPDATE operation_record_sets SET revision=? WHERE attempt=?',(revision+1,self.attempt))
            receipt=dict(revision=revision+1,committed=len(records),record_ids=[contracts.digest([self.attempt,key])],
                         previous_record_sha256=contracts.digest(old),record_sha256=contracts.digest(args['record']),
                         projection_sha256=contracts.digest(self.document(updated)))
            db.execute('INSERT INTO operation_submissions VALUES (?,?,?,?)',(self.attempt,args['request_key'],request_hash,contracts.encoded(receipt)))
        return receipt

    def projections(self,records):
        result={self.contract['output']:(contracts.encoded(self.document(records))+'\n').encode()}
        if self.lifecycle.projections:result.update(self.lifecycle.projections(self,records))
        return result


    def verify_result(self,result):
        if self.lifecycle.verify_result:
            with self.connection(write=False) as db:_,records=self._state(db)
            self.lifecycle.verify_result(self,records,result)


    def export(self,files,*,complete=False):
        # Projection recovery never replays a provider or a host operation.
        with self.connection(write=False) as db:_,records=self._state(db)
        if complete and not self.lifecycle.complete(self,records):raise ValueError(self.lifecycle.completion_error)
        if not records and not self.lifecycle.export_empty:return
        projections=self.projections(records)
        if sum(n for p,n in files.written.items() if p not in projections)+sum(map(len,projections.values()))>self.frozen['limits']['output_bytes']:
            raise ValueError('Output byte budget exceeded')
        from task_relay.filesystem import FILES
        for path,raw in projections.items():FILES.write(files.grant(),path,raw);files.written[path]=len(raw)


    def verify_export(self,read):
        with self.connection(write=False) as db:_,records=self._state(db)
        if not self.lifecycle.complete(self,records):raise ValueError('Incomplete operation record set')
        for path,raw in self.projections(records).items():
            if read(path)!=raw:raise ValueError('Contract output differs from committed records')



def freeze(frozen,db):
    if not frozen.get('operation_contract'):return
    contracts.validate_assignment(frozen)
    path=next((r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main'),None)
    if not path:raise ValueError('Durable operations need the shared on-disk database')
    frozen['operation_store']=path
    from .record_lifecycle import definition
    hooks=definition(frozen['operation_contract'])
    if hooks.freeze:hooks.freeze(frozen)
