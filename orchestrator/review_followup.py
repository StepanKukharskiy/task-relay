"""Carry review defects through the existing assignments/reports, without a scheduler.

The event journal owns finding identity. Resolution is an independent judgment on
exact new evidence, never a producer claim or a global 'resolved' boolean.
"""
import copy
import hashlib
import json
from . import contracts as c

CRITERION='Resolve every carried review finding against this exact candidate.'
INSTRUCTIONS='''Carried review findings remain mandatory. Repair each concrete defect; a
new filename, successful build, disclaimer or repeated earlier acceptance does not
resolve it. Independently assess every finding in review_followup on this candidate.
Use resolved only with precise inspected candidate/evidence locations showing the
repair. Otherwise use unresolved and revise or blocked. Missing requested images
require actual suitable images, not an unavailable-image label. Findings about
meaning and visual fit still require semantic inspection; code checks are not proof.'''


REPAIR_INSTRUCTIONS="""Address only the finding IDs in correction_context within this
assignment's declared outputs and tools. Other job findings remain the owner's
obligations; unrelated downstream defects do not block this helper's deliverable.
Inspect evidence relevant to the assigned repair, not every historical artifact.
Report concrete unresolved assigned defects honestly. A helper's delivery is not
independent approval or final job acceptance."""


def scoped(plan):return plan.get('job_owner',{}).get('correction_scope_version')==1


def repair_issues(rt,plan,frozen):
    target=frozen
    if frozen.get('review_of'):
        row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(frozen.get('review_target'),)).fetchone()
        target=json.loads(row[0]) if row else rt.spec(rt.task(plan['id'],frozen['review_of']))
    scope=target.get('correction_scope',dict(version=1,findings=[]))
    if set(scope)!={'version','findings'} or scope['version']!=1 or not isinstance(scope['findings'],list) or any(not isinstance(x,str) for x in scope['findings']) or len(set(scope['findings']))!=len(scope['findings']):
        raise ValueError('Invalid correction scope')
    known={i['id']:i for i in findings(rt,plan['id'])}
    if not set(scope['findings'])<=set(known):raise ValueError('Correction scope contains unknown job findings')
    return [known[key] for key in scope['findings']]


def enabled(plan):return plan.get('review_followup_version')==1


def final_review(rt,plan,frozen):
    if not frozen.get('review_of'):return False
    if not plan.get('job_owner'):return True
    media=set(plan['job_owner']['deliverables'].values())
    if frozen.get('review_snapshot'):return True
    if scoped(plan):
        row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(frozen.get('review_target'),)).fetchone()
        target=json.loads(row[0]) if row else rt.spec(rt.task(plan['id'],frozen['review_of']))
        # A scoped repair remains a helper even when its output type matches a
        # final deliverable. covers() and job_complete still require every
        # applicable/global obligation before that artifact can be delivered.
        if target.get('correction_scope'):return False
        return any(o.get('media_type') in media for o in target['outputs'])
    return any(i.get('media_type') in media for i in frozen['inputs'])


def findings(rt,run,*,target=None):
    """Read only validated reports; preserve original failures and exact provenance."""
    inherited=rt.db.execute("SELECT data FROM production_events WHERE run=? AND kind='review_findings_inherited' ORDER BY id",(run,)).fetchall()
    result=[issue for row in inherited for issue in json.loads(row['data'])['findings'] if target is None]
    for row in rt.db.execute("SELECT e.id,e.attempt,e.data,a.frozen FROM production_events e JOIN production_attempts a ON a.id=e.attempt WHERE e.run=? AND e.kind='checks_recorded' ORDER BY e.id",(run,)):
        event=json.loads(row['data']);f=json.loads(row['frozen'])
        if event.get('kind')!='model_review' or target is not None and f.get('review_of') not in ([target] if isinstance(target,str) else target):continue
        r=event['result']
        issues=[dict(kind=x['category'],message=x['message'],evidence=x['evidence']) for x in r.get('findings',[]) if x['category']!='advisory']
        for check in r['checks']:
            if check['passed'] or check['criterion']==f.get('review_followup',{}).get('criterion'):continue
            issues.append(dict(kind='criterion',message=f['criteria'][check['criterion']-1],evidence=check['evidence']))
        if r['decision']=='revise' and not issues:
            followup=f.get('review_followup',{})
            check=next((v for v in r['checks'] if v['criterion']==followup.get('criterion')),None)
            pending=check and any(v['verdict']=='unresolved' for v in json.loads(check['evidence']).values())
            if not pending:issues=[dict(kind='revision',message=r['instruction'],evidence=r['summary'])]
        for index,issue in enumerate(issues):
            ident=hashlib.sha256(c.encoded([run,row['id'],index,issue]).encode()).hexdigest()[:24]
            result.append(dict(id=ident,review_attempt=row['attempt'],target=f['review_of'],
                candidate_attempt=f.get('review_target'),issue=issue))
    return result


def applicable(rt,plan,frozen):
    """Findings follow candidate lineage and registered output/scope identity.

    Sharing an image or source is not derivation from another candidate. Final
    delivery separately requires the union of its reviews to cover all findings,
    so omitting a rejected branch cannot silently discard its obligations.
    """
    if not plan.get('job_owner'):
        target=frozen.get('review_of',frozen.get('id'))
        source=frozen.get('revision',{}).get('source','')
        if not frozen.get('review_of') and source.startswith('model_review:'):
            row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(source.split(':',1)[1],)).fetchone()
            if row:target=[target,json.loads(row[0]).get('review_of')]
        return findings(rt,plan['id'],target=target)
    def attempt(ident):
        row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(ident,)).fetchone() if ident else None
        return json.loads(row[0]) if row else None
    candidate=attempt(frozen.get('review_target'))
    if candidate is None and frozen.get('review_of'):
        row=rt.db.execute('SELECT a.frozen FROM production_tasks t JOIN production_attempts a ON a.id=t.latest WHERE t.run=? AND t.id=?',(plan['id'],frozen['review_of'])).fetchone()
        if row:candidate=json.loads(row[0])
    candidate=candidate or frozen
    lineage=set();seen=set()
    def visit(value):
        key=(value.get('run',plan['id']),value.get('id'))
        if key in seen:return
        seen.add(key);lineage.add(key)
        for item in value.get('inputs',[]):
            parent=None
            if item.get('artifact'):
                artifact=rt.artifact(item['artifact']);parent=attempt(artifact.get('attempt'))
            elif item.get('from_task'):
                row=rt.db.execute('SELECT a.frozen FROM production_tasks t JOIN production_attempts a ON a.id=t.latest WHERE t.run=? AND t.id=?',(key[0],item['from_task'])).fetchone()
                if row:parent=json.loads(row[0])
            if parent:visit(parent)
    visit(candidate)
    media={o.get('media_type') for o in candidate.get('outputs',[])}
    if candidate is frozen and frozen.get('review_of'):
        media={i.get('media_type') for i in frozen.get('inputs',[]) if i.get('from_task')==frozen['review_of']}
        if not media:return findings(rt,plan['id']) # no candidate identity cannot prove an unrelated scope
    from collections import Counter
    delivery_types=Counter(plan['job_owner']['deliverables'].values())
    roles={m for m in media if delivery_types[m]==1}
    def scope(value):
        from .operation_contracts import REGISTRY
        contract=value.get('operation_contract',{});params=contract.get('parameters',{})
        rule=REGISTRY.get((contract.get('id'),contract.get('version')),{}).get('planning_interface',{}).get('review_scope')
        if not rule:return None
        source=next((i for i in value.get('inputs',[]) if i['path']==params.get(rule['source_parameter'])),None)
        if not source:return None
        digest=source.get('sha256') or (rt.artifact(source['artifact'])['sha256'] if source.get('artifact') else None)
        if not digest:return None
        bounds=params.get(rule['range_parameter'],[0,params[rule['maximum_parameter']]])
        return (contract['id'],digest,tuple(bounds))
    current_scope=scope(candidate);result=[]
    for issue in findings(rt,plan['id']):
        old=attempt(issue.get('candidate_attempt'))
        previous_review=attempt(issue.get('review_attempt'))
        run=(old or previous_review or {}).get('run',plan['id'])
        related=(run,issue['target']) in lineage or issue['target']==frozen.get('review_of',frozen.get('id'))
        if old:
            related=related or bool(roles & {o.get('media_type') for o in old.get('outputs',[])})
            previous_scope=scope(old)
            if current_scope and previous_scope and current_scope[:2]==previous_scope[:2]:
                a,b=current_scope[2],previous_scope[2]
                related=max(a[0],b[0])<min(a[1],b[1])
        elif len(delivery_types)==1 and roles:
            related=True # conservative inherited single-deliverable obligation
        if related:result.append(issue)
    return result


def inherit(rt,previous,run,*,capacity_authorization=None):
    """Trusted continuation admission carries defects, never acceptance.

    Call inside the same transaction that admits an explicitly authorized successor.
    The immutable event captures the original finding identities and provenance.
    This function is not an owner tool and cannot authorize or dispatch work.
    Capacity can exceed the remainder only with a caller-supplied exact user
    authorization receipt. Trusted callers must obtain that approval externally;
    model output or a generic instruction to continue is not such authorization.
    """
    from .job_owner import original
    with rt.transaction():
        old=original(rt,previous);new=original(rt,run)
        prior=rt.status(previous);current=rt.status(run)
        if not old.get('job_owner') or not new.get('job_owner') or not enabled(new):
            raise ValueError('Finding inheritance requires compatible owner jobs')
        if old['brief']!=new['brief'] or old['backend']!=new['backend']:
            raise ValueError('Continuation must preserve the exact request and provider')
        if prior['status'] not in ('paused','blocked') or any(a['state'] not in ('completed','blocked') for a in prior['attempts']):
            raise ValueError('Continuation requires a quiescent predecessor without uncertain attempts')
        if current['attempts']:raise ValueError('Findings must be inherited before dispatch')
        a=old['job_owner'];b=new['job_owner']
        owner=next(t for t in prior['tasks'] if t['id']=='owner')
        remaining=dict(owner_turns=max(0,a['owner_turns']-owner['attempts']),
            max_tasks=max(0,a['max_tasks']-(len(prior['tasks'])-1)))
        added={key:max(0,b[key]-value) for key,value in remaining.items()}
        if any(added.values()) and capacity_authorization is None:
            raise ValueError('Continuation cannot expand remaining capacity')
        if capacity_authorization is not None:
            proof=capacity_authorization
            expected=dict(version=1,previous=previous,successor=run,prior_plan_sha256=c.digest(old),
                successor_plan_sha256=c.digest(new),additional_capacity=added)
            if (not isinstance(proof,dict) or set(proof)!=set(expected)|{'user_request','user_reply'}
                    or any(proof.get(k)!=v for k,v in expected.items())
                    or any(not isinstance(proof.get(k),str) or not proof[k].strip() for k in ('user_request','user_reply'))
                    or type(proof.get('version')) is not int
                    or not isinstance(proof.get('additional_capacity'),dict)
                    or any(type(v) is not int for v in proof['additional_capacity'].values())):
                raise ValueError('Continuation capacity authorization must match exact plans and added capacity')
        for key in ('workers','operation_backends','task_limits','task_attempts','deliverables','authoring_policy','generation_recovery'):
            if a.get(key)!=b.get(key):raise ValueError('Continuation changed original authority: '+key)
        if set(a['operations'])!=set(b['operations']):raise ValueError('Continuation changed available operations')
        allowed=set(a['inputs'])|{v['id'] for v in prior['artifacts']}
        if not set(a['inputs'])<=set(b['inputs'])<=allowed:raise ValueError('Continuation changed original evidence scope')
        data=dict(previous=previous,prior_plan_sha256=c.digest(old),findings=findings(rt,previous))
        if capacity_authorization is not None:
            data['capacity_authorization']=copy.deepcopy(capacity_authorization)
        existing=rt.db.execute("SELECT data FROM production_events WHERE run=? AND kind='review_findings_inherited'",(run,)).fetchone()
        if existing:
            if json.loads(existing[0])!=data:raise ValueError('Continuation findings already bound differently')
            return
        peers=rt.db.execute("SELECT data FROM production_events WHERE run<>? AND kind='review_findings_inherited'",(run,)).fetchall()
        if any(json.loads(r[0])['previous']==previous for r in peers):raise ValueError('Predecessor already has a continuation')
        rt.event(run,None,None,'review_findings_inherited',data)


def bind(rt,plan,frozen):
    # Never accept a model-authored follow-up envelope.
    frozen.pop('review_followup',None);frozen.pop('correction_context',None)
    if not enabled(plan) or frozen.get('execution') or frozen.get('job_owner'):return
    final=final_review(rt,plan,frozen)
    issues=repair_issues(rt,plan,frozen) if scoped(plan) and not final else applicable(rt,plan,frozen)
    if not issues:return
    frozen['correction_context']=[dict(id=v['id'],issue=v['issue']) for v in issues]
    frozen['instruction']+='\n'+(REPAIR_INSTRUCTIONS if scoped(plan) and not frozen.get('review_of') else INSTRUCTIONS)
    if not final and not (scoped(plan) and frozen.get('review_of')):return
    if len(frozen['criteria'])>=30:raise ValueError('No criterion capacity for carried review findings')
    frozen['criteria'].append(CRITERION)
    candidates=[i['path'] for i in frozen['inputs'] if i.get('from_task')==frozen['review_of']]
    if not candidates:raise ValueError('Carried review requires exact candidate inputs')
    sources={}
    for issue in issues:
        aid=issue['review_attempt']
        if aid not in sources:
            previous=json.loads(rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(aid,)).fetchone()[0])
            sources[aid]=[dict(artifact=i['artifact'],sha256=i['sha256']) for i in previous['inputs']]
    frozen['review_followup']=dict(version=1,criterion=len(frozen['criteria']),sources=sources,
        findings={f'f{n}':v for n,v in enumerate(issues,1)},candidates=candidates)


def schema(frozen):
    from task_relay.planning_contract import obj
    text=dict(type='string',minLength=1,maxLength=1600)
    location=obj(dict(path=dict(type='string',enum=[i['path'] for i in frozen['inputs']]),location=text),('path','location'))
    detail=obj(dict(verdict=dict(type='string',enum=['resolved','unresolved']),reason=text,
        inspected=dict(type='array',items=location,minItems=1,maxItems=12)),('verdict','reason','inspected'))
    return obj({k:copy.deepcopy(detail) for k in frozen['review_followup']['findings']},frozen['review_followup']['findings'])


def judgments(report,frozen):
    policy=frozen.get('review_followup')
    if not policy:return {}
    check=next((v for v in report['checks'] if v['criterion']==policy['criterion']),None)
    if check is None:
        if report['decision']=='blocked':return {}
        raise ValueError('Missing carried review finding judgments')
    from task_relay.planning_contract import validate
    try:value=json.loads(check['evidence']);validate(value,schema(frozen))
    except (ValueError,TypeError):raise ValueError('Every carried review finding needs a structured resolution') from None
    unresolved=any(v['verdict']!='resolved' for v in value.values())
    if unresolved and (check['passed'] or report['decision']=='accept'):
        raise ValueError('Unresolved review findings cannot pass or become advisory acceptance')
    return value


def validate_report(report,frozen):
    values=judgments(report,frozen)
    if not values:return
    from .runtime import safe_file
    policy=frozen['review_followup'];inputs={i['path']:i for i in frozen['inputs']}
    for key,detail in values.items():
        paths={v['path'] for v in detail['inspected']}
        if not paths.intersection(policy['candidates']):raise ValueError('Finding resolution must inspect the current candidate')
        for path in paths:
            if hashlib.sha256(safe_file(frozen['workspace'],path).read_bytes()).hexdigest()!=inputs[path]['sha256']:
                raise ValueError('Finding resolution evidence changed from its frozen version')
        if detail['verdict']=='resolved':
            old={i['sha256'] for i in policy['sources'][policy['findings'][key]['review_attempt']]}
            if all(inputs[p]['sha256'] in old for p in paths):
                raise ValueError('Unchanged candidate and evidence cannot establish a repair')


def covers(rt,run,report,frozen):
    """Delivery must not reuse a review predating a newly recorded defect."""
    plan=json.loads(rt.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    if not enabled(plan):return True
    issues=applicable(rt,plan,frozen)
    if not issues:return True
    values=judgments(report,frozen);bound=frozen.get('review_followup',{}).get('findings',{})
    resolved={bound[k]['id'] for k,v in values.items() if v['verdict']=='resolved'}
    return {v['id'] for v in issues}<=resolved


def resolved_ids(report,frozen):
    bound=frozen.get('review_followup',{}).get('findings',{})
    return {bound[k]['id'] for k,v in judgments(report,frozen).items() if v['verdict']=='resolved'}
