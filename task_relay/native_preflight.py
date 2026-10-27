"""Direct continuation of adapter-proved, unchanged native read operations."""
import hashlib,json
from orchestrator import contracts as c


def validate_dispatch(rt,task,spec,backend,inputs):
    from .completion_recovery import registered_preflight_gap,DELIVERY_POLICY
    revision=spec['revision'];old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(revision['previous_attempt'],)).fetchone()
    if not old or old['run']!=task['run'] or old['task']!=task['id'] or old['state']!='blocked' or task['latest']!=old['id']:raise ValueError('Native continuation parent changed')
    frozen=json.loads(old['frozen']);proof=registered_preflight_gap(rt,old,json.loads(old['receipt']))
    if not proof or proof!=revision['proof']:raise ValueError('Native preflight evidence changed')
    original=rt.spec(dict(task,assignment=old['assignment']));expected={**original,'max_attempts':max(original['max_attempts'],task['attempts']+1),'revision':revision}
    if spec!=expected or backend!=frozen['backend']:raise ValueError('Native continuation changed scope')
    identities=lambda rows:sorted((i['path'],i['artifact'],i['sha256']) for i in rows)
    if identities(inputs)!=identities(frozen['inputs']):raise ValueError('Native continuation input versions changed')
    rows=rt.db.execute('SELECT r.baseline,g.policy FROM completion_recoveries r JOIN completion_recovery_grants g ON g.pipeline=r.pipeline WHERE r.parent=?',(task['run'],)).fetchall()
    matched=[r for r in rows if hashlib.sha256(r['baseline'].encode()).hexdigest()==revision['baseline_sha256']]
    if len(matched)!=1 or json.loads(matched[0]['policy'])!=DELIVERY_POLICY:raise ValueError('Native continuation lacks committed allocation')
    baseline=json.loads(matched[0]['baseline'])
    for saved in baseline['attempts']:
        actual=rt.db.execute('SELECT frozen,receipt FROM production_attempts WHERE id=?',(saved['id'],)).fetchone()
        if not actual or any(hashlib.sha256(actual[k].encode()).hexdigest()!=saved[k+'_sha256'] for k in ('frozen','receipt')):raise ValueError('Native continuation receipt changed')
    events=rt.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='native_preflight_continued' AND json_extract(detail,'$.parent')=?",(task['run'],))
    if not any((v:=json.loads(r[0])).get('baseline_sha256')==revision['baseline_sha256'] and v.get('assignment_sha256')==c.digest(spec) for r in events):raise ValueError('Native continuation lacks committed intent')


def queue(state,rt,p,s,baseline,cycle):
    from .continuation_owner import queue as continue_owned
    return continue_owned(state,rt,p,s,baseline,cycle,'registered_input_preflight','existing completion allocation')
