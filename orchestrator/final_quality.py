"""Final-deliverable review obligations over the existing report and correction loop.

The compiler owns output identity and requested criteria. Reviewers supply small
semantic judgments; code rejects missing coverage, failed dimensions disguised
as advisories, and citations outside the frozen input versions. A semantic pass
is still a model judgment, not user acceptance or a guarantee of truth.
"""
import copy
import hashlib
import json

DIMENSIONS=('requirements','reference_fit','evidence','usability')
INSTRUCTIONS='''The final_quality contract reviews the actual delivered version against
its frozen requested outcome, not just successful execution or an earlier review.
For each bound outcome supply all four dimensions. requirements: requested content
and constraints; reference_fit: suitability against supplied visual/text references,
including color, material, texture, scale and function when relevant; evidence:
material factual claims, variant, currency/units, freshness and uncertainty; usability:
read the actual artifact and rendered pages, looking for concatenated fields, raw
source/JSON-LD leakage, truncation, overlap and unreadable or misleading content.
A disclosed difference is not automatically a suitable recommendation. Reject an
option that fails the brief, even if its identity/photo is correct. Missing target
coverage can be a disclosed_gap only when the frozen policy permits it. Never
present a gap or unsupported current purchasing fact as verified or client-ready.
Use defect for repairable failures and return revise with concrete corrections;
do not turn these into subjective quality/approval findings. not_applicable needs
a reason and is unavailable for required dimensions. Cite exact declared paths
and precise locations (page/slide/item/section) actually inspected. Usability must
include every bound inspection_inputs artifact from registered review companions. Evidence is
about the candidate version; do not repeat deterministic checks already supplied.
Prior acceptance, file creation and generic disclaimers are not final quality proof.'''


def criterion(ident):return 'Final delivery quality for '+ident+': independently verify request fulfillment, reference fit, factual support and artifact usability.'


def bind(plan,coverage,contract,*,target_gaps=False):
    from task_relay.request_contract import slots
    required=slots(contract) if contract else {}
    receipts=[]
    from .execution import REGISTRY
    tasks={t['id']:t for t in plan['tasks']}
    for ident,binding in coverage.items():
        item=required.get(ident)
        if not item or item['kind']!='file' or set(binding)!={'task','output'}:continue
        for task in plan['tasks']:
            if task.get('review_of')!=binding['task']:continue
            candidate=next((i for i in task['inputs'] if i.get('from_task')==binding['task'] and i.get('output')==binding['output']),None)
            if candidate is None:raise ValueError('Final quality requires the exact delivered output in its reviewer inputs')
            inspections=[i['path'] for i in task['inputs']
                if REGISTRY.get(tasks.get(i.get('from_task'),{}).get('execution',{}).get('capability'),{}).get('review_evidence')
                and any(source.get('from_task')==binding['task'] and source.get('output')==binding['output']
                        for source in tasks[i['from_task']]['inputs'])]
            local=tasks.get(binding['task'],{}).get('work_tools',{}).get('steps',{}).get('inspect',{})
            local_paths={o['path'] for o in local.get('outputs',{}).values()}
            inspections += [i['path'] for i in task['inputs'] if i.get('from_task')==binding['task'] and i.get('output') in local_paths]
            policy=task.setdefault('final_quality',dict(version=1,checks={}))
            label=criterion(ident)
            if label not in task['criteria']:task['criteria']=[*task['criteria'],label]
            index=str(task['criteria'].index(label)+1)
            policy['checks'][index]=dict(outcome=copy.deepcopy(item),candidate=candidate['path'],
                target_gaps=bool(target_gaps),inspection_inputs=inspections,reference_required=any(i.get('visual_reference') for i in task['inputs']))
            receipts.append(dict(reviewer=task['id'],outcome=ident,candidate=candidate['path'],criterion=int(index)))
            task['instruction']+='\n'+INSTRUCTIONS
    return receipts


def validate_assignment(task):
    policy=task['final_quality']
    if not task.get('review_of') or set(policy)!={'version','checks'} or policy['version']!=1 or not policy['checks']:
        raise ValueError('Invalid final quality review contract')
    inputs={i['path']:i for i in task['inputs']}
    from task_relay.request_contract import validate
    for number,binding in policy['checks'].items():
        if set(binding)!={'outcome','candidate','target_gaps','reference_required','inspection_inputs'}:raise ValueError('Invalid final quality binding')
        item=binding['outcome'];validate(dict(mode='new_work',reason='Frozen final outcome',outcomes=[item]))
        if (not number.isdigit() or not 1<=int(number)<=len(task['criteria']) or task['criteria'][int(number)-1]!=criterion(item['id'])
            or type(binding['target_gaps']) is not bool or type(binding['reference_required']) is not bool
            or not isinstance(binding['inspection_inputs'],list) or any(p not in inputs for p in binding['inspection_inputs'])
            or binding['candidate'] not in inputs or inputs[binding['candidate']].get('from_task')!=task['review_of']):
            raise ValueError('Final quality must bind exact criteria and candidate inputs')


def schema(frozen,number):
    from task_relay.planning_contract import obj,array
    binding=frozen['final_quality']['checks'][str(number)]
    text={'type':'string','minLength':1,'maxLength':1200}
    location=obj({'path':{'type':'string','enum':[i['path'] for i in frozen['inputs']]},'location':text},('path','location'))
    dimensions={}
    for name in DIMENSIONS:
        statuses=['satisfied','defect']
        if name in ('evidence','reference_fit') and not (name=='reference_fit' and binding['reference_required']):statuses.append('not_applicable')
        if name=='requirements' and binding['target_gaps']:statuses.append('disclosed_gap')
        dimensions[name]=obj({'verdict':{'type':'string','enum':statuses},'reason':text,
            'inspected':{**array(location),'minItems':1,'maxItems':8}},('verdict','reason','inspected'))
    return obj(dimensions,dimensions)


def validate_report(report,frozen):
    if not frozen.get('final_quality'):return
    validate_assignment(frozen)
    from task_relay.planning_contract import validate
    from .runtime import safe_file
    checks={str(c['criterion']):c for c in report['checks']};inputs={i['path']:i for i in frozen['inputs']};verified=set()
    for number,binding in frozen['final_quality']['checks'].items():
        check=checks.get(number)
        if check is None:
            if report['decision']=='blocked':continue
            raise ValueError('Final quality requires every bound outcome')
        try:value=json.loads(check['evidence']);validate(value,schema(frozen,int(number)))
        except (ValueError,TypeError):raise ValueError('Final quality needs structured dimension judgments, not a blanket acceptance') from None
        defective=any(v['verdict']=='defect' for v in value.values())
        if defective and (check['passed'] or report['decision']=='accept'):
            raise ValueError('Final quality defects require revise or blocked, never advisory acceptance')
        if not any(ref['path']==binding['candidate'] for ref in value['usability']['inspected']):
            raise ValueError('Usability review must inspect the actual delivered candidate')
        if not set(binding['inspection_inputs']).issubset(ref['path'] for ref in value['usability']['inspected']):
            raise ValueError('Usability review must inspect the exact registered review evidence')
        if binding['reference_required'] and value['reference_fit']['verdict']=='satisfied':
            references={i['path'] for i in inputs.values() if i.get('visual_reference')}
            if not references.intersection(r['path'] for r in value['reference_fit']['inspected']):
                raise ValueError('Reference fit must inspect the supplied visual reference')
        for detail in value.values():
            for ref in detail['inspected']:
                path=ref['path']
                if path in verified:continue
                raw=safe_file(frozen['workspace'],path).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=inputs[path].get('sha256'):
                    raise ValueError('Final quality evidence changed from its frozen version')
                verified.add(path)
