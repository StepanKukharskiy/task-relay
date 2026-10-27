"""Compact owner decision context from durable metadata; no file reads or dispatch."""
import copy
import json
from . import execution

INSTRUCTIONS='''Finish the exact requested deliverables. Use decision_brief for current inputs,
findings, failures and work routes. Choose a route and bind its required references;
workers inspect full evidence and supply bounded content. Read source passages only
when needed for a decision; use job_catalog for missing contract details.
Code owns paths, hashes, schemas, capacity and required reviewers. Omit outputs for
work, operation, content and review tasks; ordinary workers declare named outputs.
For registered content correction, bind content.baseline and omit parameters;
code inherits immutable choices from that exact eligible saved version. Explicit
conflicts reject. New content still requires its registered semantic choices.
job_delegate yields until workers return. Correct rejected proposals from their
saved diagnostics. Preserve originals and provider, permission and capacity limits.
Never replay uncertain actions. Complete only exact independently reviewed files
and required previews with all findings addressed. Wait only for running work.'''


def routes(grant):
    from .worker_tools import configure
    wanted=set(grant['deliverables'].values());result=[]
    for cap in grant['operations']:
        spec=execution.REGISTRY[cap]
        if not execution.adapter(cap).worker_tool or spec.get('review_evidence'):continue
        formats=set(spec.get('outputs',{}).values())|{spec.get('output_type')}
        for companion in spec.get('companions',{}):
            if companion in grant['operations']:formats.update(execution.REGISTRY[companion].get('outputs',{}).values())
        if not formats&wanted:continue
        intents=[dict(operation=cap,mode=mode) for mode in ('execute','create','revise')] if grant.get('worker_tools_version')==3 else [dict(operation=cap)]
        for intent in intents:
            task=dict(id='route',objective='Prepare requested deliverable',instruction='',inputs=[],dependencies=[],criteria=['Meets the requested outcome'])
            try:
                configure(task,intent,grant)
                from .owner_intents import worker_requirements
                from .owner_compilation import reviewer
                from .worker_capabilities import resolve
                task['worker']=dict(requires=worker_requirements(task))
                judge=reviewer(task,grant)
                for assignment in (task,judge):resolve(assignment,grant['workers'],grant['workers'][0]['backend'])
            except ValueError as exc:
                result.append(dict(operation=cap,**({'mode':intent['mode']} if 'mode' in intent else {}),available=False,reason=str(exc),next_tool='job_catalog'));continue
            result.append(dict(operation=cap,available=True,work=intent,
                produces=sorted(m for m in formats if m),
                content_defaults=copy.deepcopy((task['work_tools']['preparation'] or {}).get('parameters',{})),
                steps=[step['operation'] for step in task['work_tools']['steps'].values()],
                admission='Source compatibility and remaining capacity are checked when delegating; availability is not admission.'))
            if 'mode' in intent:
                from .producer_binding import requirements
                mode=intent['mode']
                result[-1]['required_reference']='baseline' if mode=='revise' else 'data' if mode=='execute' and any(p['selector']=='json' and not p.get('reference_parameter') for p in requirements(cap)) else None
    return result


def build(session,state,findings):
    rt=session.rt;inputs=[];allowed=set(session.grant['inputs'])
    for item in session.frozen['inputs']:
        if item['artifact'] not in allowed:continue
        inputs.append(dict(ref=dict(artifact=item['artifact']),label=item['purpose'],format=item.get('media_type'),
            assessment='Supplied exact evidence; not verified or accepted by this brief'))
    for item in state['artifacts']:
        if item['current'] or item.get('correction_checkpoint'):
            inputs.append(dict(ref=dict(artifact=item['artifact']),label=item['label'],format=item['format'],
                producer_status=item['producer_status'],assessment=item['assessment'],
                **({'correction_checkpoint':copy.deepcopy(item['correction_checkpoint'])} if item.get('correction_checkpoint') else {})))
    visible={i['ref']['artifact'] for i in inputs};issues=[]
    for finding in findings:
        row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(finding['review_attempt'],)).fetchone()
        prior=json.loads(row['frozen']) if row else {}
        refs=[dict(artifact=i['artifact']) for i in prior.get('inputs',[]) if i.get('artifact') in visible]
        issue=finding['issue'];message=issue.get('message',str(issue))
        issues.append(dict(id=finding['id'],message=message[:800],message_truncated=len(message)>800,
            relevant_inputs=refs,assessment='Carried finding; full evidence is bound to correction workers'))
    uncertain=[t['id'] for t in state['tasks'] if t['status']=='uncertain']
    from .job_owner import pending_children
    running=pending_children(rt,session.run,session.frozen['id'])
    if session.pending_submission:next_action='Correct the saved proposal using pending_submission; resubmit job_delegate.'
    elif uncertain:next_action='Resolve uncertain execution from its saved receipt; do not resubmit the effect.'
    elif running:next_action=('Use completed inputs to delegate independent work now. Keep only real data/review dependencies; use job_wait if no useful work can be added.' if session.grant.get('owner_progress_version')==1 else 'Use job_wait for running work; delegate other independent work only if useful.')
    elif issues:next_action='Delegate correction of the carried findings using the relevant existing inputs and a compatible work route.'
    else:next_action=('Delegate independent ready branches together; add only real data/review dependencies. Complete only exact independently reviewed deliverables.' if session.grant.get('owner_progress_version')==1 else 'Delegate the next missing outcome using existing inputs; complete only exact independently reviewed deliverables.')
    from .job_owner import ordinary
    if ordinary(session.grant) and not (running or issues or uncertain or session.pending_submission):
        next_action='Work directly with the available tools; inspect and deliver saved results. Delegate only useful substantial work. Preserve explicit review obligations.'
    return dict(version=1,next_action=next_action,available_inputs=inputs,findings=issues,
        failures=[t for t in state['tasks'] if t.get('failure')],work_routes=routes(session.grant),
        other_registered_operations=list(session.grant['operations']),
        authority='Coordination metadata only. Full evidence remains in exact files; this view does not establish quality or acceptance.')
