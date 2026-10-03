"""Lineage-scoped design proposals. Evidence is retained; interpretation is not approval."""
import copy
import json
from pathlib import Path
import re

from orchestrator import contracts as c

ROUTING = '''
For conceptual CAD/design work set design_intent:true on plan_production. Use it
for form exploration and design revisions, not inspection/export or mechanical
repairs. It maintains a cited design brief through this work's exact lineage.
When the form is unresolved, propose a small representative geometric prototype
before the full design: one instance with plan, section and perspective evidence,
then development after visual selection. Use a pipeline for these dependent
outcomes, with design_intent:true on its production stages, a selection gate on
the prototype, and explicit native-model AND preview handoffs to development.
Retain the full requested outcome as the later stage; do not silently reduce it.
Respect an explicit request to skip a prototype or use an established design.
Do not add repeated concept approval to ordinary refinements. Existing exact-code
execution boundaries still apply. Do not run modeling for a status question.
'''

INSTRUCTIONS = '''
design_intent_policy=1: ready responses must include design_intent with phase
(prototype, revision, development), representation (concrete construction logic,
not stylistic adjectives), advance_quote (empty except an explicit current user
instruction to bypass the prototype), and additions (up to 20 atomic entries).
Each addition has local_id (n1, n2...), statement, kind (requirement, rejection,
proposal, question), basis (user or interpretation), quote, supersedes (prior
entry IDs, or []), and test (how actual plan/section/geometry would demonstrate it).
User-basis quotes must occur verbatim in design_intent_request. Other assertions
are interpretations; use quote="" and kind proposal/question. Reference readings,
agent dimensions, one-mesh topology and agent success claims are not user decisions.
Never infer approval from continue, silence, an assistant report or a selected
script. Do not copy requirements from another study or infer a personal style.
Only a cited user correction can supersede prior entries. All other entries carry
forward automatically. Preserve unaffected requirements when changing one feature.
Use questions for unresolved conflicts; do not invent numeric tolerances from
subjective feedback. Explain what changed in the representation. Reading an image
is delegated to workers; the text planner must not pretend it inspected pixels.
Start unresolved form with phase prototype: smallest representative geometry,
actual plan/section/perspective evidence before replication/detail. Preparation
may only author that prototype's script; it is NOT a visual checkpoint. Development
requires design_intent_checkpoint (selected model plus preview from one prototype)
or advance_quote explicitly directing bypass. Revision preserves the established
scope and generative logic. No new execution authority or automatic acceptance.
Declare appropriate visual outputs and user selection for a geometric prototype.
Technical validity, source fidelity and visual intent are separate review claims.
'''


def _text(value, name, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Design intent requires bounded ' + name + '.')
    return value


def direct_text(text):
    """Obvious quoted examples are not authored instructions; semantics need review."""
    lines=[];fence=None
    for line in text.splitlines():
        marker=re.match(r'^\s*(`{3,}|~{3,})',line)
        if marker:
            token=marker[1]
            if fence is None:fence=token
            elif token[0]==fence[0] and len(token)>=len(fence):fence=None
            continue
        if fence is None and not line.lstrip().startswith('>'):lines.append(line)
    return '\n'.join(lines)


def saved(row, state=None, run=None):
    if not row:return None
    plan=json.loads(row['plan']) if row['plan'] else {}
    value=plan.get('origin',{}).get('design_intent')
    if state is not None and (run or row['run']):
        candidates=[]
        for a in state.db.execute('SELECT a.spec FROM production_tasks t JOIN production_assignments a ON a.id=t.assignment WHERE t.run=?',(run or row['run'],)):
            item=json.loads(a['spec']).get('design_intent_state')
            if item:candidates.append(item)
        if candidates:
            heads={v['sha256']:v for v in candidates if not any(v['sha256'] in other['ancestors'] for other in candidates)}
            if len(heads)!=1:raise ValueError('Current design assignments disagree about their lineage.')
            value=next(iter(heads.values()))
    if value is None:value=json.loads(row['context']).get('design_intent_previous')
    if value and value['sha256']!=c.digest({k:v for k,v in value.items() if k!='sha256'}):
        raise ValueError('Saved design intent changed.')
    return copy.deepcopy(value)


def attach(state, payload, parent, stage, pipeline, request):
    """Freeze only selected lineage, never a mutable project-wide head."""
    from .production_stages import planning_origin
    previous=saved(parent,state)
    if stage and not previous:previous=saved(planning_origin(state,stage['run']),state,stage['run'])
    if pipeline and not previous:
        candidates={}
        for source in pipeline.get('inputs',{}).get('sources',[]):
            artifact=state.db.execute('SELECT run FROM production_artifacts WHERE id=?',(source['artifact'],)).fetchone()
            if not artifact:continue
            value=saved(planning_origin(state,artifact['run']),state,artifact['run'])
            if value:candidates[value['sha256']]=value
        heads=[v for key,v in candidates.items() if not any(key in other['ancestors'] for other in candidates.values())]
        if len(heads)>1:raise ValueError('Multiple design branches selected; choose one design lineage before planning.')
        if heads:previous=heads[0]
    enabled=payload['options'].get('design_intent') or previous or (pipeline or {}).get('stage',{}).get('design_intent')
    if not enabled:return
    payload['options']['design_intent']=True
    payload['design_intent_policy']=1
    payload['design_intent_request']=(pipeline or {}).get('original_request',request)
    payload['design_intent_previous']=previous
    payload['design_intent_checkpoint']=[]
    # Only recorded human selection of both actual model and preview qualifies.
    selected={s['artifact'] for s in payload['sources']}
    groups={}
    for aid in selected:
        for d in state.db.execute('SELECT d.*,a.path,a.attempt FROM production_decisions d JOIN production_artifacts a ON a.id=d.artifact WHERE d.artifact=?',(aid,)):
            groups.setdefault((d['run'],d['task'],d['attempt']),[]).append(dict(d))
    for (run,task,attempt),decisions in groups.items():
        frozen=state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(attempt,)).fetchone()
        value=json.loads(frozen['frozen']).get('design_intent_state') if frozen else None
        if not value or not value.get('prototype_pending') or not previous:continue
        if value['sha256'] not in [previous['sha256'],*previous['ancestors']]:continue
        suffixes={Path(d['path']).suffix.lower() for d in decisions}
        if suffixes & {'.3dm','.blend','.skp'} and suffixes & {'.png','.jpg','.jpeg'}:
            payload['design_intent_checkpoint'].append(dict(run=run,task=task,decisions=decisions))
    payload['planner_instructions']+='\n'+INSTRUCTIONS


def compile_proposal(result, payload, request_id):
    if not payload.get('design_intent_policy'):
        if 'design_intent' in result:raise ValueError('Design intent was not enabled in this frozen scope.')
        return None
    value=result.get('design_intent')
    if not isinstance(value,dict) or set(value)!={'phase','representation','advance_quote','additions'}:
        raise ValueError('Design intent requires phase, representation, advance_quote and additions.')
    if value['phase'] not in ('prototype','revision','development'):raise ValueError('Unknown design intent phase.')
    representation=_text(value['representation'],'representation',3000)
    previous=payload.get('design_intent_previous')
    request=payload['design_intent_request'];authored=direct_text(request)
    feedback='\n'.join(e['quote'] for e in (previous or {}).get('entries',[]) if e.get('feedback_source'))
    advance=value['advance_quote']
    if not isinstance(advance,str) or (advance and (len(advance)>2000 or advance not in authored)):
        raise ValueError('Prototype bypass requires an exact current user quotation.')
    if value['phase']=='development' and not payload.get('design_intent_checkpoint') and not advance:
        raise ValueError('Development needs a selected geometric prototype and preview, or explicit user bypass.')
    if value['phase']=='revision' and not previous:
        raise ValueError('Design revision needs an established design lineage; start with a prototype.')
    additions=value['additions']
    if not isinstance(additions,list) or len(additions)>20:raise ValueError('Use at most 20 design intent additions.')
    entries=copy.deepcopy(previous['entries']) if previous else []
    inactive=set(previous['superseded']) if previous else set()
    known={e['id']:e for e in entries};local=set()
    for item in additions:
        if not isinstance(item,dict) or set(item)!={'local_id','statement','kind','basis','quote','supersedes','test'}:
            raise ValueError('Malformed design intent addition.')
        lid=item['local_id']
        if not isinstance(lid,str) or not re.fullmatch('n[1-9][0-9]*',lid) or lid in local:raise ValueError('Distinct local design IDs required.')
        local.add(lid)
        for field in ('statement','test'):_text(item[field],field)
        if item['kind'] not in ('requirement','rejection','proposal','question') or item['basis'] not in ('user','interpretation'):
            raise ValueError('Unknown design evidence kind or basis.')
        quote=item['quote']
        if item['basis']=='user':
            if not isinstance(quote,str) or not quote.strip() or len(quote)>2000 or (quote not in authored and quote not in direct_text(feedback)):
                raise ValueError('User design requirements need an exact authored quotation.')
        elif quote!='' or item['kind'] not in ('proposal','question'):
            raise ValueError('Agent interpretations remain proposals/questions, not user requirements.')
        targets=item['supersedes']
        if (not isinstance(targets,list) or any(not isinstance(t,str) or t not in known or t in inactive for t in targets)
                or len(set(targets))!=len(targets) or (targets and item['basis']!='user')):
            raise ValueError('Only a cited user change can supersede active prior design entries.')
        ident=str(request_id)+':'+lid
        if ident in known:raise ValueError('Design entry identity already exists.')
        entries.append(dict(id=ident,**{k:copy.deepcopy(v) for k,v in item.items() if k!='local_id'},
                            request_id=request_id,request_sha256=c.digest(request)))
        inactive.update(targets)
    if not entries or len(entries)>100:raise ValueError('Design intent needs 1–100 retained entries; no silent truncation.')
    record=dict(version=1,phase=value['phase'],representation=representation,entries=entries,
                superseded=sorted(inactive),advance_quote=advance,
                prototype_pending=value['phase']=='prototype' or (value['phase']=='revision' and bool(previous and previous.get('prototype_pending')) and not payload.get('design_intent_checkpoint')),
                checkpoint=copy.deepcopy(payload.get('design_intent_checkpoint',[])),
                ancestors=[*previous['ancestors'],previous['sha256']] if previous else [])
    if len(c.encoded(record))>45000:raise ValueError('Design intent exceeds its bounded context; nothing was dropped.')
    record['sha256']=c.digest(record)
    return record


def bind(tasks, record):
    if not record:return
    from orchestrator.design_review import CRITERION
    active=[e for e in record['entries'] if e['id'] not in record['superseded']]
    instructions=('\n<relay-design-intent>\nDESIGN INTENT (model interpretation, exact user evidence retained; no inferred approval):\n'+c.encoded(record)+
        '\nPreserve every active requirement. Proposals/questions are not accepted decisions. '
        'Before detailed authoring, explain the geometric construction and any conflicts. '
        'For prototype work demonstrate one representative instance before replication; '
        'show actual plan, section and perspective when native execution is in scope. '
        'Preparation checks code only and cannot certify unseen geometry. '
        'Compare real candidate evidence with references; validity/counts alone do not establish design fidelity. '
        'Latest explicit user feedback controls conflicting earlier intent; identify those conflicts and their exact quotations. '
        'Unreconciled feedback is retained verbatim, not an inferred design decision.\n</relay-design-intent>')
    for task in tasks:
        task['design_intent_state']=copy.deepcopy(record)
        if not task.get('execution'):
            task['instruction']=re.sub(r'\n<relay-design-intent>.*?</relay-design-intent>', '', task['instruction'], flags=re.S)
            task['instruction']+=instructions
    for reviewer in tasks:
        if not reviewer.get('review_of'):continue
        producer=next(t for t in tasks if t['id']==reviewer['review_of'])
        phase='output' if producer.get('execution') else 'preparation'
        reviewer['criteria']=[s for s in reviewer['criteria'] if s!=CRITERION]+[CRITERION]
        reviewer['design_review']=dict(version=1,sha256=record['sha256'],phase=phase,
            entries=copy.deepcopy(active),criterion=len(reviewer['criteria']))
        reviewer['instruction']=re.sub(r'\n<relay-design-review>.*?</relay-design-review>', '', reviewer['instruction'], flags=re.S)
        reviewer['instruction']+=('\n<relay-design-review>\nFor the design-intent criterion supply JSON encoded in its evidence string: '
            '{"intent_sha256":"'+record['sha256']+'","phase":"'+phase+'","observations":'
            '[{"id":"each active entry ID","status":"supported|concern|unverified","evidence":"actual evidence and its limits"}]}. '
            'Cover every active entry exactly once, including unaccepted proposals/questions. '
            'Preparation evidence cites the candidate construction/code; it is not visual approval. '
            'Output evidence cites inspected model/plan/section/preview, not producer assurances. '
            'Use concern for mismatch and unverified for unavailable evidence; these require human review, not silent acceptance.\n</relay-design-review>')


def feedback_record(record, text, source):
    """Retain a correction immediately; semantic atomization happens at next planning."""
    if not record:return None
    _text(text,'user correction',12000)
    value=copy.deepcopy(record)
    ident='feedback:'+c.digest([source,text])[:24]
    if any(e['id']==ident for e in value['entries']):return value
    value['ancestors'].append(value.pop('sha256'))
    value['entries'].append(dict(id=ident,statement=text,quote=text,kind='question',basis='user',
        supersedes=[],feedback_source=source,test='Reconcile this exact latest correction with earlier intent; cite the changed geometry and any remaining conflict.'))
    if len(value['entries'])>100 or len(c.encoded(value))>45000:raise ValueError('Design feedback exceeds the retained context bound.')
    value['sha256']=c.digest(value)
    return value


def summary(record):
    active=[e for e in record['entries'] if e['id'] not in record['superseded']]
    return ('Design: '+record['phase']+' · '+str(len(active))+' retained intent entries.\n'+
            record['representation']+'\n'+
            '\n'.join(e['kind']+': '+e['statement'] for e in active[:6])+
            ('\nFurther entries remain in the full assignment.' if len(active)>6 else '')+
            ('\nPrototype bypass quotation: '+record['advance_quote'] if record['advance_quote'] else ''))
