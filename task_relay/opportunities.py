"""Local history discovery. Evidence suggests opportunities; it never grants work."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from orchestrator.storage import transaction
from . import pipelines, procedures
from .usage_tracker import normalize

VERSION = 1
WORKFLOW_LIMIT = 200
REQUEST_LIMIT = 1000
INSTRUCTIONS = '''Relay can discover automation opportunities from recorded history.
For an explicit analysis request use {kind:"discover_opportunities"}; analysis is
local and queues no production or provider work. /opportunities performs the same
analysis; /opportunities list and /opportunities ID inspect saved evidence.
snapshot.automation_opportunities contains the latest suggestions, and
snapshot.automation_opportunity contains the one the user inspected, when present.
Structural similarity does not establish semantic equivalence or user acceptance.
Report counts and unknown usage honestly; do not invent savings, training,
preferences, or successful repairs. Only for an explicit request to save a candidate
use draft_procedure with opportunity_id plus the exact completed pipeline_id, name,
and literal parameters. The candidate pins that source's receipt fingerprint.
Shared sequences identify component opportunities; the current promotion drafts
the COMPLETE exemplar workflow so prerequisites and original scope are preserved.
Never silently slice stages or claim a standalone component was extracted. Failure
families are diagnostic suggestions, never authority to retry or install a repair.
'''


def initialize(db):
    for sql in '''CREATE TABLE IF NOT EXISTS relay_opportunity_scans(
        id TEXT PRIMARY KEY, channel TEXT NOT NULL, request_id TEXT NOT NULL,
        request TEXT NOT NULL, report TEXT NOT NULL, created REAL NOT NULL,
        UNIQUE(channel,request_id));
      CREATE TABLE IF NOT EXISTS relay_opportunity_candidates(
        id TEXT PRIMARY KEY, channel TEXT NOT NULL, definition TEXT NOT NULL,
        sha256 TEXT NOT NULL);
    '''.split(';'):
        if sql.strip():db.execute(sql)


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def shape(stage):
    # Tool contracts outlive generated stage/file-role names. Keep untyped free
    # conversation roles distinct, and never merge different operation/gate sets.
    caps=sorted(stage['capabilities'])
    typed=bool(caps) or stage['route'] in ('image','browser_research') or stage['gate']=='choice'
    label=' + '.join(caps) if caps else stage['route']+(' choice' if stage['gate']=='choice' else '')
    return dict(id=label if typed else stage['id'], route=stage['route'], gate=stage['gate'],
                capabilities=caps, outputs=len(stage['deliverables']) if typed else sorted(stage['deliverables']))


def token_usage(db, pid, stage_ids, channel, available, rows=None):
    if not {'production_plans', 'production_plan_calls', 'relay_pipeline_requests'} <= available:
        return dict(calls=0, measured_calls=0, tokens=None, by_model=[])
    if rows is None:rows=db.execute('''SELECT c.*, p.provider, p.model, r.step FROM production_plan_calls c
        JOIN production_plans p ON p.id=c.plan_id
        JOIN relay_pipeline_requests r ON r.request_id=p.request_id
        WHERE r.pipeline=? AND p.channel=? ORDER BY c.plan_id,c.number''', (pid,channel))
    groups={}; count=0; measured=0; total=0
    for row in rows:
        if row['step'] not in stage_ids:continue
        count+=1
        try:usage=json.loads(row['usage'] or '{}')
        except ValueError:usage={}
        value=normalize(row['provider'],usage)['total_tokens']
        key=(row['provider'],row['model'])
        group=groups.setdefault(key,dict(provider=key[0],model=key[1],calls=0,measured_calls=0,tokens=None))
        group['calls']+=1
        if value is not None:
            measured+=1;total+=value;group['measured_calls']+=1;group['tokens']=(group['tokens'] or 0)+value
    return dict(calls=count,measured_calls=measured,tokens=total if measured else None,by_model=list(groups.values()))


def observation(state, row, steps, events, chosen, source_hash, available):
    ids=[s['id'] for s in chosen]
    whole=len(chosen)==len(steps)
    relevant=[e for e in events if e['step'] in ids or (whole and e['step'] is None)]
    starts=[e['created'] for e in relevant if e['kind']=='queued']
    ends=[e['created'] for e in relevant if e['kind'] in ('completed','result')]
    finished=all(s['status']=='completed' for s in chosen)
    repairs=[]
    if 'production_auto_repairs' in available:
        repairs=[r for r in row['_repairs'] if r['step'] in ids]
    return dict(pipeline_id=row['id'], title=row['title'], request_preview=row['request'][:500],
                request_sha256=procedures.digest(row['request']),
                receipt_sha256=procedures.digest(dict(spec=row['spec'],steps=chosen,events=relevant,repairs=repairs)),
                workflow_status=row['status'], stages=ids, stage_statuses={s['id']:s['status'] for s in chosen},
                completed=finished, source_sha256=source_hash,
                user_choices=sum(e['kind']=='user_choice' for e in relevant),
                selected_artifact_versions=len({a['artifact'] for s in chosen for a in json.loads(s['sources'])}),
                clarifications=sum(e['kind']=='clarification' for e in relevant),
                failure_events=sum(e['kind'] in ('blocked','repair_blocked') for e in relevant),
                repair_receipts=repairs,
                elapsed_seconds=max(0,max(ends)-min(starts)) if finished and starts and ends else None,
                planning=token_usage(state.db,row['id'],ids,procedures.channel(state),available,row['_planning']))


def candidate(channel, kind, signature, evidence):
    # One workflow/request contributes at most once to a candidate, even after retries.
    evidence=sorted(evidence,key=lambda e:str(e.get('pipeline_id',e.get('request_id'))))
    completed=sum(e.get('completed',False) for e in evidence) if any('completed' in e for e in evidence) else None
    calls=sum(e.get('planning',{}).get('calls',0) for e in evidence)
    measured=sum(e.get('planning',{}).get('measured_calls',0) for e in evidence)
    tokens=sum(e.get('planning',{}).get('tokens') or 0 for e in evidence)
    sources=[dict(pipeline_id=e['pipeline_id'],sha256=e['source_sha256']) for e in evidence if e.get('source_sha256')]
    stages=' → '.join(s['id'] for s in signature) if isinstance(signature,list) else ''
    title={'workflow':'Repeated workflow: '+stages,'sequence':'Shared stage sequence: '+stages,
           'failure':'Repeated failure: '+str(signature),'request':'Repeated request'}[kind]
    summary=dict(occurrences=len(evidence),completed=completed,
                 user_choices=sum(e.get('user_choices',0) for e in evidence),
                 selected_artifact_versions=sum(e.get('selected_artifact_versions',0) for e in evidence),
                 clarifications=sum(e.get('clarifications',0) for e in evidence),
                 failure_events=sum(e.get('failure_events',0) for e in evidence),
                 repair_receipts=sum(len(e.get('repair_receipts',[])) for e in evidence),
                 planning_calls=calls,measured_planning_calls=measured,planning_tokens=tokens if measured else None)
    value=dict(version=VERSION,channel=channel,kind=kind,title=title,signature=signature,
               summary=summary,evidence=evidence,draft_sources=sources,
               proposal={'workflow':'Review a completed example as a reusable workflow with explicit project variables.',
                         'sequence':'Review prerequisites and file handoffs for a reusable component. The complete exemplar can be drafted now.',
                         'failure':'Compare failure and repair receipts to propose a preflight check or tested repair rule. No repair is approved by this analysis.',
                         'request':'Check whether these are retries or repeatable tasks. Capture a successful workflow before promoting an automation.'}[kind],
               confidence='Structural match; review meaning and quality.' if kind in ('workflow','sequence') else
                          'Repeated observations; retries and common symptoms may have different causes.',
               savings='Unmeasured. Recorded planning tokens are historical usage, not a savings estimate.',
               promotion='Complete exemplar workflow only; review variables and all stages.' if sources else
                         'Evidence only. No completed exemplar is available for procedure promotion.')
    sha=procedures.digest(value)
    return dict(id='opp-'+sha[:24],sha256=sha,**value)


def analyze(state, *, now=None):
    """Read one bounded, consistent snapshot. No file reads, model calls or writes."""
    db=state.db; available=tables(db); channel=procedures.channel(state)
    coverage=dict(workflow_limit=WORKFLOW_LIMIT,request_limit=REQUEST_LIMIT,
                  workflows_total=0,workflows_analyzed=0,workflows_skipped=0,requests_total=0,requests_analyzed=0,
                  planning_usage_scope='Directly linked stage planning calls only; worker/browser/chat usage is not aggregated.')
    if not {'relay_pipelines','relay_pipeline_steps','relay_pipeline_events'}<=available:
        return dict(version=VERSION,channel=channel,as_of=now or time.time(),coverage=coverage,candidates=[],
                    limitation='No saved pipeline history is available in this database.')
    workflows={}; sequences=defaultdict(dict); wholes=defaultdict(list); failures=defaultdict(list)
    with transaction(db,write=False):
        coverage['workflows_total']=db.execute('SELECT count(*) FROM relay_pipelines WHERE channel=?',(channel,)).fetchone()[0]
        rows=db.execute('SELECT * FROM relay_pipelines WHERE channel=? ORDER BY created DESC,id DESC LIMIT ?', (channel,WORKFLOW_LIMIT)).fetchall()
        for row in rows:
            try:
                row=dict(row)
                if len(row['spec'])>100000:raise ValueError('Oversized specification')
                spec=json.loads(row['spec']); shapes=[shape(s) for s in spec['stages']]
                pipelines.validate(spec,{'capabilities':{'graph_operations':[{'id':c} for s in shapes for c in s['capabilities']]}})
                if not 2<=len(shapes)<=12:raise ValueError('Unsupported stage count')
                steps=[dict(s) for s in db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(row['id'],))]
                if [s['id'] for s in steps]!=[s['id'] for s in spec['stages']]:raise ValueError('Stage mismatch')
                events=[dict(e) for e in db.execute('SELECT * FROM relay_pipeline_events WHERE pipeline=? ORDER BY id',(row['id'],))]
                for e in events:
                    if e['kind'] in ('blocked','repair_blocked') and not isinstance(json.loads(e['detail']),dict):
                        raise ValueError('Invalid failure receipt')
                for s in steps:
                    values=json.loads(s['sources'])
                    if not isinstance(values,list) or any(not isinstance(a,dict) or not isinstance(a.get('artifact'),str) for a in values):
                        raise ValueError('Invalid artifact references')
                row['_repairs']=[dict(r) for r in db.execute('SELECT step,parent,preparation,status,plan_id,error FROM production_auto_repairs WHERE pipeline=?',(row['id'],))] if 'production_auto_repairs' in available else []
                row['_planning']=list(db.execute('''SELECT c.*,p.provider,p.model,r.step FROM production_plan_calls c
                    JOIN production_plans p ON p.id=c.plan_id JOIN relay_pipeline_requests r ON r.request_id=p.request_id
                    WHERE r.pipeline=? AND p.channel=? ORDER BY c.plan_id,c.number''',(row['id'],channel))) if {'production_plans','production_plan_calls','relay_pipeline_requests'}<=available else []
                source_hash=None
                if row['status']=='completed' and all(s['status']=='completed' for s in steps):
                    source_hash=procedures.digest(procedures.source(state,row['id']))
                full_key=pipelines.encoded(shapes)
                obs=observation(state,row,steps,events,steps,source_hash,available)
                workflows[row['id']]=(full_key,obs)
                wholes[full_key].append(obs)
                for width in range(2,min(6,len(steps)-1)+1):
                    for start in range(len(steps)-width+1):
                        key=pipelines.encoded(shapes[start:start+width])
                        if row['id'] not in sequences[key]:
                            sequences[key][row['id']]=observation(state,row,steps,events,steps[start:start+width],source_hash,available)
                # Keep a recovered failure in the history even if the current error cleared.
                for step in steps:
                    errors=[e for e in events if e['step']==step['id'] and e['kind'] in ('blocked','repair_blocked')]
                    if not errors and step['status']=='blocked':errors=[dict(detail=pipelines.encoded({'error':step['error']}))]
                    for event in errors:
                        detail=json.loads(event['detail']); message=detail.get('error') or detail.get('reason') or 'Recorded stage failure'
                        key='stage '+step['id']+': '+' '.join(str(message).split())[:300]
                        evidence=dict(pipeline_id=row['id'],title=row['title'],stage=step['id'],
                                      error=str(message)[:800],workflow_status=row['status'],
                                      request_sha256=procedures.digest(row['request']),
                                      receipt_sha256=procedures.digest(errors),
                                      completed=row['status']=='completed',failure_events=len(errors),
                                      repair_receipts=[r for r in obs['repair_receipts'] if r['step']==step['id']])
                        if not any(e['pipeline_id']==row['id'] for e in failures[key]):failures[key].append(evidence)
                coverage['workflows_analyzed']+=1
            except (ValueError,TypeError,KeyError,IndexError):
                coverage['workflows_skipped']+=1
        candidates=[]
        for key,evidence in wholes.items():
            if len(evidence)>=2:candidates.append(candidate(channel,'workflow',json.loads(key),evidence))
        # Shared components need evidence across different complete workflow structures.
        repeated={k:v for k,v in sequences.items() if len(v)>=2 and len({workflows[p][0] for p in v})>=2}
        memberships=defaultdict(list)
        for key,evidence in repeated.items():memberships[tuple(sorted(evidence))].append(json.loads(key))
        for key,evidence in repeated.items():
            shapes=json.loads(key)
            # Keep maximal sequences for identical supporting workflows, reducing duplicate suggestions.
            contained=False
            for longer_shapes in memberships[tuple(sorted(evidence))]:
                if len(longer_shapes)>len(shapes) and any(longer_shapes[i:i+len(shapes)]==shapes for i in range(len(longer_shapes)-len(shapes)+1)):
                    contained=True;break
            if not contained:candidates.append(candidate(channel,'sequence',shapes,list(evidence.values())))
        for key,evidence in failures.items():
            if len(evidence)>=2:candidates.append(candidate(channel,'failure',key,evidence))
        required={'orchestrator_chats','relay_request_channels','relay_pipeline_requests','orchestrator_chat_errors'}
        if required<=available:
            where="COALESCE(ch.channel,'telegram')=? AND NOT EXISTS (SELECT 1 FROM relay_pipeline_requests s WHERE s.request_id=c.id)"
            if 'capability_dispatches' in available:
                where+=" AND NOT EXISTS (SELECT 1 FROM capability_dispatches d WHERE d.job_id=c.id AND d.executor='relay_opportunities')"
            coverage['requests_total']=db.execute('SELECT count(*) FROM orchestrator_chats c LEFT JOIN relay_request_channels ch ON ch.request_id=c.id WHERE '+where,(channel,)).fetchone()[0]
            requests=db.execute('''SELECT c.*,e.phase,e.error_type,e.message FROM orchestrator_chats c
                LEFT JOIN relay_request_channels ch ON ch.request_id=c.id
                LEFT JOIN orchestrator_chat_errors e ON e.job_id=c.id WHERE '''+where+
                ' ORDER BY c.created DESC,c.id DESC LIMIT ?', (channel,REQUEST_LIMIT)).fetchall()
            exact=defaultdict(list); errors=defaultdict(list)
            for r in requests:
                coverage['requests_analyzed']+=1
                ev=dict(request_id=r['id'],request_preview=r['prompt'][:500],status=r['status'],provider=r['provider'],model=r['model'],
                        request_sha256=procedures.digest(r['prompt']),receipt_sha256=procedures.digest(dict(r)),
                        failure_events=int(bool(r['error_type'])))
                key=' '.join(r['prompt'].split())  # Preserve case and numbers; never merge different project facts.
                exact[key].append(ev)
                if r['error_type']:
                    key=r['provider']+' / '+r['phase']+' / '+r['error_type']
                    errors[key].append(dict(**ev,error=(r['message'] or '')[:800]))
            for key,evidence in exact.items():
                if len(evidence)>=2:candidates.append(candidate(channel,'request',key,evidence))
            for key,evidence in errors.items():
                if len(evidence)>=2:candidates.append(candidate(channel,'failure',key,evidence))
    # A transparent priority heuristic, not an estimated probability or dollar return.
    candidates.sort(key=lambda c:(-len(c['draft_sources']),-c['summary']['occurrences'],c['kind'],c['id']))
    coverage['candidates_found']=len(candidates);coverage['candidates_returned']=min(50,len(candidates))
    return dict(version=VERSION,channel=channel,as_of=now or time.time(),coverage=coverage,candidates=candidates[:50],
                limitation='Structural and exact-request matches only. Completion is not acceptance. Elapsed spans include waiting; savings and preference learning are unmeasured.')


def scan(state, request_id, original):
    procedures.atomic(state)
    old=state.db.execute('SELECT * FROM relay_opportunity_scans WHERE channel=? AND request_id=?',
                         (procedures.channel(state),str(request_id))).fetchone()
    if old:
        if old['request']!=original:raise ValueError('Analysis request identity changed.')
        return saved_report(old)
    report=analyze(state)
    report['id']='scan-'+procedures.digest(dict(channel=procedures.channel(state),request_id=str(request_id),report=report))[:24]
    for c in report['candidates']:
        state.db.execute('INSERT OR IGNORE INTO relay_opportunity_candidates VALUES (?,?,?,?)',
                         (c['id'],procedures.channel(state),pipelines.encoded(c),c['sha256']))
    state.db.execute('INSERT INTO relay_opportunity_scans VALUES (?,?,?,?,?,?)',
                     (report['id'],procedures.channel(state),str(request_id),original,pipelines.encoded(report),report['as_of']))
    return report


def load(state, ident):
    row=state.db.execute('SELECT * FROM relay_opportunity_candidates WHERE id=? AND channel=?',
                         (ident,procedures.channel(state))).fetchone()
    if not row:raise ValueError('Opportunity is not available in this channel. Use /opportunities.')
    value=json.loads(row['definition']); body={k:v for k,v in value.items() if k not in ('id','sha256')}
    sha=procedures.digest(body)
    if sha!=row['sha256'] or value['sha256']!=sha or value['id']!=ident or ident!='opp-'+sha[:24]:
        raise ValueError('Opportunity evidence changed. Run a new analysis.')
    return value


def exemplar(state, ident, pid):
    c=load(state,ident)
    selected=next((s for s in c['draft_sources'] if s['pipeline_id']==pid),None)
    if not selected:raise ValueError('Select one of this opportunity’s completed exemplar workflows.')
    if procedures.digest(procedures.source(state,pid))!=selected['sha256']:
        raise ValueError('Exemplar receipts changed since analysis. Run /opportunities again.')
    return dict(id=ident,sha256=c['sha256'],kind=c['kind'],exemplar=selected,scope='complete_exemplar_workflow')


def saved_report(row):
    report=json.loads(row['report'])
    body={k:v for k,v in report.items() if k!='id'}
    ident='scan-'+procedures.digest(dict(channel=row['channel'],request_id=row['request_id'],report=body))[:24]
    if row['id']!=ident or report['id']!=ident:raise ValueError('Saved analysis changed. Use /opportunities to create a fresh snapshot.')
    return report


def latest(state):
    row=state.db.execute('SELECT * FROM relay_opportunity_scans WHERE channel=? ORDER BY created DESC,rowid DESC LIMIT 1',
                         (procedures.channel(state),)).fetchone()
    return saved_report(row) if row else None


def catalog(state):
    try:report=latest(state)
    except ValueError as exc:return [dict(error=str(exc))]
    return [dict(id=c['id'],title=c['title'],summary=c['summary'],draft_sources=c['draft_sources']) for c in report['candidates'][:8]] if report else []


def focused(state):
    ident=state.get('opportunity_focus')
    if not ident:return None
    try:
        value=load(state,ident)
        result=dict(id=ident,title=value['title'],summary=value['summary'],promotion=value['promotion'])
        if value['draft_sources']:
            pid=value['draft_sources'][0]['pipeline_id']
            exemplar(state,ident,pid)
            source=procedures.source(state,pid)
            result['exemplar']=source if len(pipelines.encoded(source))<=24000 else dict(pipeline_id=pid,note='Inspect the full source and supply literal variables.')
        return result
    except ValueError as exc:return dict(id=ident,error=str(exc))


def listing(report, page=1):
    if not report:return 'No analysis saved yet. Use /opportunities to analyze local history.'
    items=report['candidates'];pages=max(1,math.ceil(len(items)/8))
    if not 1<=page<=pages:raise ValueError('Choose a list page between 1 and '+str(pages)+'.')
    cov=report['coverage']
    lines=['Automation opportunities · page '+str(page)+'/'+str(pages),
           f"Analyzed {cov['workflows_analyzed']}/{cov['workflows_total']} workflows and {cov['requests_analyzed']}/{cov['requests_total']} human requests in this channel.",
           f"Skipped invalid workflows: {cov['workflows_skipped']}. Up to 50 candidates retained."]
    for c in items[(page-1)*8:page*8]:
        s=c['summary'];lines+=['',c['id'],c['title'],
             f"{s['occurrences']} observations; completed outcomes: {s['completed'] if s['completed'] is not None else 'unknown'}; {len(c['draft_sources'])} completed exemplars.",
             f"{s['clarifications']} clarifications; {s['failure_events']} failure events; {s['repair_receipts']} repair receipts."]
    if not items:lines+=['No repeated patterns met the evidence threshold of two distinct workflows or requests.']
    return '\n'.join(lines)+'\n\nInspect: /opportunities ID. More: /opportunities list PAGE.\n'+report['limitation']+'\nLocal analysis only; no work started.'


def describe(state, ident, page=1):
    c=load(state,ident);evidence=c['evidence'];pages=max(1,math.ceil(len(evidence)/8))
    if not 1<=page<=pages:raise ValueError('Choose an evidence page between 1 and '+str(pages)+'.')
    s=c['summary']; tokens=str(s['planning_tokens']) if s['planning_tokens'] is not None else 'unknown'
    lines=[c['title'],ident,c['proposal'],c['confidence'],
           f"Observations: {s['occurrences']}; recorded completed outcomes: {s['completed'] if s['completed'] is not None else 'unknown'} (not an acceptance count).",
           f"Recorded user choices: {s['user_choices']}; selected artifact versions: {s['selected_artifact_versions']}.",
           f"Linked planning calls: {s['planning_calls']}; known tokens: {tokens} ({s['measured_planning_calls']} measured calls).",
           c['savings'],f'Evidence page {page}/{pages}:']
    for e in evidence[(page-1)*8:page*8]:
        lines+=['',str(e.get('pipeline_id',e.get('request_id')))+' · '+str(e.get('workflow_status',e.get('status'))),
                'Request preview: '+e.get('request_preview',e.get('title',''))]
        if e.get('error'):lines+=['Failure: '+e['error']]
        if 'stages' in e:lines+=['Stages: '+', '.join(e['stages'])]
        if e.get('elapsed_seconds') is not None:lines+=['Recorded elapsed span (includes waiting): '+str(round(e['elapsed_seconds']))+' seconds.']
        if e.get('planning',{}).get('by_model'):lines+=['Planning models: '+pipelines.encoded(e['planning']['by_model'])]
        if e.get('repair_receipts'):lines+=['Repair receipts (not proof a fix succeeded): '+pipelines.encoded(e['repair_receipts'])]
    lines+=['',c['promotion']]
    if c['draft_sources']:
        lines+=['Completed exemplars: '+', '.join(s['pipeline_id'] for s in c['draft_sources']),
                'Ask Relay to draft this opportunity from an exemplar with project variables. Review and approve the resulting procedure separately.',
                'Direct draft: /opportunities draft '+ident+' WORKFLOW_ID {"name":"Procedure name","parameters":[{"name":"variable","example":"exact original text"}]}']
    return '\n'.join(lines)+'\nInspection starts no work.'


def command(state, argument, request_id, original):
    parts=argument.split(None,3)
    if not parts:return listing(scan(state,request_id,original))
    if parts[0]=='list' and len(parts)<=2:return listing(latest(state),int(parts[1]) if len(parts)==2 else 1)
    if parts[0]=='draft' and len(parts)==4:
        options=json.loads(parts[3])
        if not isinstance(options,dict) or set(options)!={'name','parameters'}:raise ValueError('Supply a procedure name and literal parameters.')
        action=dict(kind='draft_procedure',opportunity_id=parts[1],pipeline_id=parts[2],**options)
        result=procedures.dispatch(state,dict(id=request_id,prompt=original),action,{})
        return result[0]
    if len(parts)<=2:
        result=describe(state,parts[0],int(parts[1]) if len(parts)==2 else 1)
        state.put('opportunity_focus',parts[0])
        return result
    raise ValueError('Use /opportunities, /opportunities list PAGE, or /opportunities ID PAGE.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--channel',choices=('telegram','messages'),default='telegram')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    # Do not construct State: opening history for analysis must not migrate a live database.
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        report=analyze(SimpleNamespace(db=db,channel=args.channel))
    print(json.dumps(report,ensure_ascii=False,indent=2) if args.json else listing(report))


if __name__=='__main__':main()
