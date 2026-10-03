"""Bounded research campaigns on the existing pipeline queue and review receipts.

Slots are compiled up front. Consuming a slot never resets an attempt or changes
the saved workflow. All state transitions share the pipeline transaction; workers
perform external dispatch later through the existing queue.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs

from orchestrator.operation_contracts import encoded, fields, text, batch_parameters


def schema():
    from .planning_contract import obj, array
    string={'type':'string'};integer={'type':'integer'}
    return obj({'version':{'type':'integer','enum':[1]},'entity_type':string,
        'target_count':integer,'batch_size':integer,'max_batches':integer,
        'required_fields':array(string),'criteria':array(obj({'id':string,'question':string},('id','question'))),
        'discovery_instruction':string,'assessment_instruction':string},
        ('version','entity_type','target_count','batch_size','max_batches','required_fields','criteria',
         'discovery_instruction','assessment_instruction'))


INSTRUCTIONS='''For research that must discover a target number of qualified entities,
use plan_pipeline with research_campaign and stage_details for FINAL delivery only.
research_campaign is {version:1,entity_type,target_count,batch_size,max_batches,
required_fields:[field IDs],criteria:[{id,question}],discovery_instruction,
assessment_instruction}. Preserve the exact requested target and criteria. Every
criterion is required: all met qualifies, any unmet rejects, otherwise hold.
Do not turn preferences or existing automation/team support into exclusions unless
the user requires that. Unknowns stay explicit. Choose queries/strategy in the two
instructions. Relay constructs discovery and assessment slots and their contracts;
do not manually list batches or reference generated batch IDs in final stage uses.
At most 12 batches, each with batch_size*(1+field count+criterion count)<=30 claims.
batch_size*max_batches must cover target_count; yield is not guaranteed. Each slot
has one Safari producer (one attempt, <=300s,24 tools/requests,8192 response tokens)
and one independent reviewer (one attempt,<=600s,16 tools/requests,8192 response
tokens). Existing 20-action/10-exact-URL Safari limits apply. These are explicit
ceilings, not permission for retries or provider switching. Each batch first
discovers identities; its assessment planner binds exact profile/source URLs from
that reviewed ledger. Discovery must freeze navigable source URLs: X searches
need an exact /search?q=... URL with a nonempty, URL-encoded query. The Safari
worker cannot type or click; x.com, /home, /explore and an empty /search cannot
execute a search. Choose the queries during planning, not during the worker run.
Assess only that batch's new identities. Do not replace
profile/enrichment work with search snippets. Relay retains duplicates, holds,
rejections and reasons, skips unused slots at target, and supplies a campaign
ledger plus exact source artifacts to final delivery. Exhaustion is an honest
shortfall. Include all requested final formats, evidence, notes and drafts as
1–4 final stages. Outreach is draft only unless separately authorized.'''


def parameters(policy,phase):
    return dict(entity_type=policy['entity_type'],max_records=policy['batch_size'],
        required_fields=policy['required_fields'] if phase=='assess' else ['discovery_reason'],
        criteria=policy['criteria'] if phase=='assess' else [])


def validate_policy(policy):
    fields(policy,schema()['required'])
    if type(policy['version']) is not int or policy['version']!=1:raise ValueError('Unknown campaign version')
    for key,maximum in (('target_count',100),('batch_size',10),('max_batches',12)):
        if type(policy[key]) is not int or not 1<=policy[key]<=maximum:raise ValueError('Invalid campaign '+key)
    if policy['batch_size']*policy['max_batches']<policy['target_count']:
        raise ValueError('Campaign capacity cannot reach the requested target; keep the target and replan')
    if 3*policy['batch_size']+2>24:
        raise ValueError('Campaign batch cannot inspect every identity within the 24-request ceiling')
    if not policy['criteria']:raise ValueError('Campaign needs explicit qualification criteria')
    batch_parameters(parameters(policy,'assess'))
    for key in ('discovery_instruction','assessment_instruction'):text(policy[key],1800)


def slots(policy):
    validate_policy(policy);result=[]
    for number in range(1,policy['max_batches']+1):
        for phase in ('discover','assess'):
            ident=f'campaign_{number:02d}_{phase}'
            prior=f'campaign_{number:02d}_discover'
            outputs={'candidates':{'media_type':'application/json','content_contract':{'id':'research.batch','version':1}},
                     'summary':{'media_type':'text/markdown'}}
            for key in outputs:outputs[key]['companions']=[k for k in outputs if k!=key]
            inputs=[] if phase=='discover' else [dict(stage=prior,deliverable=k,consumer='context',
                media_type=v['media_type'],**({'content_contract':v['content_contract']} if 'content_contract' in v else {})) for k,v in outputs.items()]
            result.append(dict(id=ident,route='production',gate='none',capabilities=[],
                instruction=policy['discovery_instruction' if phase=='discover' else 'assessment_instruction'],
                deliverables={'candidates':'Typed, source-bound research batch records','summary':'Labeled research coverage and findings'},
                handoff=dict(inputs=inputs,outputs=outputs),campaign_batch=dict(number=number,phase=phase)))
    return result


def validate_workflow(action):
    policy=action.get('research_campaign')
    if policy is None:
        if any('campaign_batch' in s for s in action['stages']):raise ValueError('Campaign slots require an explicit budget grant')
        return
    expected=slots(policy);stages=action['stages']
    if stages[:len(expected)]!=expected or not 1<=len(stages)-len(expected)<=4:
        raise ValueError('Campaign slots must match the compiled bounded grant exactly')
    if any('campaign_batch' in s for s in stages[len(expected):]):raise ValueError('Foreign campaign slot')
    ids={s['id'] for s in expected}
    if any(e['stage'] in ids for s in stages[len(expected):] for e in s.get('handoff',{}).get('inputs',[])):
        raise ValueError('Final delivery uses the campaign ledger and completed sources, not optional slot edges')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS research_campaign_receipts(
        pipeline TEXT NOT NULL, stage TEXT NOT NULL, run TEXT NOT NULL,
        binding TEXT NOT NULL, records TEXT NOT NULL, PRIMARY KEY(pipeline,stage))''')


def canonical(url):
    """Only known X profile aliases are merged. Other site queries stay meaningful."""
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Invalid candidate HTTPS identity')
    if p.hostname.lower() in ('x.com','www.x.com','twitter.com','www.twitter.com'):
        match=re.fullmatch(r'/([A-Za-z0-9_]{1,15})/?',p.path)
        if not match or match[1].lower() in ('home','search','explore','i','intent','settings','messages','notifications'):
            raise ValueError('X candidate identity must be a profile, not a post or search URL')
        return 'https://x.com/'+match[1].lower()
    return urlunsplit((p.scheme,p.netloc.lower(),p.path or '/',p.query,''))


def ledger(state,pid):
    p=state.db.execute('SELECT spec FROM relay_pipelines WHERE id=?',(pid,)).fetchone()
    policy=json.loads(p[0]).get('research_campaign') if p else None
    if not policy:return None
    entries={};receipts=[]
    for r in state.db.execute('''SELECT r.* FROM research_campaign_receipts r JOIN relay_pipeline_steps s
        ON s.pipeline=r.pipeline AND s.id=r.stage WHERE r.pipeline=? ORDER BY s.position''',(pid,)):
        binding=json.loads(r['binding']);receipts.append(dict(stage=r['stage'],run=r['run'],binding=binding))
        phase=binding['phase']
        for record in json.loads(r['records']):
            key=canonical(record['url']);entry=entries.setdefault(key,dict(url=key,name=record['name'],status='discovered',versions=[]))
            entry['versions'].append(dict(stage=r['stage'],record=record,binding=binding))
            if phase=='discover':continue
            decisions={a['verdict'] for a in record['assessment']}
            status='rejected' if 'unmet' in decisions else 'held' if 'unknown' in decisions else 'qualified'
            if entry['status']!='discovered' and entry['status']!=status:
                entry.update(status='held',reason='Conflicting reviewed assessments require explicit resolution')
            elif 'reason' not in entry:entry['status']=status
    counts={k:sum(e['status']==k for e in entries.values()) for k in ('discovered','qualified','held','rejected')}
    used=state.db.execute("SELECT count(*) FROM relay_pipeline_steps WHERE pipeline=? AND id LIKE 'campaign_%_discover' AND status NOT IN ('pending','skipped')",(pid,)).fetchone()[0]
    pending=state.db.execute("SELECT count(*) FROM relay_pipeline_steps WHERE pipeline=? AND id LIKE 'campaign_%' AND status NOT IN ('completed','skipped')",(pid,)).fetchone()[0]
    outcome='target_reached' if counts['qualified']>=policy['target_count'] else 'shortfall' if not pending else 'researching'
    return dict(version=1,policy=policy,counts=counts,target=policy['target_count'],
        remaining=max(0,policy['target_count']-counts['qualified']),batches_started=used,
        batches_remaining=policy['max_batches']-used,outcome=outcome,entities=list(entries.values()),receipts=receipts,
        user_accepted=False)


def context(state,p,s):
    progress=ledger(state,p['id'])
    if progress is None:return None
    stage=json.loads(p['spec'])['stages'][s['position']];slot=stage.get('campaign_batch')
    if slot:
        policy=progress['policy'];progress['batch_parameters']=parameters(policy,slot['phase'])
        progress['batch_parameters']['max_records']=min(policy['batch_size'],progress['remaining']) or policy['batch_size']
        # Final slot can return fewer records. There is no obligation to pad.
        progress['needed']=progress['remaining']
        if slot['phase']=='assess':
            discovery=f"campaign_{slot['number']:02d}_discover"
            prior=state.db.execute('SELECT records FROM research_campaign_receipts WHERE pipeline=? AND stage=?',(p['id'],discovery)).fetchone()
            if not prior:raise ValueError('Assessment needs its reviewed discovery receipt')
            assessed={e['url'] for e in progress['entities'] if e['status']!='discovered'}
            progress['assessment_urls']=list(dict.fromkeys(r['url'] for r in json.loads(prior[0]) if canonical(r['url']) not in assessed))
    return progress


def skip_unused(state,p,s):
    """Called only while the pipeline is active, before queueing a pending slot."""
    stage=json.loads(p['spec'])['stages'][s['position']]
    if not stage.get('campaign_batch'):return False
    value=ledger(state,p['id'])
    reason='Target reached' if value['remaining']==0 else None
    if not reason and stage['campaign_batch']['phase']=='assess' and not context(state,p,s)['assessment_urls']:
        reason='No new identities in reviewed discovery'
    if not reason:return False
    from .pipelines import event
    state.db.execute("UPDATE relay_pipeline_steps SET status='skipped',result=? WHERE pipeline=? AND id=?",(reason,p['id'],s['id']))
    event(state,p['id'],s['id'],'campaign_slot_skipped',{'reason':reason,'user_accepted':False})
    return True


def validate_discovery_urls(computer):
    """Reject known non-executable discovery grants before a native launch."""
    spec=computer.get('spec',computer)
    for url in dict.fromkeys([spec.get('url',''),*spec.get('allowed_urls',[])]):
        parsed=urlsplit(url)
        if parsed.hostname not in ('x.com','www.x.com','twitter.com','www.twitter.com'):continue
        path=parsed.path.rstrip('/')
        query=parse_qs(parsed.query).get('q',[])
        if path in ('','/home','/explore') or (path=='/search' and (len(query)!=1 or not query[0].strip())):
            raise ValueError('Campaign discovery cannot use an X landing page or empty search: '+url+
                '. Safari can navigate, read and scroll only; freeze exact /search?q=... URLs or specific source pages. The planner must choose queries before dispatch.')


def bind_plan(plan,stage,progress):
    if not stage or not stage.get('campaign_batch'):return
    if not progress:raise ValueError('Missing frozen campaign context')
    producers=[t for t in plan['tasks'] if not t.get('review_of')]
    reviews=[t for t in plan['tasks'] if t.get('review_of')]
    if len(producers)!=1 or len(reviews)!=1 or not producers[0].get('computer') or reviews[0]['review_of']!=producers[0]['id']:
        raise ValueError('A campaign slot needs exactly one Safari producer and its independent reviewer')
    producer=producers[0];review=reviews[0]
    if stage['campaign_batch']['phase']=='discover':validate_discovery_urls(producer['computer'])
    if review.get('computer') or review.get('execution') or producer.get('execution') or review.get('browser'):
        raise ValueError('Campaign review uses saved evidence only')
    from orchestrator.executors import request_limit,response_limit
    for task,seconds,requests in ((producer,300,24),(review,600,16)):
        if task['max_attempts']!=1 or task['limits']['seconds']>seconds or task['limits']['tool_calls']>requests or request_limit(task)>requests or response_limit(task)>8192:
            raise ValueError('Campaign slot exceeds its frozen per-worker budget; no attempts reset')
    producer['research']={'mode':'campaign','parameters':progress['batch_parameters']}
    producer['instruction']+='\nFrozen campaign parameters: '+encoded(progress['batch_parameters'])
    if stage['campaign_batch']['phase']=='assess':
        allowed=producer['computer'].get('spec',producer['computer']).get('allowed_urls',[])
        if not set(progress['assessment_urls'])<=set(allowed):
            raise ValueError('Assessment must grant exact discovered profile URLs before dispatch')
        producer['instruction']+='\nAssess exactly these discovered identities: '+encoded(progress['assessment_urls'])


def consume(state,p,s,run,rt,bindings):
    """Count only an exact committed producer version with an accepted raw audit."""
    stage=json.loads(p['spec'])['stages'][s['position']]
    if not stage.get('campaign_batch'):return []
    prior_receipt=state.db.execute('SELECT * FROM research_campaign_receipts WHERE pipeline=? AND stage=?',(p['id'],s['id'])).fetchone()
    if prior_receipt:
        binding=json.loads(prior_receipt['binding'])
        if prior_receipt['run']!=run or binding['candidates']!=bindings.get('candidates') or binding['summary']!=bindings.get('summary'):
            raise ValueError('Conflicting campaign completion receipt')
        return [binding['raw_source']]
    if set(bindings)!={'candidates','summary'}:raise ValueError('Missing campaign output bindings')
    source=bindings['candidates'];summary=bindings['summary']
    artifact=state.db.execute('SELECT * FROM production_artifacts WHERE id=?',(source['artifact'],)).fetchone()
    if not artifact or artifact['run']!=run:raise ValueError('Foreign campaign artifact')
    attempt=state.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
    if not attempt or attempt['state']!='completed' or rt.task(run,artifact['task'])['latest']!=artifact['attempt']:
        raise ValueError('Stale campaign producer version')
    frozen=json.loads(attempt['frozen'])
    from orchestrator.operation_records import Store,audit_context
    from orchestrator.operation_contracts import validate_document,batch_record
    def artifact_read(task,path):
        a=rt.output(run,task,path)
        if not a:raise ValueError('Missing campaign source artifact')
        raw=Path(a['blob']).read_bytes()
        if len(raw)!=a['bytes'] or hashlib.sha256(raw).hexdigest()!=a['sha256']:raise ValueError('Campaign artifact changed')
        return raw
    read=lambda path:artifact_read(artifact['task'],path)
    Store(frozen,state.db).verify_export(read)
    raw=read(artifact['path']);document=json.loads(raw)
    validate_document(raw,{'id':'research.batch','version':1})
    progress=context(state,p,s)
    if document['parameters']!=progress['batch_parameters']:raise ValueError('Campaign parameters changed')
    accepted=state.db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND attempt=? AND kind='model_review_accepted' ORDER BY id DESC LIMIT 1",(run,artifact['task'],artifact['attempt'])).fetchone()
    if not accepted:raise ValueError('Campaign requires independent accepted evidence review')
    review_id=json.loads(accepted[0])['review_attempt']
    review=state.db.execute('SELECT * FROM production_attempts WHERE id=?',(review_id,)).fetchone()
    rf=json.loads(review['frozen'])
    if review['state']!='completed' or rt.task(run,review['task'])['latest']!=review_id or rf.get('review_target')!=artifact['attempt'] or rf.get('review_of')!=artifact['task']:
        raise ValueError('Stale campaign review')
    review_read=lambda path:artifact_read(review['task'],path)
    Store(rf,state.db).verify_export(review_read)
    audit=json.loads(review_read(rf['research_audit']['path']))
    if audit['evidence_sha256']!=source['sha256'] or audit['summary_sha256']!=summary['sha256'] or any(c['verdict']!='supported' for c in audit['claims']):
        raise ValueError('Campaign audit does not accept the exact source versions')
    # Recheck the immutable raw pack, all input hashes and literal references.
    def input_read(path):
        from orchestrator.runtime import safe_file
        return safe_file(Path(rf['workspace']),path).read_bytes()
    raw_context=audit_context(rf,input_read)
    from .pipelines import artifact_source
    raw_input=next((i for i in rf['inputs'] if i['path']==rf['computer_review']['path']),None)
    if not raw_input or not raw_input.get('artifact'):raise ValueError('Missing registered campaign raw evidence')
    raw_source=artifact_source(state,raw_input['artifact'])
    if raw_source['sha256']!=audit['raw_sha256']:raise ValueError('Campaign raw evidence version changed')
    pack=json.loads(input_read(rf['computer_review']['path']))
    visited=set()
    for observation in pack['observations']:
        try:visited.add(canonical(observation.get('url','')))
        except ValueError:pass
    keys=[]
    for record in document['records']:
        batch_record(record,document['parameters'],raw_context);keys.append(canonical(record['url']))
    if len(set(keys))!=len(keys):raise ValueError('Duplicate canonical identities within batch')
    if stage['campaign_batch']['phase']=='assess' and set(keys)!={canonical(u) for u in progress['assessment_urls']}:
        raise ValueError('Assess exactly the new discovered identities; record inaccessible entities as unknown')
    if stage['campaign_batch']['phase']=='assess':
        for record,key in zip(document['records'],keys):
            if all(a['verdict']=='met' for a in record['assessment']) and key not in visited:
                raise ValueError('Qualification requires a captured profile visit; search snippets alone cannot qualify an entity')
    binding=dict(phase=stage['campaign_batch']['phase'],producer_attempt=artifact['attempt'],review_attempt=review_id,
        candidates=source,summary=summary,raw_source=raw_source,audit_sha256=hashlib.sha256(review_read(rf['research_audit']['path'])).hexdigest(),raw_sha256=audit['raw_sha256'])
    values=(p['id'],s['id'],run,encoded(binding),encoded(document['records']))
    old=state.db.execute('SELECT * FROM research_campaign_receipts WHERE pipeline=? AND stage=?',(p['id'],s['id'])).fetchone()
    if old:
        if tuple(old)!=values:raise ValueError('Conflicting campaign completion receipt')
        return [raw_source]
    state.db.execute('INSERT INTO research_campaign_receipts VALUES (?,?,?,?,?)',values)
    from .pipelines import event
    event(state,p['id'],s['id'],'campaign_batch_reviewed',binding)
    if stage['campaign_batch']['phase']=='assess':
        from .pipelines import notice
        progress=ledger(state,p['id']);counts=progress['counts']
        notice(state,p['id'],s['id'],'campaign_progress',
            'Research batch '+str(stage['campaign_batch']['number'])+' reviewed: '+str(counts['qualified'])+'/'+str(progress['target'])+
            ' qualified, '+str(counts['held'])+' held, '+str(counts['rejected'])+' rejected. '+
            ('Target reached; unused research slots will be skipped.' if not progress['remaining'] else 'Continue only within the remaining saved batch budget.'))
    return [raw_source]
