"""Safari adapter for the existing bounded API worker and process supervisor."""
from contextlib import ExitStack,closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator import executors
from orchestrator.computer_contract import validate
from orchestrator.gemini_worker import execute,Files
from orchestrator.workers import atomic
from orchestrator.storage import transaction
from task_relay import computer_sessions as journal
from task_relay.computer_worker_session import Session
from task_relay.browser_journal import UncertainAction


def support_hashes():
    root=Path(journal.__file__).parent
    names=('computer_sessions.py','computer_target.py','computer_worker_session.py','job_ownership.py','result_handoff.py','api_providers.py','gemini.py','computer_contract.py','computer_use.py','host_computer.py','assets/macos/ComputerObserver.swift')
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


def run(frozen,control,db,*,client=None,config_reader=None,helper=None,lease_context=None):
    from task_relay.host_computer import Observer,lease
    db.row_factory=sqlite3.Row
    control=Path(control)
    if (control/'computer-result.json').exists():raise UncertainAction('Existing computer receipt prohibits worker replay.')
    policy=validate(frozen['computer']);ident=None;session=None;completed=False
    try:
        if client is None:
            from task_relay.computer_target import verify_policy
            verify_policy(policy)
            for name in ('computer_worker.py','computer_contract.py','gemini_worker.py','executors.py'):
                if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=frozen.get('runtime_sources',{}).get(name):raise ValueError('Computer worker changed after dispatch.')
            if json.loads((control/'launch.json').read_text()).get('computer_support')!=support_hashes():raise ValueError('Native support changed after dispatch.')
        Files(frozen)
        if list(control.glob('api-*.request.json')):raise UncertainAction('Saved provider requests prohibit worker replay.')
        if (control/'cancel.json').exists():raise ValueError('Cancelled before Safari session launch.')
        with ExitStack() as stack:
            stack.enter_context(lease_context or lease())
            helper=helper or Observer(policy['helper'])
            if helper.identity!=policy['identity']:raise ValueError('Selected helper build changed.')
            if policy['spec']['target']==journal.contract.SCRIPTING_WINDOW:
                helper.require_scripting_ready()
            elif hasattr(helper,'require_ready'):helper.require_ready()
            with transaction(db):journal.initialize(db)
            # Resolve an existing pipeline or register the approved standalone
            # plan under the same identity used by result export and deletion.
            owners={r[0] for r in db.execute("SELECT pipeline FROM relay_pipeline_steps WHERE target_kind='production_run' AND target=?",(frozen['run'],))}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_plans'").fetchone():
                owners.update(r[0] for r in db.execute("SELECT s.pipeline FROM relay_pipeline_steps s JOIN production_plans p ON p.id=s.target WHERE s.target_kind='plan_production' AND p.run=?",(frozen['run'],)))
            if len(owners)>1:raise ValueError('Safari research has ambiguous pipeline ownership.')
            if db.execute("SELECT 1 FROM relay_computer_actions WHERE state IN ('claimed','uncertain') AND resolved=0").fetchone():raise UncertainAction('Reconcile unresolved native actions before another worker.')
            provider=executors.provider_for(frozen['backend'])
            reader=config_reader or (lambda:executors.configured_worker(provider,'computer'))
            config,backend=reader()
            launch=json.loads((control/'launch.json').read_text())
            if backend!=frozen['backend'] or executors.fingerprint(config,backend)!=launch['credential_fingerprint']:raise ValueError('Selected computer provider connection changed.')
            with transaction(db):
                if owners:
                    job=next(iter(owners))
                else:
                    from task_relay import job_ownership,result_handoff
                    plans=list(db.execute("SELECT id,channel FROM production_plans WHERE run=? AND status='started'",(frozen['run'],)))
                    if len(plans)!=1:raise ValueError('Safari research needs one approved standalone plan or saved pipeline owner.')
                    state=SimpleNamespace(db=db,channel=plans[0]['channel'])
                    root,_,ancestors=result_handoff.ancestry(state,frozen['run'])
                    roots=[p for p in ancestors if db.execute('SELECT 1 FROM production_plans WHERE id=? AND parent_id IS NULL',(p,)).fetchone()]
                    if roots!=[root]:raise ValueError('Safari research has ambiguous standalone ancestry.')
                    job=job_ownership.record_standalone(db,root,frozen['run'],state.channel)
                ident=journal.approve(db,job=job,request_key='worker:'+frozen['assignment_id'],
                    exact_request=frozen['instruction'],spec=policy['spec'],helper=helper.identity,
                    output_root=control/'computer-evidence',actor='approved production assignment '+frozen['assignment_id'])
            driver=stack.enter_context(helper.session())
            session=Session(db,ident,driver,control,frozen['role']+' · '+frozen['id']+' · '+frozen['assignment_id'][:8])
            provider=executors.provider_for(frozen['backend'])
            reader=config_reader or (lambda:executors.configured_worker(provider,'computer'))
            session.initial=session.call('initial-observation','computer_observe',{'token':''})
            result=execute(frozen,control,client,reader,computer=session)
            completed=True
            return result
    finally:
        if session:session.close(completed)
        history=journal.actions(db,ident) if ident else []
        atomic(control/'computer-result.json',{'worker':frozen['assignment_id'],'assignment':ident,
            'failure':session.failure if session else None,
            'actions':[{'id':a['id'],'state':a['state']} for a in history],
            'unexecuted_actions':session.action_gaps() if session else [],
            'uncertain_actions':[a['id'] for a in history if a['state'] in ('claimed','uncertain') and not a['resolved']],
            'state':journal.get(db,ident)['state'] if ident else 'not_started'})


def main():
    from task_relay.relay_paths import PATHS
    os.umask(0o077);control=Path(sys.argv[1]);workspace=Path(sys.argv[2])
    frozen=json.loads((workspace/'.relay/ASSIGNMENT.json').read_text())
    try:
        with closing(sqlite3.connect(PATHS.state,timeout=30,isolation_level=None)) as db:run(frozen,control,db)
    except Exception as exc:
        atomic(control/'agent-result.json',{'outcome':'uncertain' if isinstance(exc,UncertainAction) else 'failed','reason':type(exc).__name__+': '+str(exc)})
        raise SystemExit(1)


if __name__=='__main__':main()
