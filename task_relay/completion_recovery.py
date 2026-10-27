"""Opt-in bounded research recovery through the existing committed work queue.

No provider is called here. A successor must pass the original workflow checks,
then complete independent review and the original delivery/selection gate.
"""
import hashlib
import json
from pathlib import Path

from orchestrator.operation_contracts import encoded

POLICY = dict(version=1, cycles=2, tasks_per_cycle=4, seconds=600, tool_calls=24)
LEGACY_DELIVERY_POLICY = dict(version=2, cycles=4, cycle_scope='stage', tasks_per_cycle=4, seconds=600, tool_calls=24)
DELIVERY_POLICY = dict(version=3, cycles=4, cycle_scope='stage', tasks_per_cycle=8, seconds=600, tool_calls=24)


def planner_context(detail):
    """Reference the full durable baseline without duplicating it in prompts."""
    baseline = detail['baseline']
    plan = baseline['plan']
    keys = ('id', 'role', 'objective', 'criteria', 'limits', 'max_attempts',
            'worker', 'backend', 'browser', 'execution', 'outputs', 'review_of')
    return {k: detail[k] for k in ('parent', 'cycle', 'policy', 'authorization')} | dict(
        baseline_sha256=hashlib.sha256(encoded(baseline).encode()).hexdigest(),
        gaps=baseline['gaps'],
        completed_read_operations=completed_read_operations(baseline),
        original_plan=dict(backend=plan.get('backend'),
                           deliverables=plan.get('deliverables', {}),
                           deferred_operations=plan.get('deferred_operations'),
                           tasks=[{k: t[k] for k in keys if k in t}
                                  for t in plan['tasks']]),
        evidence_policy='Full originals, attempts and recovery baseline remain in durable receipts. Supplied artifact versions are unchanged; drafts are not accepted.')


def completed_read_operations(baseline):
    """Expose finished baseline read identities, never their semantic acceptance."""
    identities={a['id']:a for a in baseline['attempts']}
    specs={t['id']:t for t in baseline['plan']['tasks'] if 'id' in t}
    from orchestrator.execution import REGISTRY
    reusable={cap:spec['saved_evidence'] for cap,spec in REGISTRY.items() if spec.get('saved_evidence')}
    return [dict(task=t['id'],attempt=t['latest'],capability=reusable[specs[t['id']]['execution']['capability']]['capability'],
                 actual_capability=specs[t['id']]['execution']['capability'])
            for t in baseline['tasks']
            if t['status'] in ('completed','awaiting_review') and identities.get(t.get('latest'),{}).get('state')=='completed'
            and specs.get(t['id'],{}).get('execution',{}).get('capability') in reusable]


def validate_operation_reuse(plan, payload, reuse):
    """Bind executed read coverage to exact baseline bytes and reviewed consumers."""
    if not isinstance(reuse,dict):
        raise ValueError('Reused operations must name exact saved artifact versions.')
    if not reuse:return
    completed=payload.get('completion_recovery',{}).get('completed_read_operations',[])
    original_caps={t['id']:t.get('execution',{}).get('capability')
                   for t in payload.get('completion_recovery',{}).get('original_plan',{}).get('tasks',[]) if t.get('id')}
    selected=set(payload.get('options',{}).get('step_capabilities',[]))
    prepared_selected='web.sources.prepared' in selected
    actual={t.get('execution',{}).get('capability') for t in plan['tasks']}
    if 'web.sources.prepared' in selected:selected.add('web.sources')
    if 'web.sources.prepared' in actual:actual.add('web.sources')
    sources={s['artifact']:(s['sha256'],s['bytes']) for s in payload.get('sources',[])}
    records=payload.get('recorded_external_sources',[])
    from orchestrator.execution import REGISTRY
    reusable={spec['saved_evidence']['capability'] for spec in REGISTRY.values() if spec.get('saved_evidence')}
    for capability,ids in reuse.items():
        if (capability not in reusable or capability not in selected or capability in actual
                or not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids)
                or len(set(ids))!=len(ids)):
            raise ValueError('Only absent selected completed source reads can be reused in recovery.')
        eligible={r['artifact'] for r in records
                  if sources.get(r['artifact'])==(r['sha256'],r['bytes'])
                  and (r.get('capability','web.sources')==capability)
                  and any(c['attempt']==r['attempt'] and c['capability']==capability
                          and (not prepared_selected or c.get('actual_capability',original_caps.get(c.get('task')))=='web.sources.prepared') for c in completed)}
        if not set(ids)<=eligible:
            raise ValueError('Reused source lacks an exact completed baseline receipt.')
        for ident in ids:
            producers=[t for t in plan['tasks'] if not t.get('review_of')
                       and any(i.get('artifact')==ident for i in t['inputs'])]
            if not any(any(r.get('review_of')==t['id']
                           and any(i.get('artifact')==ident for i in r['inputs'])
                           for r in plan['tasks']) for t in producers):
                raise ValueError('Reused source must reach its producer and independent reviewer.')


def browser_subset(candidate, original):
    """Narrow image subjects under the same exact browser authority."""
    import copy
    a,b=copy.deepcopy(candidate),copy.deepcopy(original)
    images=a.pop('image_sources',[]);old=b.pop('image_sources',[])
    if a!=b:return False
    for group in images:
        prior=next((g for g in old if g['path']==group['path']),None)
        if not prior or not group['subjects'] or any(s not in prior['subjects'] for s in group['subjects']):return False
    return True


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS local_review_invocations (
        pipeline TEXT NOT NULL, step TEXT NOT NULL, parent TEXT NOT NULL,
        cycle INTEGER NOT NULL, previous_attempt TEXT PRIMARY KEY, baseline TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS completion_recovery_extensions (
        pipeline TEXT NOT NULL,step TEXT NOT NULL,request_sha256 TEXT NOT NULL,
        request TEXT NOT NULL,baseline_sha256 TEXT NOT NULL,cycles INTEGER NOT NULL,
        PRIMARY KEY(pipeline,step,request_sha256))''')
    db.execute("""CREATE TABLE IF NOT EXISTS standalone_correction_grants (run TEXT PRIMARY KEY,request TEXT NOT NULL,baseline_hash TEXT NOT NULL,head TEXT NOT NULL,cycle INTEGER NOT NULL,channel TEXT NOT NULL,epoch INTEGER NOT NULL,error TEXT)""")
    db.execute('''CREATE TABLE IF NOT EXISTS completion_recovery_grants (
        pipeline TEXT PRIMARY KEY, request TEXT NOT NULL, policy TEXT NOT NULL)''')
    schema='''CREATE TABLE IF NOT EXISTS completion_recoveries (
        pipeline TEXT NOT NULL, step TEXT NOT NULL, parent TEXT NOT NULL,
        cycle INTEGER NOT NULL, request_id INTEGER UNIQUE NOT NULL,
        baseline TEXT NOT NULL, PRIMARY KEY(pipeline,step,cycle), UNIQUE(parent,baseline))'''
    prior=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='completion_recoveries'").fetchone()
    import re
    if prior and re.search(r'parent\s+TEXT\s+NOT\s+NULL\s+UNIQUE',prior[0],re.I):
        db.execute('SAVEPOINT recovery_identity_migration')
        try:
            db.execute('ALTER TABLE completion_recoveries RENAME TO completion_recoveries_prior_identity')
            db.execute(schema)
            db.execute('INSERT INTO completion_recoveries(rowid,pipeline,step,parent,cycle,request_id,baseline) SELECT rowid,pipeline,step,parent,cycle,request_id,baseline FROM completion_recoveries_prior_identity')
            db.execute('DROP TABLE completion_recoveries_prior_identity')
            db.execute('RELEASE recovery_identity_migration')
        except Exception:
            db.execute('ROLLBACK TO recovery_identity_migration');db.execute('RELEASE recovery_identity_migration');raise
    else:db.execute(schema)


def authorize(state, pipeline, request, *, additional_cycles=4):
    """Caller must supply explicit human authorization, never model suggestions."""
    if not state.db.in_transaction:
        raise ValueError('Recovery authorization requires an atomic transaction.')
    if not isinstance(request, str) or not request.strip():
        raise ValueError('Exact human recovery request is required.')
    p = state.db.execute('SELECT * FROM relay_pipelines WHERE id=?', (pipeline,)).fetchone()
    if not p or p['channel'] != getattr(state, 'channel', 'telegram'):
        raise ValueError('Recovery belongs to its original channel.')
    policy = DELIVERY_POLICY if json.loads(p['spec']).get('completion') else POLICY
    old = state.db.execute('SELECT * FROM completion_recovery_grants WHERE pipeline=?', (pipeline,)).fetchone()
    if old:
        if json.loads(old['policy']) not in ((LEGACY_DELIVERY_POLICY,DELIVERY_POLICY) if json.loads(p['spec']).get('completion') else (POLICY,)):
            raise ValueError('The saved recovery grant cannot be replaced.')
        if old['request']!=request:
            # A new human request is a separate bounded grant, never a rewrite
            # of the original authorization or spent recovery ledger.
            step=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status='blocked' ORDER BY position LIMIT 1",(pipeline,)).fetchone()
            if p['status']!='blocked' or not step:raise ValueError('Additional recovery requires an exact stopped stage')
            run=step['target'] if step['target_kind']=='production_run' else None
            if step['target_kind']=='plan_production':
                plan=state.db.execute('SELECT run FROM production_plans WHERE id=?',(step['target'],)).fetchone()
                run=plan['run'] if plan else None
            baseline=snapshot(state,run,photo_recovery=True) if run else None
            if not baseline:raise ValueError('Additional recovery requires confirmed stopped work; uncertain effects remain held')
            digest=hashlib.sha256(request.encode()).hexdigest()
            existing=state.db.execute('SELECT 1 FROM completion_recovery_extensions WHERE pipeline=? AND step=? AND request_sha256=?',(pipeline,step['id'],digest)).fetchone()
            if not existing:
                state.db.execute('INSERT INTO completion_recovery_extensions VALUES(?,?,?,?,?,?)',
                    (pipeline,step['id'],digest,request,hashlib.sha256(encoded(baseline).encode()).hexdigest(),additional_cycles))
                from .pipelines import event
                event(state,pipeline,step['id'],'additional_recovery_authorized',dict(request=request,request_sha256=digest,
                    cycles=additional_cycles,baseline_sha256=hashlib.sha256(encoded(baseline).encode()).hexdigest(),original_grant_preserved=True,acceptance=False))
        return
    state.db.execute('INSERT INTO completion_recovery_grants VALUES (?,?,?)',
                     (pipeline, request, encoded(policy)))


def bind_deliveries(plan,payload,options,coverage):
    """Resolve exact output ports and retain reviewed intermediate versions."""
    if coverage or payload.get('planner_budget_binding_version')!=2:return coverage
    requested=options.get('deliverables',{});resolved={};carried={}
    recovery=payload.get('completion_recovery',{});original=recovery.get('original_plan',{})
    sources={s['artifact']:s for s in payload.get('sources',[])}
    records={r['artifact']:r for r in payload.get('recorded_external_sources',[])}
    reused={a for ids in plan.get('reused_operations',{}).values() for a in ids}
    completed={r['attempt']:r['task'] for r in recovery.get('completed_read_operations',[])}
    for ident,description in requested.items():
        outputs=[{'task':t['id'],'output':o['path']} for t in plan['tasks'] if not t.get('review_of')
                 for o in t['outputs'] if o['purpose']==description]
        if len(outputs)==1:
            resolved[ident]=outputs[0];continue
        if outputs:return coverage
        prior=original.get('deliverables',{}).get(ident,{})
        candidates=[a for a in reused if a in sources and a in records
                    and completed.get(records[a].get('attempt'))==prior.get('task')
                    and prior.get('description')==description]
        if len(candidates)!=1:return coverage
        aid=candidates[0];source=sources[aid];record=records[aid]
        carried[ident]=dict(artifact=aid,origin_artifact=record['origin_artifact'],sha256=source['sha256'],bytes=source['bytes'],
                           path=prior['output'],parent=recovery['parent'],task=prior['task'],
                           attempt=record['attempt'])
        resolved[ident]={'artifact':aid}
    if carried:plan['carried_deliverables']=carried
    return resolved


def validate_carried_deliveries(state,plan,baseline):
    """Recheck exact prior current outputs and independent review at Start/delivery."""
    from . import production_control as pc
    from orchestrator.runtime import Runtime, safe_file
    from orchestrator.runtime import file_hash
    from pathlib import Path
    rt=Runtime(pc.root(state),connection=state.db)
    for ident,proof in plan.get('carried_deliverables',{}).items():
        prior=baseline['plan'].get('deliverables',{}).get(ident,{})
        if proof['parent']!=baseline['run'] or proof['task']!=prior.get('task') or proof['path']!=prior.get('output'):
            raise ValueError('Carry-forward changed its original delivery port')
        task=rt.task(proof['parent'],proof['task']);review=rt.reviewer(proof['parent'],proof['task'])
        if task['status']!='completed' or task['latest']!=proof['attempt'] or not review or review['status']!='completed':
            raise ValueError('Carry-forward needs a current independently reviewed output')
        output=rt.output(proof['parent'],proof['task'],proof['path'])
        if not output or any(output[k]!=proof[k] for k in ('sha256','bytes')) or output['id']!=proof['origin_artifact']:
            raise ValueError('Carry-forward artifact version changed')
        alias=rt.artifact(proof['artifact'])
        if any(alias[k]!=proof[k] for k in ('sha256','bytes')):raise ValueError('Carry-forward alias bytes changed')
        for artifact in (output,alias):
            blob=Path(artifact['blob'])
            if blob.is_symlink() or not blob.is_file() or blob.stat().st_size!=proof['bytes'] or file_hash(blob)!=proof['sha256']:
                raise ValueError('Carry-forward stored bytes changed')
        if proof.get('handoff'):
            from orchestrator.handoff_contracts import check_file
            check_file(Path(alias['blob']),proof['handoff'])


def schema_repair_gap(rt, attempt, receipt):
    """A changed local adapter may recover a definitively rejected request.

    An HTTP error alone is insufficient: retain the exact rejected wire schema,
    require no executed tools or pending outcome, and prove the new adapter
    changes the fragment transport. Ordinary model failures stay held.
    """
    from pathlib import Path
    from orchestrator import gemini_worker
    frozen=json.loads(attempt['frozen'])
    if (frozen.get('backend',{}).get('type')!='gemini-agent'
            or not (frozen.get('operation_contract') or frozen.get('job_owner')) or receipt.get('status')!='finished'
            or receipt.get('external_outcome')!='no_pending_response'
            or receipt.get('pending_requests')!=[] or receipt.get('tool_calls')!=0
            or receipt.get('api_requests')!=1):return None
    current=hashlib.sha256(Path(gemini_worker.__file__).read_bytes()).hexdigest()
    previous=frozen.get('runtime_sources',{}).get('gemini_worker.py')
    if not previous or previous==current:return None
    control=rt.root/'workers'/attempt['id']
    try:
        requests=list(control.glob('api-*.request.json'))
        if len(requests)!=1 or list(control.glob('api-*.response.json')):return None
        path=requests[0];outcome_path=path.with_name(path.name.removesuffix('.request.json')+'.outcome.json')
        outcome=json.loads(outcome_path.read_text())
        request=json.loads(path.read_text())
        if outcome.get('outcome')!='rejected' or outcome.get('http_status')!=400:return None
        if request.get('provider')!='gemini' or request.get('model')!=frozen['backend']['model']:return None
        old={t['name']:t for group in request['payload']['tools'] for t in group['functionDeclarations']}
        from orchestrator import job_owner
        tools=job_owner.definitions(frozen['owner_grant']) if frozen.get('job_owner') else gemini_worker.definitions(frozen)
        new={t['name']:t for t in gemini_worker.gemini_declarations(tools)}
        changed=[name for name,field in (('operation_submit','records'),('operation_amend','record'))
                 if name in old and field in old[name].get('parametersJsonSchema',{}).get('properties',{})
                 and field+'_json' in new.get(name,{}).get('parameters',{}).get('properties',{})]
        from orchestrator.gemini_tool_schema import declaration
        changed+= [name for name,value in old.items() if name not in changed
                   and value.get('parametersJsonSchema') and name in new
                   and declaration(value).get('parameters')==new[name].get('parameters')
                   and value.get('parametersJsonSchema')!=new[name].get('parameters')]
        mode=request['payload'].get('toolConfig',{}).get('functionCallingConfig',{}).get('mode')
        if old==new and mode=='ANY' and gemini_worker.FUNCTION_CALLING_MODE=='AUTO':
            changed.append('functionCallingConfig.mode')
        if not changed:return None
    except (ValueError,OSError,KeyError,TypeError):return None
    return dict(task=attempt['task'],kind='provider_schema_repair',
                rejected_request_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                rejection_sha256=hashlib.sha256(outcome_path.read_bytes()).hexdigest(),
                previous_runtime_sha256=previous,current_runtime_sha256=current,changed_tools=changed,
                instruction='Use the corrected installed fragment transport in a bounded successor. Preserve completed source work and all original attempts. Reuse exact accepted input versions; do not repeat search/source collection or infer acceptance. The old request was definitively rejected, not replayed.')


def registered_preflight_gap(rt,attempt,receipt):
    """Native read adapters prove their own pre-dispatch validation boundary."""
    import importlib
    from pathlib import Path
    from orchestrator.execution import REGISTRY
    frozen=json.loads(attempt['frozen']);meta=REGISTRY.get(frozen.get('execution',{}).get('capability'),{})
    hook=meta.get('preflight_recovery')
    if not hook or frozen.get('max_attempts',1)!=1 or meta.get('saved_evidence',{}).get('kind') not in ('pages','photos'):return None
    if (receipt.get('status')!='finished' or receipt.get('exit_code')!=1 or receipt.get('pending_requests')
            or receipt.get('operation',{}).get('outcome')!='failed' or receipt.get('cleanup_error')):return None
    module,name=hook.split(':');adapter=importlib.import_module(module)
    current=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest()
    previous=frozen.get('runtime_sources',{}).get(Path(adapter.__file__).name)
    if not previous or previous==current:return None
    if any((Path(frozen['workspace'])/o['path']).exists() for o in frozen['outputs']):return None
    try:
        data={}
        for item in frozen['inputs']:
            artifact=rt.artifact(item['artifact']);raw=Path(artifact['blob']).read_bytes()
            if artifact['sha256']!=item['sha256'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:return None
            data[item['path']]=raw
        proof=getattr(adapter,name)(frozen,receipt,rt.root/'workers'/attempt['id'],lambda path:data[path])
    except (ValueError,OSError,KeyError,TypeError):return None
    if not proof or proof.get('execution')!='not_started' or proof.get('quiescent') is not True:return None
    return dict(kind='registered_input_preflight',task=attempt['task'],attempt=attempt['id'],proof=proof,
        previous_runtime_sha256=previous,current_runtime_sha256=current,instruction=proof['instruction'])


def snapshot(state, run, *, photo_recovery=False):
    """Only confirmed, finished read-only work can seed a new research cycle."""
    from . import production_control as pc
    from orchestrator.runtime import Runtime
    rt = Runtime(pc.root(state), connection=state.db, read_only=True)
    tasks = [dict(t) for t in state.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id', (run,))]
    if not tasks or any(t['status'] in ('launching', 'running', 'cancelling', 'uncertain') for t in tasks):
        return None
    attempts = [dict(a) for a in state.db.execute('SELECT * FROM production_attempts WHERE run=? ORDER BY id', (run,))]
    for a in attempts:
        receipt = json.loads(a['receipt'] or '{}')
        if (a['state'] not in ('completed', 'blocked') or receipt.get('status') != 'finished'
                or receipt.get('pending_requests') or receipt.get('browser', {}).get('uncertain_actions')):
            return None
        if any(x.get('status') != 'observed' for x in receipt.get('browser', {}).get('actions', [])):
            return None
        frozen = json.loads(a['frozen'])
        from orchestrator.execution import REGISTRY
        read_caps={cap for cap,spec in REGISTRY.items() if spec.get('saved_evidence',{}).get('kind') in (('pages','photos') if photo_recovery else ('pages',))}
        local_caps={cap for cap,spec in REGISTRY.items() if spec.get('completion_recovery')=='local_artifact'
                    and spec.get('kind')=='procedure' and spec.get('external_requests')==0}
        if photo_recovery:read_caps.add('images.merge')
        capability=frozen.get('execution', {}).get('capability')
        if capability not in {None,*read_caps,*local_caps}:
            return None  # Host operations and other effects use their own recovery.
        if capability in local_caps and (receipt.get('operation',{}).get('outcome') not in ('completed','failed')
                                        or receipt.get('cleanup_error')):return None
        if frozen.get('computer'):
            return None
        if frozen.get('backend', {}).get('type') != 'codex-cli' and not frozen.get('execution'):
            if receipt.get('external_outcome') != 'no_pending_response':
                return None
    gaps = []
    for t in tasks:
        if t['status'] != 'blocked':
            continue
        a = next((a for a in attempts if a['id'] == t['latest']), None)
        if not a:
            return None
        receipt = json.loads(a['receipt'])
        frozen=json.loads(a['frozen'])
        if not frozen.get('review_of') and a['state']=='completed':
            # A completed independent review can leave its producer blocked
            # when the local correction is inapplicable/exhausted. Preserve
            # that review as the gap; do not look for a producer self-rejection.
            reviewer=rt.reviewer(run,t['id'])
            reviewed=next((v for v in attempts if reviewer and v['id']==reviewer['latest']),None)
            if reviewed and reviewed['state']=='completed':
                rf=json.loads(reviewed['frozen']);rr=json.loads(reviewed['receipt'] or '{}')
                for event in state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(reviewed['id'],)):
                    value=json.loads(event[0]);result=value.get('result',{});findings=result.get('findings',[])
                    if (value.get('kind')=='model_review' and result.get('assignment_id')==reviewed['id']
                            and result.get('decision')=='revise' and rf.get('review_target')==a['id']
                            and rr.get('status')=='finished' and not rr.get('exit_code') and not rr.get('pending_requests')
                            and any(f.get('category') in ('requirements','integrity') for f in findings)
                            and all(f.get('category') in ('requirements','integrity','advisory') for f in findings)):
                        gaps.append(dict(task=reviewer['id'],kind='review_gaps',candidate_task=t['id'],
                            findings=findings,reported_decision='revise',effective_status=t['status'],
                            instruction=result.get('instruction','')))
                        break
                if gaps and gaps[-1].get('candidate_task')==t['id']:continue
        from orchestrator.continuation_adapters import detect_gap
        continuation=detect_gap(rt,t,a,photo_recovery)
        if continuation:
            gaps.append(continuation)
            continue
        repair=schema_repair_gap(rt,a,receipt)
        if repair:
            gaps.append(repair)
            continue
        budget_reason=str(receipt.get('reason',''))
        if ('Provider request budget exhausted' in budget_reason
                or budget_reason.removeprefix('ValueError: ')=='Tool budget exhausted before execution.'):
            gaps.append(dict(task=t['id'], kind='split_budget', instruction='Split remaining work into smaller independently reviewed units; retain saved progress.'))
            continue
        frozen=json.loads(a['frozen'])
        if photo_recovery and frozen.get('execution',{}).get('capability')=='images.fetch' and receipt.get('operation',{}).get('outcome')=='failed':
            from orchestrator.image_sources import unpack
            from pathlib import Path
            from .pipelines import artifact_source
            for artifact in state.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(a['id'],)):
                if artifact['path'] not in {o['path'] for o in frozen['outputs']}:continue
                try:
                    source=artifact_source(state,artifact['id'])
                    _,_,manifest=unpack(Path(source['path']).read_bytes())
                except (ValueError,OSError):continue
                missing=[s['id'] for s in manifest['subjects'] if s['status']=='missing']
                if missing and len(missing)==len(manifest['subjects']):
                    gaps.append(dict(task=t['id'],kind='photo_download_failed',missing=missing,base_photo=source,
                                     instruction='Confirmed failed public downloads only. Preserve the diagnostic base ZIP. Discover alternate observed image references under the original grant; fetch missing subjects, merge base first, and independently review. Never replay an uncertain action.'))
                    break
            if gaps and gaps[-1]['task']==t['id']:continue
        events = state.db.execute("SELECT data FROM production_events WHERE run=? AND attempt=? AND kind='checks_recorded' ORDER BY id DESC", (run, a['id'])).fetchall()
        reviewed = rt.spec(t).get('review_of')
        report_kind = 'model_review' if reviewed else 'worker_self_report'
        result = next((v['result'] for e in events if (v := json.loads(e[0])).get('kind') == report_kind), None)
        findings = result.get('findings', []) if result else []
        if reviewed and result is None and (frozen.get('source_verification') or frozen.get('report_contract')):
            # A rejected report is not acceptance. Reproduce the exact durable
            # response failure; permit bounded fresh review, never replay effects.
            response=state.db.execute("SELECT data FROM production_events WHERE run=? AND attempt=? AND kind='first_response' ORDER BY id DESC LIMIT 1",(run,a['id'])).fetchone()
            if response:
                from orchestrator import contracts as contracts
                try:
                    raw=json.loads(json.loads(response[0])['text'])
                except (ValueError,KeyError,TypeError):return None
                if raw.get('decision')!='accept' or any(f.get('category') not in ('advisory','requirements','integrity') for f in raw.get('findings',[])):return None
                try:contracts.report(raw,frozen)
                except ValueError as exc:
                    target=next((x for x in tasks if x['id']==reviewed),None)
                    if str(exc)!=a['error'] or not target or target['latest']!=frozen.get('review_target'):return None
                    gaps.append(dict(task=t['id'],kind='review_format',findings=[dict(category='integrity',code='review_report_rejected',message=str(exc),evidence='Exact persisted first_response and current frozen review target')],
                        response_sha256=hashlib.sha256(response[0].encode()).hexdigest(),
                        instruction='Preserve the existing candidate bytes and reuse saved source receipts. Correct the independent review against the prospective compiled contract and explicit current policy; use supplied artifact references or exact declared file paths, never invented pointers. Do not retain an acceptance decision with failed checks. Missing support remains unresolved or blocked under that policy. Do not repeat completed source collection solely to repair this report, or accept the prior rejected report.'))
                    continue
                return None
        if not reviewed:
            from orchestrator.record_recovery import incomplete_result
            incomplete=incomplete_result(frozen,receipt,result,state.db)
            if incomplete:
                gaps.append(dict(task=t['id'],kind='registered_record_incomplete',proof=incomplete,
                    findings=[dict(category='requirements',code='incomplete_registered_records',
                        message='The exact registered local projection is not complete.',evidence=encoded(incomplete))],
                    reported_decision='blocked',effective_status=t['status'],
                    instruction='Complete the remaining registered records in an independently reviewed bounded successor. Use the registered schema and its procedural criteria; preserve exact inputs, prior records and receipts. Do not replay external work or infer acceptance.'))
                continue
            # A producer may discover missing mandatory evidence before review.
            # This is a continuation proposal, never acceptance of its draft.
            # Require the exact finished attempt and typed requirements only;
            # permission, quality and unknown effects retain their own gates.
            if (not result or result.get('assignment_id') != a['id']
                    or result.get('decision') != 'blocked' or not findings
                    or not any(f.get('category') == 'requirements' for f in findings)
                    or any(f.get('category') not in ('requirements', 'advisory') for f in findings)):
                return None
            gaps.append(dict(task=t['id'], kind='producer_gaps', findings=findings,
                             reported_decision=result['decision'], effective_status=t['status'],
                             instruction=result.get('instruction', '')))
            continue
        target = next((x for x in tasks if x['id'] == reviewed), None)
        frozen = json.loads(a['frozen'])
        # Runtime disposition may block an 'accept' report with requirements
        # findings. The finished blocked task, not that word, controls recovery.
        if (not reviewed or not target or frozen.get('review_target') != target['latest']
                or not findings or result.get('decision') not in ('blocked', 'revise', 'accept')
                or not any(f.get('category') in ('requirements', 'integrity', 'quality') for f in findings)
                or any(f.get('category') not in ('requirements', 'integrity', 'quality', 'advisory') for f in findings)):
            return None
        gaps.append(dict(task=t['id'], kind='review_gaps', findings=findings,
                         reported_decision=result.get('decision'), effective_status=t['status'],
                         instruction=result.get('instruction', '')))
    if not gaps:
        from .delivery_completion import recovery_gap
        gap=recovery_gap(state,run,rt)
        if gap:gaps.append(gap)
        else:return None
    # Include immutable originals and every saved partial/review; never call them accepted.
    artifacts = [dict(a) for a in state.db.execute('SELECT * FROM production_artifacts WHERE run=? ORDER BY id', (run,))]
    plan = json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()[0])
    identities = [dict(id=a['id'], task=a['task'], state=a['state'],
                       receipt_sha256=hashlib.sha256((a['receipt'] or '').encode()).hexdigest(),
                       frozen_sha256=hashlib.sha256(a['frozen'].encode()).hexdigest()) for a in attempts]
    return dict(run=run, tasks=tasks, attempts=identities, gaps=gaps, artifacts=artifacts,
                plan=plan, attempts_reset=False, user_accepted=False)


def local_revision(rt, baseline):
    """A concrete local defect can use the original producer/reviewer capacity.

    No graph, criteria, worker or allowance is changed. This is correction, not
    acceptance of the rejected candidate or a grant to repeat host effects.
    """
    if len(baseline['gaps'])!=1:return None
    gap=baseline['gaps'][0]
    if (gap.get('kind')!='review_gaps' or gap.get('reported_decision')!='revise'
            or not gap.get('instruction','').strip() or not gap.get('findings')
            or any(f['category'] not in ('requirements','integrity','advisory') for f in gap['findings'])):return None
    review=rt.task(baseline['run'],gap['task']);rs=rt.spec(review)
    producer=rt.task(baseline['run'],rs['review_of']);ps=rt.spec(producer)
    from orchestrator import executors
    for task,spec in ((producer,ps),(review,rs)):
        if (any(spec.get(k) for k in ('browser','computer','execution','operation_contract','user_gate'))
                or task['attempts']>=spec.get('max_attempts',0)):return None
        attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
        frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
        kind=frozen['backend']['type']
        if (kind not in (*executors.FILE_TYPES,*executors.CODE_TYPES,'codex-cli')
                or receipt.get('status')!='finished' or receipt.get('exit_code')
                or receipt.get('pending_requests') or receipt.get('cleanup_error')
                or kind!='codex-cli' and receipt.get('external_outcome')!='no_pending_response'):return None
        from orchestrator.runtime import file_hash
        for item in frozen['inputs']:
            artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
            if blob.is_symlink() or artifact['sha256']!=item['sha256'] or file_hash(blob)!=item['sha256']:return None
    if (review['status']!='blocked' or producer['status']!='awaiting_review'
            or frozen.get('review_target')!=producer['latest']):return None
    descendants={producer['id']}
    tasks=list(rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(baseline['run'],)))
    for _ in tasks:
        descendants.update(t['id'] for t in tasks if set(rt.spec(t)['dependencies']) & descendants)
    if any(t['attempts'] and t['id'] in descendants and t['id'] not in (producer['id'],review['id']) for t in tasks):return None
    for artifact in baseline['artifacts']:
        blob=Path(artifact['blob'])
        if blob.is_symlink() or blob.stat().st_size!=artifact['bytes'] or file_hash(blob)!=artifact['sha256']:return None
    return dict(producer=producer['id'],review=review['id'],review_attempt=review['latest'],
                candidate=producer['latest'],instruction=gap['instruction'])


def queue_local_revision(state,rt,p,s,baseline,proof):
    from . import pipelines,production_control as pc
    run=baseline['run']
    rt.revise(run,proof['producer'],proof['instruction'],'model_review:'+proof['review_attempt'])
    if rt.task(run,proof['producer'])['status']!='queued':raise ValueError('Original correction capacity was exhausted')
    digest=hashlib.sha256(encoded(baseline).encode()).hexdigest()
    task=rt.task(run,proof['producer']);spec=rt.spec(task)
    spec['revision'].update(kind='confirmed_local_revision',recovery_baseline_sha256=digest)
    aid=rt.new_assignment(run,spec)
    state.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?',(aid,run,proof['producer']))
    state.put('production-enabled:'+run,pc.runtime_digest(rt,run))
    state.db.execute("UPDATE relay_pipeline_steps SET status='running',error=NULL WHERE pipeline=? AND id=?",(p['id'],s['id']))
    pipelines.event(state,p['id'],s['id'],'completion_local_revision_queued',dict(parent=run,**proof,
        baseline_sha256=digest,assignment_sha256=hashlib.sha256(encoded(spec).encode()).hexdigest(),
        attempts_reset=False,allowances_expanded=False,provider_planning_calls=0,accepted=False))


def validate_local_revision(rt,task,spec,backend):
    from orchestrator.runtime import file_hash
    revision=spec['revision'];digest=revision['recovery_baseline_sha256']
    rows=rt.db.execute('SELECT baseline FROM completion_recoveries WHERE parent=?',(task['run'],)).fetchall()
    baselines=[json.loads(r[0]) for r in rows if hashlib.sha256(r[0].encode()).hexdigest()==digest]
    if len(baselines)!=1:raise ValueError('Local correction lacks its exact committed baseline')
    baseline=baselines[0]
    old=next((a for a in baseline['attempts'] if a['id']==revision['previous_attempt'] and a['task']==task['id']),None)
    if not old or task['latest']!=old['id']:raise ValueError('Local correction changed its producer candidate')
    for saved in baseline['attempts']:
        current=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(saved['id'],)).fetchone()
        if (not current or hashlib.sha256((current['receipt'] or '').encode()).hexdigest()!=saved['receipt_sha256']
                or hashlib.sha256(current['frozen'].encode()).hexdigest()!=saved['frozen_sha256']):
            raise ValueError('Local correction changed its confirmed review evidence')
        if saved['id']==old['id'] and json.loads(current['frozen'])['backend']!=backend:
            raise ValueError('Local correction changed its authorized worker')
    for artifact in baseline['artifacts']:
        blob=Path(artifact['blob'])
        if blob.is_symlink() or blob.stat().st_size!=artifact['bytes'] or file_hash(blob)!=artifact['sha256']:
            raise ValueError('Local correction changed saved candidate bytes')
    events=rt.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='completion_local_revision_queued' AND json_extract(detail,'$.parent')=?",(task['run'],)).fetchall()
    expected=hashlib.sha256(encoded(spec).encode()).hexdigest()
    if not any((v:=json.loads(r[0])).get('baseline_sha256')==digest and v.get('assignment_sha256')==expected and v.get('producer')==task['id'] for r in events):
        raise ValueError('Local correction changed its committed assignment')


def begin(state, p, s, run):
    from . import pipelines
    from .workflow_state import decision
    def hold(code,reason,action='inspect_recovery'):
        return decision(state,p,s,code,reason,action)
    if not state.db.in_transaction:
        raise ValueError('Recovery intent requires an atomic transaction.')
    if p['status'] != 'active' or s['status'] != 'running':
        return hold('owner_stopped','The workflow or stage is not active.','resume')
    from orchestrator.runtime import Runtime
    from . import production_control as pc
    from .continuation_owner import resume_original
    rt=Runtime(pc.root(state),connection=state.db);current=snapshot(state,run)
    if resume_original(state,rt,p,s,current):return True
    grant = state.db.execute('SELECT * FROM completion_recovery_grants WHERE pipeline=?', (p['id'],)).fetchone()
    if not grant:
        return hold('grant_missing','No recovery authorization is recorded for this workflow.','review_authorization')
    policy=json.loads(grant['policy'])
    if policy not in (POLICY,LEGACY_DELIVERY_POLICY,DELIVERY_POLICY):
        return hold('grant_unsupported','The saved recovery policy is unsupported. It was preserved.','review_authorization')
    from .local_review import resume_zero_dispatch
    from .continuation_owner import resume_finalization
    if (resume_zero_dispatch(state,rt,p,s,current)
            or resume_finalization(state,rt,p,s,current)):
        return True
    cycle = (state.db.execute('SELECT count(*) FROM completion_recoveries WHERE pipeline=? AND step=?', (p['id'],s['id'])).fetchone()[0]
             if policy.get('cycle_scope')=='stage' else state.db.execute('SELECT count(*) FROM completion_recoveries WHERE pipeline=?',(p['id'],)).fetchone()[0]) + 1
    extra=state.db.execute('SELECT coalesce(sum(cycles),0) FROM completion_recovery_extensions WHERE pipeline=? AND step=?',(p['id'],s['id'])).fetchone()[0]
    if cycle > policy['cycles']+extra:
        return hold('capacity_exhausted','All authorized recovery cycles for this stage have been used.','review_authorization')
    authority=grant['request']
    if cycle>policy['cycles']:
        boundary=policy['cycles']
        for extension in state.db.execute('SELECT request,cycles FROM completion_recovery_extensions WHERE pipeline=? AND step=? ORDER BY rowid',(p['id'],s['id'])):
            boundary+=extension['cycles']
            if cycle<=boundary:
                authority=extension['request'];break
    baseline = snapshot(state, run, **({'photo_recovery':True} if policy==DELIVERY_POLICY else {}))
    if baseline is None:
        return hold('proof_unavailable','The stopped execution has no supported confirmed recovery proof. Inspect its exact receipts; no replay was authorized.','inspect_receipt')
    if state.db.execute('SELECT 1 FROM completion_recoveries WHERE parent=? AND baseline=?',(run,encoded(baseline))).fetchone():
        return hold('baseline_already_allocated','This exact failure already has a saved recovery allocation. Inspect that successor rather than submitting it again.','inspect_successor')
    if len(encoded(baseline).encode()) > 200000:
        return hold('context_capacity','The recovery evidence exceeds the admitted context size. Partition it before dispatch.','partition')
    stages=json.loads(p['spec']).get('stages',[]);position=dict(s).get('position')
    stage=stages[position] if type(position) is int and 0<=position<len(stages) else {}
    if policy==DELIVERY_POLICY and stage.get('gate')=='none':
        from . import production_control as pc
        from orchestrator.runtime import Runtime
        rt=Runtime(pc.root(state),connection=state.db)
        proof=local_revision(rt,baseline)
        if proof:
            ident=-int(hashlib.sha256((p['id']+':'+s['id']+':recovery:'+str(cycle)).encode()).hexdigest()[:15],16)-1
            state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',(p['id'],s['id'],run,cycle,ident,encoded(baseline)))
            queue_local_revision(state,rt,p,s,baseline,proof)
            return True
        from . import registered_revision
        if registered_revision.proof(rt,baseline):
            ident=-int(hashlib.sha256((p['id']+':'+s['id']+':recovery:'+str(cycle)).encode()).hexdigest()[:15],16)-1
            state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',(p['id'],s['id'],run,cycle,ident,encoded(baseline)))
            return registered_revision.queue(state,rt,p,s,baseline,cycle)
    if policy==DELIVERY_POLICY:
        from . import continuation_owner
        kind=continuation_owner.select(baseline,stage,policy)
        if kind:
            rt=Runtime(pc.root(state),connection=state.db)
            return continuation_owner.queue(state,rt,p,s,baseline,cycle,kind,authority,allocate=True)
    ids = list(dict.fromkeys([a['id'] for a in baseline['artifacts']] +
               [i['artifact'] for t in baseline['plan']['tasks'] for i in t.get('inputs', []) if i.get('artifact')]))
    sources = [pipelines.artifact_source(state, ident) for ident in ids]
    ident = -int(hashlib.sha256((p['id']+':'+s['id']+':recovery:'+str(cycle)).encode()).hexdigest()[:15], 16)-1
    detail = dict(parent=run, cycle=cycle, policy=policy, authorization=authority, baseline=baseline)
    state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',
                     (p['id'], s['id'], run, cycle, ident, encoded(baseline)))
    state.db.execute("UPDATE relay_pipeline_steps SET target=NULL,target_kind=NULL,error=NULL WHERE pipeline=? AND id=?", (p['id'], s['id']))
    pipelines.enqueue_step(state, p, s, request_id=ident,
                           recovery=dict(detail=detail, sources=sources))
    current=state.db.execute('SELECT target FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],s['id'])).fetchone()
    if not current['target']:admit_saved_stage(state, p, s, ident, run)
    pipelines.event(state, p['id'], s['id'], 'completion_recovery_queued', detail)
    return True


def reconcile_changed_failures(state):
    """A resumed run may have a later confirmed defect under its same grant."""
    from . import pipelines,production_control as pc
    from .relay_channels import ScopedState
    from orchestrator.runtime import Runtime
    from orchestrator.storage import transaction
    reconcile_detached_admission(state)
    reconcile_stranded_local_revision(state)
    rows=state.db.execute("SELECT p.* FROM relay_pipelines p JOIN completion_recovery_grants g ON g.pipeline=p.id WHERE p.status='blocked'").fetchall()
    for p in rows:
        s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status NOT IN ('completed','skipped') ORDER BY position LIMIT 1",(p['id'],)).fetchone()
        if not s or s['status']!='blocked':continue
        run=s['target'] if s['target_kind']=='production_run' else None
        if s['target_kind']=='plan_production':
            plan=state.db.execute('SELECT * FROM production_plans WHERE id=?',(s['target'],)).fetchone()
            if not plan or plan['status']!='started' or plan['channel']!=p['channel']:continue
            run=plan['run']
        if not run:continue
        scoped=ScopedState(state,p['channel'])
        if scoped.get('production-control-epoch:'+run,0)!=0:continue
        stage=json.loads(p['spec'])['stages'][s['position']]
        if stage.get('gate')!='none' or state.db.execute('SELECT 1 FROM production_decisions WHERE run=?',(run,)).fetchone():continue
        # begin() is the authoritative proof, grant and capacity gate. A second
        # error-text/gap allowlist here stranded newly registered recoveries.
        rt=Runtime(pc.root(scoped),connection=state.db)
        row=state.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()
        if not row or row['status']!='active' or rt.status(run)['status']!='blocked':continue
        try:
            with transaction(state.db):
                # Native admission reads the saved owner, not the prospective
                # dictionary. Commit its activation together with recovery.
                state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
                if not begin(scoped,dict(p,status='active'),dict(s,status='running'),run):
                    from .workflow_state import denied
                    raise denied(state,p,s,'Changed failure has no admissible recovery.')
                pipelines.event(state,p['id'],s['id'],'changed_failure_recovered',dict(parent=run,previous_error=s['error'],attempts_reset=False,authority='changed confirmed baseline and remaining original recovery cycles'))
        except (ValueError,OSError) as exc:
            from .workflow_state import failure,refresh
            with transaction(state.db):
                failure(state,p,s,exc)
                refresh(state,p['id'])


def reconcile_detached_admission(state):
    """Restore a confirmed failed plan's committed pointer; never resubmit it."""
    from orchestrator.storage import transaction
    from . import pipelines
    rows=state.db.execute('''SELECT s.*,p.channel FROM relay_pipeline_steps s
        JOIN relay_pipelines p ON p.id=s.pipeline
        WHERE p.status='active' AND s.status='running' AND s.target IS NULL AND s.target_kind IS NULL''').fetchall()
    for step in rows:
        receipt=state.db.execute('SELECT * FROM completion_recoveries WHERE pipeline=? AND step=? AND request_id=?',
                                (step['pipeline'],step['id'],step['request_id'])).fetchone()
        if not receipt:continue
        plans=state.db.execute("SELECT * FROM production_plans WHERE request_id=? AND channel=? AND status='blocked' AND run IS NULL",(step['request_id'],step['channel'])).fetchall()
        if len(plans)!=1:continue
        plan=plans[0];context=json.loads(plan['context'])
        if (hashlib.sha256(encoded(context).encode()).hexdigest()!=plan['context_hash']
                or context.get('completion_recovery',{}).get('baseline_sha256')!=hashlib.sha256(receipt['baseline'].encode()).hexdigest()):continue
        calls=state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(plan['id'],)).fetchall()
        if not calls or any(not r['response'] or not r['usage'] for r in calls):continue
        events=state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND step=? AND kind='dispatched'",(step['pipeline'],step['id']))
        expected=dict(request_id=step['request_id'],kind='plan_production',target=plan['id'])
        if not any(json.loads(r[0])==expected for r in events):continue
        with transaction(state.db):
            updated=state.db.execute("UPDATE relay_pipeline_steps SET target_kind='plan_production',target=?,status='blocked',error=? WHERE pipeline=? AND id=? AND request_id=? AND status='running' AND target IS NULL AND target_kind IS NULL",
                (plan['id'],plan['error'],step['pipeline'],step['id'],step['request_id']))
            if updated.rowcount!=1:continue
            state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=? AND status='active'",(step['pipeline'],))
            pipelines.event(state,step['pipeline'],step['id'],'dispatched_recovery_target_restored',dict(plan=plan['id'],request_id=step['request_id'],cycle=receipt['cycle'],resubmitted=False))


def planning_recovery_receipt(state, pipeline, step, plan):
    """Follow exact rejected-request retry receipts without changing allocation."""
    from .production_planning import rate_limited_plan
    current=plan;seen=set()
    while current['id'] not in seen:
        seen.add(current['id'])
        receipt=state.db.execute('SELECT * FROM completion_recoveries WHERE pipeline=? AND step=? AND request_id=?',
            (pipeline,step,current['request_id'])).fetchone()
        if receipt:return receipt
        events=state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND step=? AND kind='planning_retry_requested' AND json_extract(detail,'$.successor')=?",(pipeline,step,current['id'])).fetchall()
        if len(events)!=1:return None
        detail=json.loads(events[0][0]);prior=state.db.execute('SELECT * FROM production_plans WHERE id=?',(detail.get('plan_id'),)).fetchone()
        if (not prior or not rate_limited_plan(state,prior) or detail.get('context_hash')!=prior['context_hash']
                or detail.get('call')!=prior['calls'] or not detail.get('request')
                or any(current[k]!=prior[k] for k in ('channel','request','context','context_hash','options','provider','model'))):return None
        current=prior
    return None


def reconcile_stranded_local_revision(state):
    """A failed unexecuted replan must not strand usable original capacity.

    Preserve its replies and spent recovery receipt. Rebind to the unchanged
    original run only when the exact sealed baseline still admits local revision.
    """
    from . import production_control as pc,pipelines
    from .relay_channels import ScopedState
    from orchestrator.runtime import Runtime
    from orchestrator.storage import transaction
    for p in state.db.execute("SELECT p.* FROM relay_pipelines p JOIN completion_recovery_grants g ON g.pipeline=p.id WHERE p.status='blocked' AND g.policy=?",(encoded(DELIVERY_POLICY),)).fetchall():
        s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status NOT IN ('completed','skipped') ORDER BY position LIMIT 1",(p['id'],)).fetchone()
        if not s or s['status']!='blocked' or s['target_kind']!='plan_production':continue
        stages=json.loads(p['spec']).get('stages',[]);position=dict(s).get('position')
        stage=stages[position] if type(position) is int and 0<=position<len(stages) else {}
        if stage.get('gate')!='none':continue
        plan=state.db.execute('SELECT * FROM production_plans WHERE id=?',(s['target'],)).fetchone()
        if not plan or plan['status']!='blocked' or plan['run'] or plan['channel']!=p['channel']:continue
        receipt=planning_recovery_receipt(state,p['id'],s['id'],plan)
        if not receipt:continue
        calls=state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(plan['id'],)).fetchall()
        if not calls or any(not r['response'] or not r['usage'] for r in calls):continue
        scoped=ScopedState(state,p['channel']);run=receipt['parent']
        if scoped.get('production-control-epoch:'+run,0) or state.db.execute('SELECT 1 FROM production_decisions WHERE run=?',(run,)).fetchone():continue
        baseline=json.loads(receipt['baseline']);digest=hashlib.sha256(encoded(baseline).encode()).hexdigest()
        from orchestrator import contracts as contracts
        context=json.loads(plan['context'])
        if contracts.digest(context)!=plan['context_hash'] or context.get('completion_recovery',{}).get('baseline_sha256')!=digest:continue
        parent=state.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()
        if not parent or parent[0]!='active':continue
        try:
            with transaction(state.db):
                current=snapshot(scoped,run,photo_recovery=True)
                if not current:continue
                rt=Runtime(pc.root(scoped),connection=state.db)
                from . import registered_revision
                if current==baseline and registered_revision.queue(scoped,rt,p,s,baseline,receipt['cycle']):continue
                if any(not r['error'] for r in calls):continue
                proof=local_revision(rt,baseline)
                if proof:
                    if current!=baseline:continue
                    queue_local_revision(scoped,rt,p,s,baseline,proof)
                else:
                    # Historical replan may have classified a confirmed local
                    # invocation as a generic budget stop. Preserve that receipt;
                    # only its read-only classification may differ now.
                    if ({k:v for k,v in current.items() if k!='gaps'}!={k:v for k,v in baseline.items() if k!='gaps'}
                            or len(current['gaps'])!=1 or current['gaps'][0]['kind']!='local_review_session'
                            or len(baseline['gaps'])!=1 or baseline['gaps'][0]['task']!=current['gaps'][0]['task']
                            or baseline['gaps'][0]['kind'] not in ('split_budget','confirmed_review_generation','local_review_session')):continue
                    from .local_review import queue
                    queue(scoped,rt,p,s,baseline,current['gaps'][0],receipt['cycle'])
                state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target=? WHERE pipeline=? AND id=?",(run,p['id'],s['id']))
                state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
                pipelines.event(scoped,p['id'],s['id'],'stranded_local_revision_recovered',dict(parent=run,
                    preserved_failed_plan=plan['id'],cycle=receipt['cycle'],baseline_sha256=digest,
                    attempts_reset=False,allowances_expanded=False,provider_planning_calls=0,accepted=False))
        except (ValueError,OSError,KeyError,TypeError):continue


def admit_saved_stage(state, p, s, ident, run):
    """Known standalone research routing needs no second recommendation model.

    Keep the ordinary native planner and Start checks. Non-standalone stages fall
    back to the existing router rather than guessing a project or source choice.
    """
    from . import pipelines, production_planning as planning, orchestrator_chat as chat
    original=state.db.execute('SELECT options FROM production_plans WHERE run=?', (run,)).fetchone()
    if not original:return False
    options=json.loads(original['options'])
    if options.get('project') is not None or options.get('reference_pack_id') is not None:return False
    stage=json.loads(p['spec'])['stages'][s['position']]
    if stage['route']!='production':return False
    action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                research_ids=[],reference_ids=[],planning_only=False,
                step_capabilities=stage['capabilities'],deliverables=stage['deliverables'],
                task_seconds=POLICY['seconds'])
    if 'research_mode' in stage:action['research_mode']=stage['research_mode']
    job=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()
    snap=chat.snapshot(state,p['id']);snap['pipeline_step']=pipelines.request_context(state,ident)
    pipelines.guard(state,job,action)
    result=planning.enqueue(state,job,action,snap)
    pipelines.observe_dispatch(state,job,action)
    state.db.execute("UPDATE orchestrator_chats SET status='answered',answer=?,snapshot=? WHERE id=? AND status='queued'",
                     (result,encoded(snap),ident))
    pipelines.event(state,p['id'],s['id'],'recovery_admission_compiled',
                    dict(request_id=ident,action=action,authority='Saved production stage and explicit recovery grant',
                         interpretation_provider_called=False,workers_started=False))
    return True


def check_observed_photos(state, receipt, baseline, plan):
    """Validate a separate evidence-only continuation, never resolve its parent."""
    from orchestrator.browser_review_inputs import saved_manifest
    from orchestrator.runtime import Runtime, safe_file
    from . import production_control as pc
    gap=baseline['gaps'][0];parent=gap['attempt'];run=baseline['run']
    if receipt['parent']!='observed-photo:'+parent:
        raise ValueError('Observed photo continuation changed its evidence parent')
    current=[dict(a) for a in state.db.execute('SELECT * FROM production_attempts WHERE run=? ORDER BY id',(run,))]
    if current!=baseline['attempts'] or any(a['state'] in ('launching','running','cancelling') for a in current):
        raise ValueError('Observed photo continuation changed its stopped attempts')
    old=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()
    if not old or json.loads(old[0])!=baseline['plan']:
        raise ValueError('Observed photo continuation changed its original plan')
    attempt=next((a for a in current if a['id']==parent),None)
    if not attempt:raise ValueError('Observed photo continuation lacks its stopped producer')
    raw,pack,proof=saved_manifest(state.db,attempt)
    if proof!=gap['proof']:
        raise ValueError('Observed photo continuation changed its exact export proof')
    if any(t.get('browser') or t.get('computer') or (not t.get('execution') and not t.get('review_of'))
           or t.get('execution',{}).get('capability') not in (None,'images.fetch','images.merge') for t in plan['tasks']):
        raise ValueError('Observed photo continuation cannot replay browser or producer work')
    rt=Runtime(pc.root(state),connection=state.db,read_only=True)
    fetches=[t for t in plan['tasks'] if t.get('execution',{}).get('capability')=='images.fetch']
    if len(fetches)!=1 or len(fetches[0]['inputs'])!=1:
        raise ValueError('Observed photo continuation requires only its one saved manifest')
    source=rt.artifact(fetches[0]['inputs'][0].get('artifact'))
    blob=Path(source['blob']);safe_file(Path(blob.anchor),str(blob.relative_to(blob.anchor)))
    if source['sha256']!=hashlib.sha256(raw).hexdigest() or source['bytes']!=len(raw) or blob.stat().st_size!=len(raw) or blob.read_bytes()!=raw:
        raise ValueError('Observed photo continuation changed its manifest bytes')
    sources=baseline['artifacts']
    if len(sources)!=1:raise ValueError('Observed photo continuation needs one reviewed base branch')
    source=sources[0];current_source=rt.artifact(source['id'])
    if current_source!=source:raise ValueError('Observed photo continuation changed its reviewed ZIP')
    blob=Path(source['blob']);safe_file(Path(blob.anchor),str(blob.relative_to(blob.anchor)))
    if blob.stat().st_size!=source['bytes'] or hashlib.sha256(blob.read_bytes()).hexdigest()!=source['sha256']:
        raise ValueError('Observed photo continuation changed its reviewed ZIP bytes')
    producer=rt.task(run,source['task']);reviewers=[t for t in state.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))
        if t['status']=='completed' and rt.spec(t).get('review_of')==producer['id']]
    if (producer['status']!='completed' or producer['latest']!=source['attempt']
            or not any(json.loads(state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(t['latest'],)).fetchone()[0]).get('review_target')==source['attempt'] for t in reviewers)):
        raise ValueError('Observed photo continuation lacks current independent ZIP review')
    bases=[i['artifact'] for t in baseline['plan']['tasks'] if t.get('execution',{}).get('capability')=='images.merge'
           for i in t['inputs'] if i.get('artifact')]
    merges=[t for t in plan['tasks'] if t.get('execution',{}).get('capability')=='images.merge']
    if (len(bases)!=1 or len(merges)!=1 or merges[0]['inputs'][0].get('artifact')!=bases[0]
            or not any(i.get('artifact')==source['id'] for i in merges[0]['inputs'])
            or not any(d.get('task')==merges[0]['id'] for d in plan.get('deliverables',{}).values())):
        raise ValueError('Observed photo continuation must preserve and deliver its complete base and reviewed ZIP')


def check_plan(state, p, s, row):
    """Bound the replacement graph, not just each worker's advertised limit."""
    if 'request_id' not in row.keys():
        return
    receipt = state.db.execute('SELECT * FROM completion_recoveries WHERE request_id=? AND pipeline=? AND step=?',
                               (row['request_id'], p['id'], s['id'])).fetchone()
    # Native recovery of an unexecuted saved response retains the original grant.
    candidate=dict(row);seen=set()
    while not receipt and candidate.get('parent_id'):
        from orchestrator import contracts as contracts
        ident=candidate['parent_id']
        if ident in seen:break
        seen.add(ident)
        if len(seen)>10:break
        marker=json.loads(candidate['context']).get('recovered_proposal',{})
        prior=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        if (marker.get('plan_id')!=ident or not prior or prior['status']!='blocked' or prior['run']
                or prior['channel']!=candidate['channel']):break
        call=state.db.execute('SELECT response FROM production_plan_calls WHERE plan_id=? AND number=?',(ident,marker.get('call'))).fetchone()
        if not call or not call['response'] or contracts.digest(call['response'])!=marker.get('response_sha256'):break
        candidate=dict(prior)
        receipt=state.db.execute('SELECT * FROM completion_recoveries WHERE request_id=? AND pipeline=? AND step=?',
                                 (candidate['request_id'],p['id'],s['id'])).fetchone()
    if not receipt:
        if json.loads(dict(row).get('context','{}')).get('completion_recovery'):
            raise ValueError('Recovery proposal lacks its exact saved authorization baseline.')
        return
    plan = json.loads(row['plan'])
    baseline = json.loads(receipt['baseline'])
    grant=state.db.execute('SELECT policy FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone()
    policy=json.loads(grant[0]) if grant else POLICY
    if policy not in (POLICY,LEGACY_DELIVERY_POLICY,DELIVERY_POLICY):
        raise ValueError('Unknown frozen recovery policy.')
    if len(baseline['gaps'])==1 and baseline['gaps'][0].get('kind')=='observed_public_photo':
        if policy!=DELIVERY_POLICY:raise ValueError('Observed photo continuation lacks its whole-delivery grant')
        check_observed_photos(state,receipt,baseline,plan)
    elif snapshot(state, receipt['parent'], **({'photo_recovery':True} if policy==DELIVERY_POLICY else {})) != baseline:
        raise ValueError('Recovery baseline changed; reconcile before dispatch.')
    if plan.get('reused_operations'):
        from . import external_evidence
        from orchestrator.runtime import Runtime
        from . import production_control as pc
        rt=Runtime(pc.root(state),connection=state.db)
        context=json.loads(row['context'])
        # Recompute provenance at Start, rather than trusting a planner snapshot.
        context['recorded_external_sources']=external_evidence.recorded_sources(rt,context['sources'],
            attempts={r['attempt'] for r in completed_read_operations(baseline)})
        context['completion_recovery']=planner_context(dict(parent=receipt['parent'],cycle=receipt['cycle'],
            policy=policy,authorization='',baseline=baseline))
        validate_operation_reuse(plan,context,plan['reused_operations'])
    tasks = plan['tasks']
    if len(tasks) > policy['tasks_per_cycle']:
        raise ValueError('Recovery graph exceeds its aggregate task budget.')
    old = baseline['plan']
    validate_carried_deliveries(state,plan,baseline)
    for gap in baseline['gaps']:
        if gap.get('kind') in ('delivery_photos','photo_download_failed'):
            base=gap['base_photo']['artifact']
            merges=[t for t in tasks if t.get('execution',{}).get('capability')=='images.merge'
                    and t.get('inputs') and t['inputs'][0].get('artifact')==base]
            if not merges or not any(d.get('task') in {t['id'] for t in merges} for d in plan.get('deliverables',{}).values()):
                raise ValueError('Photo recovery must deliver a reviewed merge with the exact base ZIP first.')
    if set(plan.get('deliverables', {})) != set(old.get('deliverables', {})) or plan.get('deferred_operations') != old.get('deferred_operations'):
        raise ValueError('Recovery changed the final deliverables or deferred operations.')
    from orchestrator.executors import request_limit
    browsers = [t.get('browser') for t in old['tasks'] if t.get('browser')]
    def backend(task, graph):
        return (task.get('worker') or {}).get('backend') or task.get('backend') or graph.get('backend')
    backends = [backend(t, old) for t in old['tasks'] if not t.get('execution')]
    for t in tasks:
        if (t['max_attempts'] != 1 or t['limits']['seconds'] > policy['seconds']
                or t['limits']['tool_calls'] > policy['tool_calls'] or (not t.get('execution') and request_limit(t) > policy['tool_calls'])):
            raise ValueError('Recovery worker exceeds the frozen budget; split remaining work.')
        allowed={None,'web.sources'}
        original_caps={x.get('execution',{}).get('capability') for x in old['tasks']}
        if 'web.sources.prepared' in original_caps:allowed.add('web.sources.prepared')
        from orchestrator.execution import REGISTRY
        if policy==DELIVERY_POLICY:
            allowed|={cap for cap in original_caps if REGISTRY.get(cap,{}).get('completion_recovery')=='local_artifact'
                      and REGISTRY[cap].get('kind')=='procedure' and REGISTRY[cap].get('external_requests')==0}
        photos={cap for cap in original_caps if REGISTRY.get(cap,{}).get('saved_evidence',{}).get('kind')=='photos'}
        if policy==DELIVERY_POLICY and photos:
            allowed|=photos|{'images.merge'}
        if t.get('computer') or t.get('execution', {}).get('capability') not in allowed:
            raise ValueError('Research recovery cannot add host operations.')
        if t.get('browser') and not any(browser_subset(t['browser'],b) for b in browsers):
            raise ValueError('Recovery expanded the original browser grant.')
        if not t.get('execution') and backend(t, plan) not in backends:
            raise ValueError('Recovery changed the authorized worker provider or model.')
        if t.get('execution', {}).get('capability') == 'web.sources.prepared':
            parameters=t['execution'].get('parameters',{})
            original_parameters=[x['execution']['parameters'] for x in old['tasks'] if x.get('execution',{}).get('capability')=='web.sources.prepared']
            if not any(parameters.get('model')==x.get('model') and parameters.get('domains')==x.get('domains') for x in original_parameters):
                raise ValueError('Recovery changed the authorized prepared-source provider or domains.')
            # The registry bounds the validated upstream query document and
            # external requests; do not treat a native operation as an agent.
        if t.get('execution', {}).get('capability') == 'web.sources':
            parameters = t['execution'].get('parameters', {})
            old_sources = [x['execution']['parameters'] for x in old['tasks']
                           if x.get('execution', {}).get('capability') == 'web.sources']
            if not any(parameters.get('model') == x.get('model') and parameters.get('domains') == x.get('domains') for x in old_sources):
                raise ValueError('Recovery changed the authorized source provider or domains.')
            # One search and at most three page fetches per literal query.
            if not 1 <= len(parameters.get('queries', [])) <= policy['tool_calls'] // 4:
                raise ValueError('Recovery source queries exceed the bounded missing-evidence batch.')
        if (not t.get('review_of') and not REGISTRY.get(t.get('execution',{}).get('capability'),{}).get('review_evidence')
                and not any(r.get('review_of') == t['id'] for r in tasks)):
            raise ValueError('Recovery requires independent review of each producer.')


def authorize_standalone_correction(state, run, request):
    """Explicit two-cycle offline correction grant; never a sourcing grant."""
    from . import production_control as pc
    from orchestrator.runtime import Runtime
    if not state.db.in_transaction or not isinstance(request,str) or not request.strip():
        raise ValueError('Atomic exact human correction authorization is required.')
    rt=Runtime(pc.root(state),connection=state.db)
    owner=state.db.execute('SELECT channel FROM production_plans WHERE run=?',(run,)).fetchone()
    if owner and owner[0]!=getattr(state,'channel','telegram'):raise ValueError('Correction belongs to its original channel.')
    baseline=snapshot(state,run)
    if baseline is None:raise ValueError('Confirmed current review evidence is required.')
    correction_plan(rt,baseline,'correction-preflight',request)
    identity=hashlib.sha256(encoded(baseline).encode()).hexdigest()
    old=state.db.execute('SELECT * FROM standalone_correction_grants WHERE run=?',(run,)).fetchone()
    if old:
        if old['request']!=request or old['baseline_hash']!=identity:raise ValueError('Saved correction authority cannot be replaced.')
        return
    state.db.execute('INSERT INTO standalone_correction_grants VALUES (?,?,?,?,?,?,?,?)',
        (run,request,identity,run,0,getattr(state,'channel','telegram'),state.get('production-control-epoch:'+run,0),None))
    rt.event(run,None,None,'standalone_correction_authorized',dict(request=request,baseline_sha256=identity,cycles=2,scope='offline report correction only',user_accepted=False))


def correction_plan(rt, baseline, ident, request):
    """Compile an offline report pair from exact reviewed versions, no planner."""
    import copy
    from pathlib import PurePosixPath
    from orchestrator import contracts as c
    from orchestrator.executors import validate
    if len(baseline['gaps'])!=1 or baseline['gaps'][0]['kind']!='review_gaps':
        raise ValueError('Offline correction needs one current independent review gap.')
    gap=baseline['gaps'][0]
    if any(f.get('category')!='integrity' for f in gap['findings']):
        raise ValueError('Offline correction cannot waive requirements, quality, permission or uncertainty.')
    old=baseline['plan'];review=next(t for t in old['tasks'] if t['id']==gap['task'])
    producer=next(t for t in old['tasks'] if t['id']==review['review_of'])
    if producer.get('user_gate') or producer.get('execution') or producer.get('computer'):
        raise ValueError('Correction cannot add effects or resolve a user decision.')
    backend=copy.deepcopy((review.get('worker') or {}).get('backend') or review.get('backend') or old['backend'])
    if backend.get('type')!='codex-cli':raise ValueError('Offline correction requires the already authorized code reviewer.')
    outputs=copy.deepcopy(producer['outputs'])
    if not any(PurePosixPath(o['path']).suffix.lower() in ('.md','.txt') for o in outputs):
        raise ValueError('Automatic correction is limited to evidence reports.')
    inputs=[];seen=set()
    for t in old['tasks']:
        for i in t.get('inputs',[]):
            if i.get('artifact') and i['artifact'] not in seen:
                inputs.append(copy.deepcopy(i));seen.add(i['artifact'])
    for a in baseline['artifacts']:
        if a['id'] not in seen:
            inputs.append(dict(artifact=a['id'],path='saved/'+(a['task'] or 'runtime')+'/'+a['path'],purpose=a['purpose'],authority='Exact unaccepted prior evidence; retain source identity'))
            seen.add(a['id'])
    # Check immutable source bytes before admitting the successor.
    for i in inputs:rt.artifact(i['artifact'])
    correction='Exact human correction request: '+request+'\nOffline correction only. No network, browser, accounts, purchases or new source facts. Preserve every input unchanged. Correct report claims against saved observations and the exact independent review findings. Preserve the original assigned criteria; downstream gaps remain explicit, never accepted. Copy prior non-report outputs (images, manifests, provenance) byte-for-byte, retaining their historical job identity. Never invent hashes, controls or visual matches. Save corrected report at the same declared report path.\nOriginal assignment:\n'+producer['instruction']+'\nCurrent review findings:\n'+encoded(gap)
    limits=dict(seconds=600,tool_calls=24,output_bytes=min(producer['limits']['output_bytes'],100000000))
    first=dict(id='correct_report',role='producer',objective='Correct saved evidence report attribution',instruction=correction,criteria=copy.deepcopy(producer['criteria']),inputs=inputs,outputs=outputs,tools=validate(backend),limits=limits,max_attempts=1)
    second=dict(id='review_correction',role='reviewer',review_of=first['id'],dependencies=[first['id']],objective='Independently verify offline evidence correction',instruction='No network or new retrieval. Check each current finding against exact original source bytes and revised report. All prior non-report artifacts must be unchanged. Review only original criteria; no draft acceptance, purchasing completeness or aesthetic approval is inferred. Original review instruction: '+review['instruction'],criteria=copy.deepcopy(producer['criteria']),inputs=copy.deepcopy(inputs)+[dict(from_task=first['id'],output=o['path'],path='revised/'+o['path'],purpose=o['purpose'],authority='Unaccepted corrected output') for o in outputs],outputs=[dict(path='delivery/correction-review.md',purpose='Independent correction judgment')],tools=validate(backend),limits=dict(seconds=600,tool_calls=24,output_bytes=1000000),max_attempts=1)
    result=dict(id=ident,brief='Offline correction of '+baseline['run'],backend=backend,tasks=[first,second],origin=dict(parent=baseline['run'],exact_correction_request=request,baseline_sha256=hashlib.sha256(encoded(baseline).encode()).hexdigest(),user_accepted=False))
    if old.get('deliverables'):
        if any(v.get('task')!=producer['id'] for v in old['deliverables'].values()):raise ValueError('Correction cannot drop unrelated deliverables.')
        result['deliverables']={k:{**v,'task':first['id']} for k,v in old['deliverables'].items()}
    if old.get('deferred_operations'):raise ValueError('Deferred execution needs its own continuation.')
    return c.plan(result)


def advance_standalone_corrections(state):
    """Atomic local queue admission; workers dispatch only after commit."""
    from . import production_control as pc
    from orchestrator.runtime import Runtime
    if not state.db.execute("SELECT 1 FROM sqlite_master WHERE name='standalone_correction_grants'").fetchone():return
    from orchestrator.storage import transaction
    rt=Runtime(pc.root(state),connection=state.db)
    for grant in state.db.execute('SELECT * FROM standalone_correction_grants WHERE cycle<2 AND error IS NULL').fetchall():
        if rt.status(grant['head'])['status']!='blocked':continue
        with transaction(state.db):
            if state.get('production-control-epoch:'+grant['run'],0)!=grant['epoch'] or (grant['head']!=grant['run'] and state.get('production-control-epoch:'+grant['head'],0)!=0):continue
            baseline=snapshot(state,grant['head'])
            if baseline is None:continue
            if grant['cycle']==0 and hashlib.sha256(encoded(baseline).encode()).hexdigest()!=grant['baseline_hash']:continue
            ident='correction-'+hashlib.sha256((grant['run']+':'+str(grant['cycle']+1)).encode()).hexdigest()[:24]
            try:plan=correction_plan(rt,baseline,ident,grant['request'])
            except ValueError as exc:
                state.db.execute('UPDATE standalone_correction_grants SET error=? WHERE run=?',(str(exc),grant['run']))
                rt.event(grant['head'],None,None,'standalone_correction_needs_recovery',dict(reason=str(exc),user_accepted=False));continue
            rt.create(plan)
            from . import relay_channels
            relay_channels.bind(state,'production',ident,grant['channel'])
            state.put('production-enabled:'+ident,pc.runtime_digest(rt,ident))
            state.db.execute('UPDATE standalone_correction_grants SET head=?,cycle=cycle+1 WHERE run=?',(ident,grant['run']))
            pc.notice(relay_channels.ScopedState(state,grant['channel']),ident,'correction-queued','Queued offline correction and independent review: '+ident+'; prior evidence remains unchanged.')
            rt.event(ident,None,None,'standalone_correction_queued',dict(parent=grant['head'],authorization=grant['request'],baseline=baseline,cycle=grant['cycle']+1,attempts_reset=False,user_accepted=False,channel=grant['channel']))
