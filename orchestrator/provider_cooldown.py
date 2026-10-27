"""Durable provider/model cooldown, never task replay or additional capacity."""
import copy
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from . import contracts as c, executors
from .workers import atomic
from .runtime_outcomes import Hold

POLICY=dict(version=1,max_retries=2,delays=[30,90],max_wait_seconds=180)


def validate(policy):
    if policy!=POLICY or type(policy.get('version')) is not int or type(policy.get('max_retries')) is not int:raise ValueError('Unsupported provider cooldown policy')
    return policy


def freeze(rt,plan,frozen):
    frozen.pop('provider_cooldown',None)
    policy=plan.get('job_owner',{}).get('provider_cooldown')
    if policy:
        validate(policy)
        frozen['provider_cooldown']=dict(policy=copy.deepcopy(policy),database=str(rt.root/'provider-cooldowns.sqlite'))


def eligible(backend,request,outcome):
    """Only correlated rejection of function-only generation; no hosted effects."""
    if outcome.get('outcome')!='rejected':return False
    if backend.get('type') not in (*executors.FILE_TYPES,*executors.CODE_TYPES):return False
    provider=executors.provider_for(backend);payload=request.get('payload',{})
    if request.get('provider')!=provider or request.get('model')!=backend['model']:return False
    error=outcome.get('provider_error',{});status=outcome.get('http_status')
    if status not in (429,503) and not (provider=='codex' and error.get('failure_kind')=='service_unavailable'):return False
    detail=error.get('detail',error)
    if detail.get('code') in ('insufficient_quota','credit_balance_exhausted','organization_spend_limit_exceeded',
            'project_spend_limit_exceeded','organization_usage_limit_exceeded') or error.get('quota_exhausted'):return False
    if provider=='codex':
        return (error.get('terminal') is True and error.get('external_outcome')=='rejected'
            and error.get('model')==backend['model'] and bool(error.get('journals'))
            and error.get('scope') in ('before_tools','next_generation_only'))
    tools=payload.get('tools')
    if not isinstance(tools,list) or not tools:return False
    if provider=='gemini':return request.get('endpoint')=='models/'+backend['model']+':generateContent' and all(set(t)=={'functionDeclarations'} for t in tools)
    if any(t.get('type')!='function' for t in tools):return False
    if provider=='openai':return request.get('endpoint')=='responses' and payload.get('store') is False and not payload.get('background')
    return request.get('endpoint')=='chat/completions' and payload.get('stream') is False


class Cooldown:
    def __init__(self,frozen,control,*,clock=time.time,sleep=time.sleep):
        self.frozen=frozen;self.control=Path(control);self.clock=clock;self.sleep=sleep
        context=frozen['provider_cooldown'];self.policy=validate(context['policy'])
        self.database=Path(context['database'])
        if not self.database.is_absolute():raise ValueError('Cooldown store requires trusted absolute path')
        self.scope=c.digest([executors.provider_for(frozen['backend']),frozen['backend']['model']])
        self.assignment=frozen['assignment_id']
        self.database.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS gates(scope TEXT PRIMARY KEY,until REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS failures(id TEXT PRIMARY KEY,assignment TEXT NOT NULL,scope TEXT NOT NULL,receipt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS waits(id TEXT PRIMARY KEY,started REAL NOT NULL,spent REAL NOT NULL DEFAULT 0);''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def publish(self,stem,outcome,remaining_requests,remaining_seconds,*,can_retry=True):
        """Commit failure and shared cooldown before any subsequent dispatch."""
        request=self.control/(stem+'.request.json');failure=self.control/(stem+'.outcome.json')
        identity=c.digest([self.assignment,str(self.control),stem])
        hashes=dict(request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),outcome_sha256=hashlib.sha256(failure.read_bytes()).hexdigest())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT receipt FROM failures WHERE id=?',(identity,)).fetchone()
            if old:
                receipt=json.loads(old[0])
                if any(receipt[k]!=v for k,v in hashes.items()):raise ValueError('Cooldown failure evidence changed')
                for name,binding in receipt['journal_prefixes'].items():
                    raw=(self.control/name).read_bytes()[:binding['bytes']]
                    if hashlib.sha256(raw).hexdigest()!=binding['sha256']:raise ValueError('Cooldown original journal prefix changed')
            else:
                # Persistent transports append; bind the exact rejection prefix.
                evidence={}
                for name,sha in outcome.get('provider_error',{}).get('journals',{}).items():
                    if name not in ('codex-sent.jsonl','codex-events.jsonl'):raise ValueError('Unsupported cooldown evidence journal')
                    path=self.control/name
                    if not path.is_file():path=self.control/'codex'/name
                    raw=path.read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Cooldown rejection evidence changed before binding')
                    evidence[str(path.relative_to(self.control))]=dict(sha256=sha,bytes=len(raw))
                used=db.execute('SELECT count(*) FROM failures WHERE assignment=?',(self.assignment,)).fetchone()[0]
                ordinal=used+1;delay=self.policy['delays'][min(used,len(self.policy['delays'])-1)]
                retry_after=outcome.get('provider_error',{}).get('retry_after_seconds')
                if type(retry_after) in (int,float) and retry_after>=0:delay=max(delay,retry_after)
                allowed=(can_retry and ordinal<=self.policy['max_retries'] and remaining_requests>0
                         and delay+1<remaining_seconds and delay<=self.policy['max_wait_seconds'])
                until=self.clock()+delay
                receipt=dict(version=1,assignment=self.assignment,scope=self.scope,ordinal=ordinal,until=until,
                    continued=allowed,remaining_requests=remaining_requests,remaining_seconds=remaining_seconds,
                    acceptance=False,replayed_tools=False,usage=None,journal_prefixes=evidence,**hashes)
                db.execute('INSERT INTO failures VALUES (?,?,?,?)',(identity,self.assignment,self.scope,c.encoded(receipt)))
                db.execute('INSERT INTO gates VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET until=max(until,excluded.until)',(self.scope,until))
        atomic(self.control/(stem+'.cooldown.json'),receipt)
        return receipt['continued']

    def wait(self,stem,remaining_seconds):
        """One durable wait budget per assignment; no provider request is sent here."""
        end=self.clock()+remaining_seconds;wait_id=self.assignment
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO waits(id,started) VALUES (?,?)',(wait_id,self.clock()))
        while True:
            if (self.control/'cancel.json').exists():raise Hold('provider_cooldown_cancelled','Cancelled during provider cooldown',phase='produce')
            with self.connect() as db:
                row=db.execute('SELECT until FROM gates WHERE scope=?',(self.scope,)).fetchone()
                spent=db.execute('SELECT spent FROM waits WHERE id=?',(wait_id,)).fetchone()[0]
            delay=max(0,(row[0] if row else 0)-self.clock())
            if end-self.clock()<=1:raise Hold('provider_cooldown_exhausted','Original provider deadline exhausted',phase='produce')
            if delay<=0:
                # Stagger resumed calls sharing this provider/model. Commit the
                # next slot before dispatch; no lock is held across network I/O.
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    latest=db.execute('SELECT until FROM gates WHERE scope=?',(self.scope,)).fetchone()
                    if latest and latest[0]>self.clock():continue
                    if latest:db.execute('UPDATE gates SET until=? WHERE scope=?',(self.clock()+2,self.scope))
                return
            if delay+1>=end-self.clock() or spent+delay>self.policy['max_wait_seconds']:
                raise Hold('provider_cooldown_exhausted','Provider cooldown cannot fit the original time/wait allowance',phase='produce')
            atomic(self.control/(stem+'.cooldown-wait.json'),dict(scope=self.scope,until=row[0],spent=spent,dispatched=False))
            # Charge before waiting so process interruption never refunds allowance.
            interval=min(1,delay)
            with self.connect() as db:db.execute('UPDATE waits SET spent=spent+? WHERE id=?',(interval,wait_id))
            self.sleep(interval)


def search_gate(config,control,backend,seconds):
    context=config.get('provider_cooldown')
    if not context:return None
    gate=Cooldown(dict(provider_cooldown=context,backend=backend,assignment_id=config['cooldown_assignment']),control)
    gate.wait('provider-search',seconds)
    return gate


def search_failure(gate,query,error,seconds):
    """Search has a fixed operation allocation: cool peers, never add searches."""
    if gate is None or error.uncertain:return
    detail=error.detail
    if error.status not in (429,503,'serverOverloaded') or detail.get('quota_exhausted'):return
    nested=detail.get('detail',detail)
    if nested.get('code') in ('insufficient_quota','credit_balance_exhausted','organization_spend_limit_exceeded',
                             'project_spend_limit_exceeded','organization_usage_limit_exceeded'):return
    # Adapter certainty is required. A failed submitted search is never replayed.
    stem='provider-search'
    outcome=dict(outcome='rejected',http_status=error.status,provider_error=detail)
    atomic(gate.control/(stem+'.request.json'),dict(query=query,backend=gate.frozen['backend']))
    atomic(gate.control/(stem+'.outcome.json'),outcome)
    gate.publish(stem,outcome,0,seconds,can_retry=False)
