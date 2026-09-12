"""Explicit, job/purpose-scoped replacement ledger and conservative output validity."""
import json
import time
from . import contracts as c
from .artifact_dependencies import EDGES, metadata


def scope(db, run):
    row=db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()
    if not row:raise ValueError('Unknown production scope')
    origin=json.loads(row['plan']).get('origin',{})
    if origin.get('job_request_id') is not None:return 'job:'+c.encoded(origin['job_request_id'])
    return 'job:'+c.encoded(run)


def selected(rt, decision):
    row=rt.db.execute('SELECT * FROM production_decisions WHERE id=?',(decision,)).fetchone()
    if not row:raise ValueError('Choose an exact saved selection decision')
    d=dict(row);a=rt.artifact(d['artifact'])
    if a['run']!=d['run'] or a['task']!=d['task'] or not a['attempt']:raise ValueError('Selection artifact ownership differs')
    d['version']={k:a[k] for k in ('id','run','task','attempt','path','sha256','bytes')}
    return d


def member(db, decision):
    rows=db.execute('''SELECT h.* FROM production_replacement_heads h
        JOIN json_each(h.members) m ON m.value=?''',(decision,)).fetchall()
    if len(rows)>1:raise ValueError('Ambiguous replacement history')
    return dict(rows[0]) if rows else None


def describe(rt, old, new):
    a=selected(rt,old);b=selected(rt,new)
    job=scope(rt.db,a['run'])
    if scope(rt.db,b['run'])!=job:raise ValueError('Selections belong to different jobs; no project-wide replacement is inferred')
    if a['purpose']!=b['purpose']:raise ValueError('Selections have different decision purposes')
    if a['artifact']==b['artifact']:raise ValueError('Choose two distinct selected artifact versions')
    head=member(rt.db,old);other=member(rt.db,new)
    if head and head['current_decision']!=old:raise ValueError('The old selection is no longer current; inspect the latest replacement')
    if other and (not head or other['id']!=head['id']):raise ValueError('The new selection belongs to another replacement history')
    return {'scope':job,'purpose':a['purpose'],'head':head['id'] if head else old,
            'expected_revision':head['revision'] if head else 0,'old':a,'new':b,
            'members':list(dict.fromkeys([*(json.loads(head['members']) if head else [old]),new]))}


def affected(rt, head):
    """Current selection is a barrier: revision context must not invalidate itself."""
    db=rt.db
    runs=[r['id'] for r in db.execute('SELECT id FROM production_runs') if scope(db,r['id'])==head['scope']]
    decisions=json.loads(head['members']) if isinstance(head['members'],str) else head['members']
    current=selected(rt,head['current_decision'])['artifact']
    roots=sorted({selected(rt,d)['artifact'] for d in decisions}-{current})
    if not roots:return []
    rm=','.join('?' for _ in runs);sm=','.join('?' for _ in roots)
    rows=db.execute('''WITH RECURSIVE edges AS ('''+EDGES+'''), impacted(id) AS (
        SELECT id FROM production_artifacts WHERE id IN ('''+sm+''')
        UNION SELECT e.output FROM edges e JOIN impacted i ON i.id=e.input WHERE e.output!=?)
        SELECT i.id FROM impacted i JOIN production_artifacts a ON a.id=i.id
        WHERE a.run IN ('''+rm+''')''',(*roots,current,*runs)).fetchall()
    return sorted(r['id'] for r in rows)


def preview(rt, old, new):
    with rt.transaction():
        d=describe(rt,old,new)
        head={'scope':d['scope'],'members':d['members'],'current_decision':new}
        ids=affected(rt,head)
        return {**d,'affected_count':len(ids),'affected_outputs':[metadata(rt.db,i) for i in ids[:50]],
                'outputs_truncated':len(ids)>50,
                'note':'Declared input dependencies are conservative. Running results and future consumers in this job are also tracked. No assignments change or rebuilds start.'}


def refresh(rt, job):
    """Called inside output registration/replacement transaction, including late results."""
    if not rt.db.in_transaction:raise ValueError('Validity refresh requires a transaction')
    for row in rt.db.execute('SELECT * FROM production_replacement_heads WHERE scope=?',(job,)).fetchall():
        h=dict(row);ids=set(affected(rt,h))
        replacement=rt.db.execute('SELECT id FROM production_replacements WHERE head=? AND revision=?',(h['id'],h['revision'])).fetchone()['id']
        existing={r['artifact']:dict(r) for r in rt.db.execute('SELECT * FROM production_artifact_validity WHERE head=?',(h['id'],))}
        for aid in ids|existing.keys():
            outdated=int(aid in ids)
            if aid in existing and existing[aid]['outdated']==outdated and existing[aid]['replacement']==replacement:continue
            reason=c.encoded({'scope':job,'purpose':h['purpose'],'current_decision':h['current_decision'],
                'basis':'Exact superseded selection or transitive declared input dependency; semantic use is not proved.'})
            rt.db.execute('''INSERT INTO production_artifact_validity VALUES (?,?,?,?,?)
                ON CONFLICT(artifact,head) DO UPDATE SET replacement=excluded.replacement,
                outdated=excluded.outdated,reason=excluded.reason''',(aid,h['id'],replacement,outdated,reason))
            a=rt.artifact(aid)
            rt.event(a['run'],a['task'],a['attempt'],'artifact_validity_changed',
                     {'artifact':aid,'head':h['id'],'replacement':replacement,'outdated':bool(outdated),'reason':json.loads(reason)})


def replace(rt, old, new, expected_revision, receipt, note):
    from .runtime import file_hash,safe_file
    from pathlib import Path
    c.nonempty(note,'replacement decision note');c.nonempty(receipt,'replacement receipt')
    if type(expected_revision) is not int or expected_revision<0:raise ValueError('Use the exact replacement revision')
    with rt.transaction():
        done=rt.db.execute('SELECT * FROM production_replacements WHERE id=?',(receipt,)).fetchone()
        if done:
            if (done['old_decision'],done['new_decision'],done['revision'],done['note'])!=(old,new,expected_revision+1,note):raise ValueError('Replacement receipt identity differs')
            return dict(done)
        d=describe(rt,old,new)
        if d['expected_revision']!=expected_revision:raise ValueError('Replacement state changed; request a fresh decision card')
        for decision in (d['old'],d['new']):
            a=rt.artifact(decision['artifact']);p=Path(a['blob'])
            p=safe_file(Path(p.anchor),str(p.relative_to(p.anchor)))
            if p.stat().st_size!=a['bytes'] or file_hash(p)!=a['sha256']:raise ValueError('Selected artifact content changed')
        rt.db.execute('''INSERT INTO production_replacement_heads VALUES (?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET current_decision=excluded.current_decision,
            revision=excluded.revision,members=excluded.members''',
            (d['head'],d['scope'],d['purpose'],new,expected_revision+1,c.encoded(d['members'])))
        rt.db.execute('INSERT INTO production_replacements VALUES (?,?,?,?,?,?,?)',
            (receipt,d['head'],expected_revision+1,old,new,note,time.time()))
        rt.event(d['new']['run'],d['new']['task'],d['new']['version']['attempt'],'artifact_replacement_selected',
                 {**d,'receipt':receipt,'note':note})
        refresh(rt,d['scope'])
        return dict(rt.db.execute('SELECT * FROM production_replacements WHERE id=?',(receipt,)).fetchone())


def view(db, run):
    job=scope(db,run)
    heads=[dict(h) for h in db.execute('SELECT * FROM production_replacement_heads WHERE scope=? ORDER BY id LIMIT 51',(job,))]
    heads_truncated=len(heads)>50;heads=heads[:50]
    for h in heads:
        members=json.loads(h['members']);h['members']=list(dict.fromkeys([h['current_decision'],*members[:200]]))
        h['members_truncated']=len(members)>200
        history=[dict(r) for r in db.execute('SELECT id,revision,old_decision,new_decision,created FROM production_replacements WHERE head=? ORDER BY revision DESC LIMIT 21',(h['id'],))]
        h['history']=list(reversed(history[:20]));h['history_truncated']=len(history)>20
    rows=[dict(r) for r in db.execute('''SELECT v.*,a.path,a.run,a.task FROM production_artifact_validity v
        JOIN production_artifacts a ON a.id=v.artifact JOIN production_replacement_heads h ON h.id=v.head
        WHERE h.scope=? AND v.outdated=1 ORDER BY a.run,a.path,v.head LIMIT 201''',(job,))]
    for r in rows:r['reason']=json.loads(r['reason'])
    return {'scope':job,'heads':heads,'outdated_outputs':rows[:200],'truncated':len(rows)>200 or heads_truncated or any(h['members_truncated'] or h['history_truncated'] for h in heads),
            'note':'Outdated means supplied superseded input or an older selection in this job/purpose. It does not change historical acceptance or authorize execution.'}
