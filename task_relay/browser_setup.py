"""Chat-started browser login. Credentials stay on the provider's browser page."""
import json
import secrets
import time
from orchestrator.storage import transaction
from . import relay_channels


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS browser_setup_requests(
        source TEXT PRIMARY KEY, request TEXT NOT NULL, job TEXT,
        channel TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS browser_setup_progress(
        job TEXT PRIMARY KEY, phase TEXT NOT NULL, updated REAL NOT NULL);''')


def notice(state,job,suffix,text):
    row=state.db.execute('SELECT channel FROM browser_setup_requests WHERE job=?',(job,)).fetchone()
    channel=row['channel'] if row else 'telegram'
    event='browser-setup:'+job+':'+suffix
    state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)',(event,channel))
    state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,\'\',?)',(event,text))


def status(state):
    row=state.db.execute("SELECT j.status,p.phase,p.updated FROM provider_jobs j LEFT JOIN browser_setup_progress p ON p.job=j.id WHERE j.provider='perplexity' AND j.operation='browser_login' ORDER BY j.created_at DESC LIMIT 1").fetchone()
    if not row:return 'Perplexity browser is not connected. Use /browser connect to open sign-in on the Relay computer.'
    phase=row['phase'] or row['status']
    if row['status']=='completed':return 'Perplexity browser sign-in was verified. Session expiry is checked when used. Conversation execution and Telegram task routing are still in the pilot stage.'
    if row['status'] in ('failed','cancelled'):return 'Perplexity browser setup '+row['status']+'. Use /browser connect to try again.'
    return 'Perplexity browser setup: '+phase+'. Sign in on the Relay computer; the result will return here. /browser cancel stops setup.'


def command(state,arg,source,channel='telegram'):
    if channel not in ('telegram','messages'):raise ValueError('Unsupported setup channel')
    action=arg.strip().lower() or 'status'
    if action not in ('connect','status','cancel'):
        raise ValueError('Use /browser connect, /browser status or /browser cancel. Never send login credentials here.')
    with transaction(state.db):
        old=state.db.execute('SELECT * FROM browser_setup_requests WHERE source=?',(source,)).fetchone()
        if old:
            if old['request']!=arg or old['channel']!=channel:raise ValueError('Setup request identity changed')
            return 'Browser setup request already recorded. '+status(state)
        job=None;created=False
        if action=='connect':
            active=state.db.execute("SELECT id FROM provider_jobs WHERE provider='perplexity' AND status IN ('queued','running')").fetchone()
            if active:job=active['id']
            else:
                job=secrets.token_hex(16);created=True
                state.db.execute('INSERT INTO provider_jobs VALUES (?,?,?,?,?)',(job,'perplexity','browser_login','queued',time.time()))
        elif action=='cancel':
            rows=state.db.execute("SELECT id FROM provider_jobs WHERE provider='perplexity' AND status IN ('queued','running')").fetchall()
            for row in rows:
                state.db.execute("UPDATE provider_jobs SET status='cancelled' WHERE id=?",(row['id'],))
                notice(state,row['id'],'cancelled','Perplexity setup cancelled. Saved browser sign-in data is retained. No task was submitted.')
        state.db.execute('INSERT INTO browser_setup_requests VALUES (?,?,?,?,?)',(source,arg,job,channel,time.time()))
        if created:
            notice(state,job,'queued','Perplexity sign-in queued. A dedicated browser will open on the computer running Relay. Sign in there; Relay will detect completion and report here. Do not send passwords or login codes in chat. No task will be submitted.')
    return status(state)


def progress(state,job,phase,text):
    with transaction(state.db):
        if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND status='running'",(job,)).fetchone():return False
        state.db.execute('INSERT OR REPLACE INTO browser_setup_progress VALUES (?,?,?)',(job,phase,time.time()))
        notice(state,job,phase,text)
    return True


def finish(state,job,ok,text):
    with transaction(state.db):
        changed=state.db.execute("UPDATE provider_jobs SET status=? WHERE id=? AND status IN ('queued','running')",('completed' if ok else 'failed',job)).rowcount
        if changed:
            state.db.execute('INSERT OR REPLACE INTO browser_setup_progress VALUES (?,?,?)',(job,'verified' if ok else 'failed',time.time()))
            notice(state,job,'finished',text)


def run_login(state,job,driver_factory=None,timeout=600):
    from .perplexity_browser import profile_lock,browser_page,HOME_URL
    from pathlib import Path
    if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND status='running'",(job,)).fetchone():return
    data=Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent
    try:
        with profile_lock(data) as root:
            with (driver_factory or browser_page)(root) as driver:
                driver.open()
                if not progress(state,job,'waiting_for_sign_in','Perplexity sign-in is open on the Relay computer. Complete sign-in there and resolve any consent dialog. Select Search. I will confirm here automatically; no terminal step is needed.'):return
                deadline=time.monotonic()+timeout
                while time.monotonic()<deadline:
                    if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND status='running'",(job,)).fetchone():return
                    # Do not inspect identity-provider forms or collect credentials.
                    if driver.page.url==HOME_URL:
                        try:driver.check_ready(driver.snapshot())
                        except ValueError:pass
                        else:
                            finish(state,job,True,'Perplexity browser connected. Your sign-in is saved privately on the Relay computer. No conversation was started. Browser task execution is still being qualified; /browser status shows setup status.')
                            return
                    driver.pause()
                finish(state,job,False,'Perplexity sign-in timed out. Use /browser connect when you can complete sign-in on the Relay computer. No task was submitted.')
    except Exception:
        finish(state,job,False,'Perplexity sign-in could not open or finish. The Relay computer needs its browser component and an available desktop session. Retry with /browser connect; no task was submitted.')


def main():
    import os,sys
    from pathlib import Path
    from .bridge import State
    os.umask(0o077)
    state=State(Path(sys.argv[1]))
    try:run_login(state,sys.argv[2])
    finally:state.db.close()


if __name__=='__main__':main()
