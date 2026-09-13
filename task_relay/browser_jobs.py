"""Durable, explicit browser submissions. A journal never resends an uncertain turn."""
import hashlib
import json
import re
import sqlite3
import time
from urllib.parse import urlsplit


def conversation_url(value):
    u=urlsplit(value)
    if (u.scheme!='https' or u.netloc!='www.perplexity.ai' or u.query or u.fragment
            or not re.fullmatch(r'/search/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',u.path)):
        raise ValueError('Use the exact saved https://www.perplexity.ai/search/… conversation URL')
    return value


def fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()


class Journal:
    def __init__(self,db):
        self.db=db
        db.row_factory=sqlite3.Row
        db.executescript('''CREATE TABLE IF NOT EXISTS browser_jobs(
            id TEXT PRIMARY KEY, prompt TEXT NOT NULL, target TEXT,
            status TEXT NOT NULL, baseline TEXT, url TEXT, result TEXT,
            error TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS browser_job_events(
            id INTEGER PRIMARY KEY, job TEXT NOT NULL, status TEXT NOT NULL,
            detail TEXT NOT NULL, created REAL NOT NULL);''')

    def get(self,receipt):
        row=self.db.execute('SELECT * FROM browser_jobs WHERE id=?',(receipt,)).fetchone()
        if not row:raise ValueError('Unknown browser receipt')
        return dict(row)

    def event(self,receipt,status,detail):
        self.db.execute('INSERT INTO browser_job_events(job,status,detail,created) VALUES (?,?,?,?)',
                        (receipt,status,detail,time.time()))

    def prepare(self,receipt,prompt,target=None):
        if not isinstance(receipt,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',receipt):
            raise ValueError('Receipt must be 1–100 letters, digits, underscores or hyphens')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>12000:
            raise ValueError('Provide 1–12000 characters of exact prompt text')
        if target:conversation_url(target)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT * FROM browser_jobs WHERE id=?',(receipt,)).fetchone()
            if old:
                if old['prompt']!=prompt or old['target']!=target:raise ValueError('Receipt belongs to a different exact request')
                return dict(old)
            if target and self.db.execute("SELECT 1 FROM browser_jobs WHERE (target=? OR url=?) AND status IN ('prepared','blocked','submitting','uncertain')",(target,target)).fetchone():
                raise ValueError('This conversation has unfinished or uncertain work; inspect its receipt first')
            now=time.time()
            self.db.execute('INSERT INTO browser_jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (receipt,prompt,target,'prepared',None,None,None,None,now,now))
            self.event(receipt,'prepared','Exact request retained; no browser submission')
        return self.get(receipt)

    def update(self,receipt,status,**values):
        if set(values)-{'baseline','url','result','error'}:raise ValueError('Unknown journal field')
        with self.db:
            self.db.execute('UPDATE browser_jobs SET status=?,updated=?'+''.join(','+k+'=?' for k in values)+' WHERE id=?',
                            (status,time.time(),*values.values(),receipt))
            self.event(receipt,status,values.get('error') or 'Browser observation recorded')

    def claim(self,receipt,baseline):
        with self.db:
            changed=self.db.execute("UPDATE browser_jobs SET status='submitting',baseline=?,error=NULL,updated=? WHERE id=? AND status IN ('prepared','blocked')",
                                    (json.dumps(baseline),time.time(),receipt)).rowcount
            if not changed:raise ValueError('Browser receipt already claimed; do not resend')
            self.event(receipt,'submitting','Submission intent committed before browser interaction')


def completed(baseline,now,prompt):
    # Multiple new turns or an unfamiliar UI are not enough evidence to claim this result.
    try:conversation_url(now['url'])
    except (ValueError,KeyError):return False
    return (now['ready'] and now['queries']==baseline['queries']+1
            and now['answers']==baseline['answers']+1
            and now['text'].count(prompt)==baseline['text'].count(prompt)+1)


def execute(journal,receipt,driver,*,reconcile=False,url=None,timeout=120):
    job=journal.get(receipt)
    if job['status']=='completed':return job
    if not 1<=timeout<=600:raise ValueError('Browser observation timeout must be 1–600 seconds')
    submitted=job['status'] in ('submitting','uncertain')
    if submitted and not reconcile:raise ValueError('Submission is uncertain; use reconcile to observe it without resending')
    if reconcile and not submitted:raise ValueError('Only an uncertain submission needs reconciliation')
    if url:conversation_url(url)
    target=job['url'] or job['target']
    if url and target and url!=target:raise ValueError('Reconciliation URL differs from the recorded conversation')
    if reconcile and not (target or url):raise ValueError('Supply the saved conversation URL to reconcile a new conversation')
    try:
        driver.open(target or url)
        if reconcile:
            baseline=json.loads(job['baseline'])
        else:
            baseline=driver.snapshot()
            driver.check_ready(baseline)
            journal.claim(receipt,baseline)
            submitted=True
            driver.submit(job['prompt'],baseline)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            now=driver.snapshot()
            try:canonical=conversation_url(now['url'])
            except ValueError:canonical=None
            if canonical:
                if target and canonical!=target:raise ValueError('Browser navigated to a different conversation')
                if not journal.get(receipt)['url']:
                    journal.update(receipt,'submitting',url=canonical)
            if completed(baseline,now,job['prompt']):
                journal.update(receipt,'completed',url=canonical,result=now['text'],error=None)
                return journal.get(receipt)
            driver.pause()
        raise ValueError('No complete matching turn was observed before the time limit')
    except Exception as exc:
        # The browser may have accepted Enter even when its driver reports a timeout.
        if not submitted and journal.get(receipt)['status'] not in ('prepared','blocked'):
            return journal.get(receipt)
        journal.update(receipt,'uncertain' if submitted else 'blocked',error=str(exc)[:1000])
        return journal.get(receipt)
