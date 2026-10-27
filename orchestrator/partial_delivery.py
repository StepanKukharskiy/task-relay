"""Read-only partial handoff. Scheduling stops never erase collected candidates.

This projection does not accept outputs, resolve findings, retry work or alter
historical execution state. Only current, collected, byte-verified requested
formats are offered; review judgments remain bound to exact candidate inputs.
"""
import hashlib
import json
from pathlib import Path


def snapshot(rt, report):
    if report['status'] not in ('blocked','uncertain') or report.get('settlement'):return None
    if report.get('uncertainty_progress',{}).get('can_continue'):return None
    tasks={t['id']:t for t in report['tasks']}
    owners=[(t,rt.spec(t)) for t in tasks.values() if rt.spec(t).get('job_owner')]
    if len(owners)!=1:return None
    attempts={a['id']:a for a in report['attempts']}
    if any(a['state'] in ('launching','running','cancelling') for a in attempts.values()):return None
    owner,spec=owners[0]
    required=json.loads(rt.db.execute('SELECT plan FROM production_runs WHERE id=?',(report['id'],)).fetchone()[0])['job_owner']['deliverables']
    candidates=[];unavailable=[];attention=[]
    for a in report['artifacts']:
        task=tasks.get(a['task'])
        if not task or task['id']==owner['id'] or a['attempt']!=task['latest']:continue
        producer=attempts.get(a['attempt'])
        if not producer or producer['state']!='completed':continue
        pspec=rt.spec(task)
        if pspec.get('review_of'):continue
        output=next((o for o in pspec['outputs'] if o['path']==a['path']),None)
        if not output or output.get('media_type') not in required.values():continue
        artifact=rt.artifact(a['id']);blob=Path(artifact['blob'])
        try:
            from .runtime import safe_file
            blob=safe_file(rt.root,str(blob.relative_to(rt.root)))
            raw=blob.read_bytes()
            if len(raw)!=a['bytes'] or hashlib.sha256(raw).hexdigest()!=a['sha256']:raise ValueError('Registered file identity changed')
        except (OSError,ValueError) as exc:
            unavailable.append(dict(artifact=a['id'],path=a['path'],reason=str(exc)));continue
        judgments=[]
        for reviewer in tasks.values():
            if not rt.spec(reviewer).get('review_of') or not reviewer['latest']:continue
            row=rt.db.execute('SELECT frozen,state FROM production_attempts WHERE id=?',(reviewer['latest'],)).fetchone()
            if not row or row['state'] not in ('completed','blocked','uncertain'):continue
            frozen=json.loads(row['frozen'])
            if frozen.get('review_target')!=task['latest']:continue
            if not any(i.get('artifact')==a['id'] and i.get('sha256')==a['sha256'] for i in frozen.get('inputs',[])):continue
            for e in rt.db.execute("SELECT id,data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id",(reviewer['latest'],)):
                data=json.loads(e['data'])
                if data.get('kind')!='model_review':continue
                result=data['result'];decision=result.get('decision')
                judgments.append(dict(attempt=reviewer['latest'],event=e['id'],decision=decision,state=row['state'],
                    summary=result.get('summary',''),findings=result.get('findings',[]),instruction=result.get('instruction','')))
        # Any exact negative judgment remains visible; one accept cannot hide it.
        review_status=('requires_attention' if any(j['decision']!='accept' or j['state']!='completed' for j in judgments) else
                       'reviewed' if judgments and task['status']=='completed' else 'unreviewed')
        candidates.append(dict(artifact=a['id'],task=a['task'],attempt=a['attempt'],path=a['path'],sha256=a['sha256'],
            bytes=a['bytes'],media_type=output['media_type'],review_status=review_status,reviews=judgments))
    from .job_owner import original,ordinary
    if ordinary(original(rt,report['id'])['job_owner']):
        saved={}
        for row in rt.db.execute("SELECT data FROM production_events WHERE run=? AND kind='owner_result_saved' ORDER BY id",(report['id'],)):
            v=json.loads(row[0]);saved[v['deliverable']]=v
        for key,v in saved.items():
            a=rt.artifact(v['artifact'])
            try:
                from .runtime import safe_file
                raw=safe_file(rt.root,str(Path(a['blob']).relative_to(rt.root))).read_bytes()
                if len(raw)!=a['bytes'] or hashlib.sha256(raw).hexdigest()!=v['sha256'] or a['sha256']!=v['sha256']:raise ValueError('Saved result identity changed')
            except (OSError,ValueError) as exc:
                unavailable.append(dict(artifact=a['id'],path=a['path'],reason=str(exc)));continue
            candidates.append(dict(artifact=a['id'],task=None,attempt=None,path=a['path'],sha256=a['sha256'],bytes=a['bytes'],
                media_type=v['media_type'],deliverable=key,review_status='unreviewed',reviews=[]))
    if not candidates:return None
    for t in tasks.values():
        a=attempts.get(t['latest'])
        if a and (a.get('error') or a['state']=='uncertain'):
            attention.append(dict(task=t['id'],attempt=a['id'],state=a['state'],
                                  reason=a.get('error') or 'Outcome remains uncertain; no replay or acceptance inferred.'))
    return dict(version=1,status='partial',execution_status=report['status'],
        summary='Available work is ready; unresolved issues require attention.',
        complete=False,user_acceptance=False,candidates=candidates,unavailable=unavailable,
        required_deliverables=required,
        missing_formats={k:v for k,v in required.items() if not any(a['media_type']==v for a in candidates)},
        attention=attention,
        limitation='Candidate formats are not final role bindings. Individual reviews do not establish complete delivery or user acceptance. Uncertain work remains unresolved; exporting verified files does not reconcile or replay it.')


def lines(delivery):
    result=[delivery['summary'],'']
    labels={'reviewed':'independent review recorded','requires_attention':'candidate requires corrections','unreviewed':'candidate not independently approved'}
    for a in delivery['candidates']:
        result.append(a['path']+' — '+labels[a['review_status']]+'; artifact '+a['artifact'])
    if delivery['missing_formats']:result.append('Not produced: '+', '.join(delivery['missing_formats']))
    result+=['','Still unresolved:']
    result.extend(v['task']+': '+v['reason'] for v in delivery['attention'])
    result.extend(v['path']+': '+v['reason'] for v in delivery['unavailable'])
    result+=['',delivery['limitation']]
    return result
