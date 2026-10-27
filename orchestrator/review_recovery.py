"""Finite review recovery over exact versions; no semantic acceptance inference."""
import json
from . import contracts as c
from .runtime_outcomes import Hold


def identity(rt,run,spec):
    values=[]
    for item in spec['inputs']:
        if item['path'].startswith('execution-evidence/'):continue # code-derived from the same origins
        if 'artifact' in item:a=rt.artifact(item['artifact'])
        else:
            try:a=rt.output(run,item['from_task'],item['output'])
            except ValueError:return None # prospective producer, not repeated review
        values.append((a['attempt'] or '',a['path'] or '',a['sha256']))
    return c.digest(dict(inputs=sorted(set(values)),scope=spec.get('correction_scope')))


def check(rt,run,batch):
    """An unchanged failed assessment needs new evidence, not another reviewer."""
    for task in batch:
        if not task.get('review_snapshot'):continue
        key=identity(rt,run,task)
        if key is None:continue
        for row in rt.db.execute("SELECT frozen,receipt FROM production_attempts WHERE run=? AND state IN ('completed','blocked')",(run,)):
            prior=json.loads(row['frozen'])
            if not prior.get('review_of') or identity(rt,run,prior)!=key:continue
            receipt=json.loads(row['receipt'] or '{}')
            # A failed transport is not a semantic review; it keeps its own recovery.
            from .runtime import safe_file
            from pathlib import Path
            p=Path(prior['workspace'])/'.relay/result.json'
            if not p.exists():continue
            if p.is_symlink() or p.parent.is_symlink():raise ValueError('Linked review report')
            result=json.loads(p.read_text())
            if result.get('decision') not in ('blocked','revise'):continue
            raise Hold('unchanged_failed_review',
                'These exact candidates and evidence already received an unresolved review. '
                'No new evidence or corrected candidate was supplied; another review cannot '
                'repair the recorded prerequisite. Originals are retained; stop this recovery.')


def admission_failure(rt,run,task,spec,backend,inputs,reason):
    """A pre-dispatch failure is not a failed assessment or an unknown send."""
    data=dict(reason=reason,dispatched=False)
    if spec.get('review_of') and not task['attempts'] and task['latest'] is None:
        data['review_admission']=dict(version=1,assignment=task['assignment'],spec_sha256=c.digest(spec),
            target=rt.task(run,spec['review_of'])['latest'],backend=backend,
            inputs=[{k:i[k] for k in ('path','artifact','sha256')} for i in inputs])
    return data


def requeue(rt,run):
    """Recheck an existing unstarted review slot, never replace a semantic gate.

    Only new correlated failure receipts qualify. Original assignments, attempts,
    candidate versions and limits remain intact. Queue mutation commits before
    ordinary claim/dispatch. A stopped owner or any unknown effect forbids recovery.
    """
    from . import worker_capabilities
    with rt.transaction():
        row=rt.db.execute('SELECT status,plan FROM production_runs WHERE id=?',(run,)).fetchone()
        plan=json.loads(row['plan'])
        if row['status']!='active' or not plan.get('job_owner'):return
        owner=next(t for t in plan['tasks'] if t.get('job_owner'))
        if rt.task(run,owner['id'])['status'] not in ('waiting','queued','running','launching'):return
        if rt.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('uncertain','cancelling')",(run,)).fetchone():return
        for task in rt.db.execute("SELECT * FROM production_tasks WHERE run=? AND status='blocked'",(run,)).fetchall():
            spec=rt.spec(task)
            if not spec.get('review_of') or task['latest'] is not None or task['attempts']:continue
            event=rt.db.execute("SELECT id,data FROM production_events WHERE run=? AND task=? AND kind='capability_unavailable' ORDER BY id DESC LIMIT 1",(run,task['id'])).fetchone()
            if not event:continue
            saved=json.loads(event['data']);proof=saved.get('review_admission')
            if not proof or saved.get('dispatched') is not False:continue
            prior=rt.db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND kind='review_admission_requeued'",(run,task['id'])).fetchall()
            if len(prior)>=spec['max_attempts'] or any(json.loads(e['data'])['failure_event']==event['id'] for e in prior):continue
            backend=worker_capabilities.backend_for(spec,plan['backend'])
            if not rt.ready(run,spec):continue
            try:
                inputs=rt.checked_inputs(run,spec,backend)
                expected=admission_failure(rt,run,task,spec,backend,inputs,saved['reason'])['review_admission']
                if proof!=expected:continue
                from .review_snapshot import check
                check(rt,run,spec)
                if not hasattr(rt.factory,'available'):continue
                rt.factory.available(backend)
            except (ValueError,OSError,KeyError,TypeError):continue
            rt.db.execute("UPDATE production_tasks SET status='queued' WHERE run=? AND id=?",(run,task['id']))
            rt.event(run,task['id'],None,'review_admission_requeued',dict(failure_event=event['id'],ordinal=len(prior)+1,proof=proof,dispatched=False))
