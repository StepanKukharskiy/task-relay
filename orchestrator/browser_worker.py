"""General browser worker using the shared bounded API loop and supervisor."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator import executors
from orchestrator.gemini_worker import execute,Files
from orchestrator.workers import atomic
from task_relay import general_browser
from task_relay.browser_journal import Journal,UncertainAction


def support_hashes():
    root=Path(general_browser.__file__).parent
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('general_browser.py','browser_journal.py','browser_sites.py','host_browser_accounts.py','api_providers.py')}


def configured(provider='gemini'):
    config,backend=executors.configured() if provider=='gemini' else executors.configured(provider)
    return config,{**backend,'type':provider+'-browser'}


def run(frozen,control,db,data,*,client=None,config_reader=None,driver_context=None):
    control=Path(control);journal=Journal(db);profile=frozen['browser']['profile']
    try:
        from task_relay.host import verify_support
        verify_support(frozen)
        launch=json.loads((control/'launch.json').read_text())
        if client is None:
            for name in ('browser_worker.py','browser_contract.py','gemini_worker.py','executors.py'):
                if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=frozen.get('runtime_sources',{}).get(name):
                    raise ValueError('Browser implementation changed after assignment was frozen')
            if launch.get('browser_support')!=support_hashes():raise ValueError('Browser host implementation changed')
        provider=frozen['backend']['type'].removesuffix('-browser')
        reader=config_reader or (lambda:configured(provider))
        config,backend=reader()
        if backend!=frozen['backend'] or executors.fingerprint(config,backend)!=launch['credential_fingerprint']:
            raise ValueError('Selected browser provider connection changed')
        Files(frozen)  # Verify declared text inputs before launching a browser.
        if list(control.glob('api-*.request.json')):raise UncertainAction('Existing provider request receipts prohibit worker replay')
        if (control/'cancel.json').exists():raise ValueError('Cancelled before browser launch')
        with (driver_context or general_browser.browser(data,frozen['browser'])) as driver:
            if journal.pending(profile):raise UncertainAction('Inspect unresolved profile actions before starting another worker')
            session=general_browser.Session(db,frozen['assignment_id'],frozen['browser'],driver,
                        cancelled=lambda:(control/'cancel.json').exists())
            return execute(frozen,control,client,reader,browser=session)
    finally:
        actions=[dict(r) for r in db.execute('SELECT id,status FROM general_browser_actions WHERE job=? ORDER BY created,id',(frozen['assignment_id'],))]
        atomic(control/'browser-result.json',{'profile':profile,'job':frozen['assignment_id'],
                    'actions':actions,'uncertain_actions':journal.pending(profile),
                    'tabs':journal.tabs(profile),'live_tabs':'detached after worker exit'})


def main():
    from task_relay.relay_paths import PATHS
    os.umask(0o077);control=Path(sys.argv[1]);workspace=Path(sys.argv[2])
    frozen=json.loads((workspace/'.relay/ASSIGNMENT.json').read_text())
    try:
        PATHS.data.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(PATHS.state,timeout=30)) as db:run(frozen,control,db,PATHS.data)
    except Exception as exc:
        atomic(control/'agent-result.json',{'outcome':'uncertain' if isinstance(exc,UncertainAction) else 'failed',
                                         'reason':type(exc).__name__+': '+str(exc)})
        raise SystemExit(1)


if __name__=='__main__':main()
