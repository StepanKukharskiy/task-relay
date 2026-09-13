"""General browser receipts in the shared database. No implicit action replay."""
import json
import sqlite3
import time
from orchestrator.contracts import encoded, label
from orchestrator.storage import transaction


class UncertainAction(ValueError):pass


class Journal:
    def __init__(self,db):
        self.db=db;db.row_factory=sqlite3.Row
        with transaction(db):
            db.execute('''CREATE TABLE IF NOT EXISTS general_browser_actions(
                job TEXT NOT NULL, id TEXT NOT NULL, profile TEXT NOT NULL, request TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT, created REAL NOT NULL, PRIMARY KEY(job,id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS general_browser_tabs(
                profile TEXT NOT NULL,id TEXT NOT NULL,url TEXT NOT NULL,status TEXT NOT NULL,
                updated REAL NOT NULL,PRIMARY KEY(profile,id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS general_browser_events(
                id INTEGER PRIMARY KEY,profile TEXT NOT NULL,job TEXT,action TEXT,
                kind TEXT NOT NULL,data TEXT NOT NULL,created REAL NOT NULL)''')

    def event(self,profile,job,action,kind,data):
        self.db.execute('INSERT INTO general_browser_events(profile,job,action,kind,data,created) VALUES (?,?,?,?,?,?)',
                        (profile,job,action,kind,encoded(data),time.time()))

    def pending(self,profile):
        return [dict(r) for r in self.db.execute("SELECT job,id,status FROM general_browser_actions WHERE profile=? AND status IN ('intent','uncertain')",(profile,))]

    def lookup(self,profile,job,ident,name,args):
        old=self.db.execute('SELECT * FROM general_browser_actions WHERE job=? AND id=?',(job,ident)).fetchone()
        if not old:return None
        if old['profile']!=profile or old['request']!=encoded({'name':name,'arguments':args}):
            raise ValueError('Action receipt identity changed')
        if old['status']=='observed':return json.loads(old['result'])
        raise UncertainAction('This action already has a receipt; inspect it without replay')

    def claim(self,profile,job,ident,name,args,max_actions,interactive):
        label(profile);label(job);label(ident)
        if self.db.in_transaction:raise ValueError('Browser dispatch must follow the caller transaction commit')
        request=encoded({'name':name,'arguments':args})
        with transaction(self.db):
            old=self.db.execute('SELECT * FROM general_browser_actions WHERE job=? AND id=?',(job,ident)).fetchone()
            if old:
                if old['profile']!=profile or old['request']!=request:raise ValueError('Action receipt identity changed')
                if old['status']=='observed':return json.loads(old['result'])
                raise UncertainAction('This action already has a receipt; inspect it without replay')
            if interactive and self.pending(profile):raise UncertainAction('Profile has unresolved browser work; no further interaction')
            if self.db.execute('SELECT count(*) FROM general_browser_actions WHERE job=?',(job,)).fetchone()[0]>=max_actions:
                raise ValueError('Browser action limit reached')
            self.db.execute('INSERT INTO general_browser_actions VALUES (?,?,?,?,?,?,?)',
                (job,ident,profile,request,'intent',None,time.time()))
            self.event(profile,job,ident,'intent',{'request':json.loads(request)})
        return None

    def finish(self,profile,job,ident,status,result):
        with transaction(self.db):
            count=self.db.execute("UPDATE general_browser_actions SET status=?,result=? WHERE profile=? AND job=? AND id=? AND status='intent'",
                            (status,encoded(result),profile,job,ident)).rowcount
            if count!=1:raise ValueError('Browser action was already finalized or changed')
            self.event(profile,job,ident,status,result)

    def tab(self,profile,ident,url,status='open'):
        with transaction(self.db):
            self.db.execute('INSERT INTO general_browser_tabs VALUES (?,?,?,?,?) ON CONFLICT(profile,id) DO UPDATE SET url=excluded.url,status=excluded.status,updated=excluded.updated',
                            (profile,ident,url,status,time.time()))

    def tabs(self,profile):
        return [dict(t) for t in self.db.execute('SELECT * FROM general_browser_tabs WHERE profile=? ORDER BY updated,id',(profile,))]

    def resolve(self,profile,job,ident,outcome,note):
        if outcome not in ('occurred','not_occurred') or not isinstance(note,str) or not note.strip():raise ValueError('Explicit inspected outcome and note required')
        with transaction(self.db):
            changed=self.db.execute("UPDATE general_browser_actions SET status=? WHERE profile=? AND job=? AND id=? AND status IN ('intent','uncertain')",
                ('resolved_'+outcome,profile,job,ident)).rowcount
            if changed!=1:raise ValueError('No matching unresolved action')
            self.event(profile,job,ident,'operator_resolution',{'outcome':outcome,'note':note})
