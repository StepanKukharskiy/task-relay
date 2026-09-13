"""User-managed account sites and manual sign-in receipts; no stored credentials."""
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from orchestrator.browser_contract import origin
from orchestrator.storage import transaction

PROFILE = 'accounts'


def initialize(db):
    for sql in (
        'CREATE TABLE IF NOT EXISTS browser_account_source(id INTEGER PRIMARY KEY CHECK(id=1), endpoint TEXT, revision TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS browser_sites(origin TEXT PRIMARY KEY,status TEXT NOT NULL,revision TEXT NOT NULL,updated REAL NOT NULL)',
        'CREATE TABLE IF NOT EXISTS browser_site_requests(source TEXT PRIMARY KEY,request TEXT NOT NULL,channel TEXT NOT NULL,result TEXT NOT NULL,created REAL NOT NULL)',
        'CREATE TABLE IF NOT EXISTS browser_site_logins(job TEXT PRIMARY KEY,origin TEXT NOT NULL,revision TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0)',
    ): db.execute(sql)
    db.execute('INSERT OR IGNORE INTO browser_account_source VALUES(1,NULL,?)', (secrets.token_hex(16),))


def website(url):
    value=origin(url)
    if urlsplit(value).scheme!='https':raise ValueError('Account sites require an exact HTTPS origin.')
    if urlsplit(url).query or urlsplit(url).fragment:
        raise ValueError('Use the site address without query parameters or fragments.')
    return value


def catalog(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='browser_sites'").fetchone():return []
    return [dict(zip(('origin','status','updated'),r)) for r in db.execute('SELECT origin,status,updated FROM browser_sites ORDER BY origin')]


def describe(db):
    rows=catalog(db)
    lines=['Relay account sites (profile: accounts):']
    lines.extend(r['origin']+' — '+r['status'] for r in rows)
    if not rows:lines.append('No sites added yet.')
    lines.append('Use /browser sites add https://site.example, then /browser sites login https://site.example. New sites require manual sign-in confirmation. Saved access does not authorize every action on a site.')
    return '\n'.join(lines)


def command(state,arg,source,channel):
    from . import browser_setup
    parts=arg.split()
    op=parts[1].lower() if len(parts)>1 else 'list'
    if op not in ('list','add','login','done','remove') or len(parts)!=(1 if len(parts)==1 else 2 if op=='list' else 3):
        raise ValueError('Use /browser sites, or /browser sites add|login|done|remove https://site.example.')
    site=website(parts[2]) if op!='list' else None
    with transaction(state.db):
        old=state.db.execute('SELECT request,channel,result FROM browser_site_requests WHERE source=?',(source,)).fetchone()
        if old:
            if old[0]!=arg or old[1]!=channel:raise ValueError('Site request identity changed.')
            return old[2]
        revision=state.db.execute('SELECT revision FROM browser_account_source WHERE id=1').fetchone()[0]
        row=state.db.execute('SELECT status FROM browser_sites WHERE origin=?',(site,)).fetchone()
        if op=='list':result=describe(state.db)
        elif op=='add':
            if not row or row[0]=='removed':
                state.db.execute('INSERT INTO browser_sites VALUES(?,?,?,?) ON CONFLICT(origin) DO UPDATE SET status=excluded.status,revision=excluded.revision,updated=excluded.updated',
                                 (site,'needs_verification',revision,time.time()))
            result=site+' is on the site list. Use /browser sites login '+site+' to sign in manually.'
        elif op=='remove':
            state.db.execute("UPDATE browser_sites SET status='removed',updated=? WHERE origin=?",(time.time(),site))
            state.db.execute("UPDATE provider_jobs SET status='cancelled' WHERE id IN (SELECT job FROM browser_site_logins WHERE origin=?) AND status IN ('queued','running')",(site,))
            result=site+' removed from permitted account sites. Browser cookies are retained; removal stops Relay access, not the website session.'
        elif not row or row[0]=='removed':raise ValueError('Add this exact site first: /browser sites add '+site)
        elif op=='login':
            active=state.db.execute("SELECT j.id,l.origin FROM provider_jobs j JOIN browser_site_logins l ON l.job=j.id WHERE j.status IN ('queued','running')").fetchone()
            if active:
                if active[1]!=site:raise ValueError('Finish the current site sign-in or use /browser cancel first.')
                result='Manual sign-in is already queued or open for '+site+'.'
            else:
                job=secrets.token_hex(16)
                state.db.execute("UPDATE browser_sites SET status='needs_verification',revision=?,updated=? WHERE origin=?",(revision,time.time(),site))
                state.db.execute('INSERT INTO provider_jobs VALUES(?,?,?,?,?)',(job,'browser-sites','browser_site_login','queued',time.time()))
                state.db.execute('INSERT INTO browser_site_logins(job,origin,revision) VALUES(?,?,?)',(job,site,revision))
                state.db.execute('INSERT INTO browser_setup_requests VALUES(?,?,?,?,?)',(source,arg,job,channel,time.time()))
                browser_setup.notice(state,job,'queued','Manual sign-in queued for '+site+'. Complete sign-in in the Relay browser. Do not send credentials in chat. Wait for the browser-open notice before confirming.')
                result='Manual sign-in queued for '+site+'.'
        else:
            active=state.db.execute("SELECT l.job FROM browser_site_logins l JOIN provider_jobs j ON j.id=l.job JOIN browser_setup_progress p ON p.job=l.job WHERE l.origin=? AND l.revision=? AND j.status='running' AND p.phase='waiting_for_site_confirmation'",(site,revision)).fetchone()
            if not active:raise ValueError('No open sign-in awaiting confirmation for '+site+'. Use /browser sites login '+site)
            state.db.execute('UPDATE browser_site_logins SET confirmed=1 WHERE job=?',(active[0],))
            result='Your sign-in confirmation is recorded. Relay will check that the browser is back on '+site+'.'
        state.db.execute('INSERT INTO browser_site_requests VALUES(?,?,?,?,?)',(source,arg,channel,result,time.time()))
    return result


class VerificationRequired(ValueError):pass


class Access:
    def __init__(self,data):
        self.path=Path(data)/'state.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            with transaction(db):initialize(db)
            self.endpoint,self.revision=db.execute('SELECT endpoint,revision FROM browser_account_source WHERE id=1').fetchone()

    def check(self,url):
        site=origin(url)
        with closing(sqlite3.connect(self.path)) as db:
            current=db.execute('SELECT revision FROM browser_account_source WHERE id=1').fetchone()[0]
            row=db.execute('SELECT status,revision FROM browser_sites WHERE origin=?',(site,)).fetchone()
        if current!=self.revision or not row or row!=('confirmed_by_user',self.revision):
            raise VerificationRequired('Manual verification required for '+site+'. Use /browser sites add '+site+' and /browser sites login '+site+'. The current task has not gained access to this site.')

    def require_manual(self,url):
        site=origin(url)
        with closing(sqlite3.connect(self.path)) as db,transaction(db):
            db.execute("UPDATE browser_sites SET status='needs_verification',updated=? WHERE origin=? AND revision=? AND status='confirmed_by_user'",(time.time(),site,self.revision))
        raise VerificationRequired('Sign-in or verification is required again for '+site+'. Use /browser sites login '+site+'.')


def set_source(db,endpoint):
    """Caller validates an explicitly selected local browser before saving it."""
    with transaction(db):
        initialize(db)
        db.execute('UPDATE browser_account_source SET endpoint=?,revision=? WHERE id=1',(endpoint,secrets.token_hex(16)))
        db.execute("UPDATE browser_sites SET status='needs_verification',updated=? WHERE status!='removed'",(time.time(),))


def run_login(state,job,driver_factory=None,timeout=600):
    from . import browser_setup,host_browser_accounts
    if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND status='running'",(job,)).fetchone():return
    row=state.db.execute('SELECT origin,revision FROM browser_site_logins WHERE job=?',(job,)).fetchone()
    if not row:return
    site,revision=row
    data=Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent
    try:
        access=Access(data)
        if access.revision!=revision:raise ValueError('Browser connection changed.')
        with (driver_factory or host_browser_accounts.manual)(data,access) as page:
            page.goto(site,wait_until='domcontentloaded',timeout=30000)
            browser_setup.progress(state,job,'waiting_for_site_confirmation',
                'Sign in manually to '+site+' in the open Relay browser. Complete verification there, then return to this site and send /browser sites done '+site+'. Do not send passwords or codes in chat. /browser cancel stops setup.')
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                current=state.db.execute('SELECT j.status,l.confirmed,s.status,c.revision FROM provider_jobs j JOIN browser_site_logins l ON l.job=j.id JOIN browser_sites s ON s.origin=l.origin JOIN browser_account_source c ON c.id=1 WHERE j.id=?',(job,)).fetchone()
                if current[0]!='running':return
                if current[2]=='removed' or current[3]!=revision:raise ValueError('Site access changed.')
                if current[1]:
                    if origin(page.url)!=site or host_browser_accounts.login_required(page):
                        raise ValueError('Return to the signed-in site before confirming.')
                    with transaction(state.db):
                        # Confirmation and completion are one receipt, guarded against cancellation.
                        changed=state.db.execute("UPDATE browser_sites SET status='confirmed_by_user',updated=? WHERE origin=? AND revision=? AND status!='removed' AND EXISTS (SELECT 1 FROM provider_jobs WHERE id=? AND status='running') AND EXISTS (SELECT 1 FROM browser_account_source WHERE revision=?)",(time.time(),site,revision,job,revision)).rowcount
                        if changed:browser_setup.finish(state,job,True,'Saved sign-in for '+site+' confirmed by you. Session reuse is enabled for this site; authentication is checked when used. No task was submitted.')
                    return
                page.wait_for_timeout(500)
            raise ValueError('Manual sign-in timed out.')
    except Exception:
        browser_setup.finish(state,job,False,'Manual sign-in was not confirmed for '+site+'. Check the browser connection and complete sign-in on that exact site, then use /browser sites login '+site+' to try again. No task was submitted.')


def main(argv=None):
    import argparse
    from .relay_paths import PATHS
    from .bridge import State
    from .general_browser import profile_lock
    from . import host_browser_accounts
    parser=argparse.ArgumentParser(description='Manage approved account sites and the explicitly connected local browser.')
    sub=parser.add_subparsers(dest='action')
    for action in ('add','login','done','remove'):
        sub.add_parser(action).add_argument('url')
    sub.add_parser('list');sub.add_parser('managed')
    sub.add_parser('attach').add_argument('--endpoint',required=True)
    args=parser.parse_args(argv)
    state=State(PATHS.state)
    try:
        if args.action in ('attach','managed'):
            # Resolve and test the exact browser connection before mutating state.
            endpoint=host_browser_accounts.resolve_endpoint(args.endpoint) if args.action=='attach' else None
            with profile_lock(PATHS.data,PROFILE):
                if endpoint:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as runtime:
                        remote=host_browser_accounts.attach(runtime,endpoint)
                        remote.close()
                set_source(state.db,endpoint)
            print('Account browser connection saved. Confirm each site again before task access. Existing browser tabs were not changed.')
        else:
            arg='sites '+(args.action or 'list')+(' '+args.url if hasattr(args,'url') else '')
            print(command(state,arg,'local-sites:'+secrets.token_hex(16),'telegram'))
        return 0
    except Exception:
        # CDP connection errors may contain the private browser endpoint.
        parser.exit(2,'Account browser setup failed. Check the exact site, local debugging endpoint and current sign-in state.\n')
    finally:state.db.close()
