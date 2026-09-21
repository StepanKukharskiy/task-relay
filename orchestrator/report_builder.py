"""Assignment-owned report forms; the worker supplies judgments and evidence only."""
import copy

INSTRUCTIONS='''Use report_contract.schema for the final report/finish call. Fill the
named checks slots with passed and evidence, using null only for checks you could
not perform when decision is blocked. Relay binds assignment identity and criterion
numbers. Do not include assignment_id or criterion fields in this form. Decision,
summary, revision instruction and findings are your independent judgments. Never
claim acceptance from structure alone. For completed source-fidelity observations,
use the typed evidence object in its designated slot. This replaces earlier JSON-
encoded-string formatting instructions only; keep all independent inspection,
units, transforms, entity, source/candidate comparison and measurement requirements.
In the typed object: sources are keyed by s1, s2, etc.; each needs the
independently observed file hash and observation. Measurements are keyed by the
frozen metric names and need actual error and evidence. Relay fills the identity
list; missing measurements are never zero. If unable to inspect/measure, report
blocked and explain the limitation in text evidence.'''


def schema(frozen):
    from task_relay.planning_contract import obj
    from . import outcomes
    text={'type':'string'}
    checks={}
    policy=frozen.get('source_fidelity')
    for index,criterion in enumerate(frozen['criteria'],1):
        evidence=text
        if policy and index==policy['criterion']:
            observations=obj({'s'+str(i):obj({'observed_sha256':text,'observation':text},('observed_sha256','observation'))
                              for i,_ in enumerate(policy['sources'],1)},['s'+str(i) for i in range(1,len(policy['sources'])+1)])
            props={'sources':observations}
            if policy['phase']=='comparison':
                props['measurements']=obj({m['metric']:obj({'error':{'type':'number'},'evidence':text},('error','evidence'))
                    for m in policy['checks']},[m['metric'] for m in policy['checks']])
            evidence={'anyOf':[text,obj(props,props)]}
        checks['c'+str(index)]={'anyOf':[obj({'passed':{'type':'boolean'},'evidence':evidence},('passed','evidence')),
                                        {'type':'null'}], 'description':criterion}
    return obj({'summary':text,'decision':{'type':'string','enum':['accept','revise','blocked'] if frozen.get('review_of') else ['delivered','blocked']},
                'instruction':text,'findings':copy.deepcopy(outcomes.SCHEMA),'checks':obj(checks,checks)},
               ('summary','decision','instruction','findings','checks'))


def freeze(frozen):
    return dict(version=1,schema=schema(frozen),
                source_slots={'s'+str(i):copy.deepcopy(s) for i,s in enumerate(frozen.get('source_fidelity',{}).get('sources',[]),1)})


def build(value,frozen):
    from task_relay.planning_contract import validate
    from . import contracts as c
    policy=frozen.get('report_contract')
    if not policy or policy.get('version')!=1:raise ValueError('Typed report requires a frozen supported report contract.')
    if policy!=freeze(frozen):raise ValueError('Frozen report form differs from its assignment.')
    validate(value,policy['schema'])
    result={k:copy.deepcopy(value[k]) for k in ('summary','decision','instruction','findings')}
    result.update(assignment_id=frozen['assignment_id'],checks=[])
    for index in range(1,len(frozen['criteria'])+1):
        detail=value['checks']['c'+str(index)]
        if detail is None:
            if result['decision']!='blocked':raise ValueError('Unchecked criteria require a blocked decision.')
            continue
        evidence=detail['evidence']
        if isinstance(evidence,dict):
            fidelity=frozen['source_fidelity'];observations={}
            for key,source in policy['source_slots'].items():
                observation=evidence['sources'][key]
                if observation['observed_sha256']!=source['sha256']:
                    raise ValueError('Observed source hash differs from the frozen source version.')
                c.nonempty(observation['observation'],'source observation')
                observations[source['artifact']]=observation['observation']
            data=dict(sources=copy.deepcopy(fidelity['sources']),source_observations=observations)
            if fidelity['phase']=='comparison':
                from .source_fidelity import number
                measurements=evidence['measurements']
                if any(not number(m['error']) for m in measurements.values()):raise ValueError('Source measurement must be finite and nonnegative.')
                for measurement in measurements.values():c.nonempty(measurement['evidence'],'measurement evidence')
                data['comparisons']=[dict(metric=m['metric'],**measurements[m['metric']]) for m in fidelity['checks']]
            evidence=c.encoded(data)
        result['checks'].append(dict(criterion=index,passed=detail['passed'],evidence=evidence))
    # Caller applies canonical role, fidelity and outcome validation.
    return result
