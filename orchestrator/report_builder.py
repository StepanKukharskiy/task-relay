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
blocked and explain the limitation in text evidence. For report contract v3,
source-verification evidence uses candidate_ref and source_ref from artifact_slots.
Use the mapped path to read the file; do not construct a path or supply a hash in
the report. Relay resolves the reference to its frozen artifact version. Exact
claim/quote excerpts and independent judgments remain required.'''


def artifact_bindings(frozen):
    """Assignment-local references; identity/version and staging remain Relay-owned."""
    return {'i'+str(index):{key:item[key] for key in ('artifact','sha256','path')}
            for index,item in enumerate(frozen.get('inputs',[]),1)
            if all(item.get(key) for key in ('artifact','sha256','path'))}


def schema(frozen, *, scoped_paths=True, artifact_refs=False):
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
        if index in frozen.get('source_verification',{}).get('criteria',[]):
            from .source_verification import schema as source_schema
            evidence={'anyOf':[text,source_schema(frozen if scoped_paths else None,artifact_refs=artifact_refs)]}
        if str(index) in frozen.get('final_quality',{}).get('checks',{}):
            from .final_quality import schema as quality_schema
            evidence=quality_schema(frozen,index)
        if index==frozen.get('review_followup',{}).get('criterion'):
            from .review_followup import schema as followup_schema
            evidence=followup_schema(frozen)
        checks['c'+str(index)]={'anyOf':[obj({'passed':{'type':'boolean'},'evidence':evidence},('passed','evidence')),
                                        {'type':'null'}], 'description':criterion}
        if scoped_paths and index in frozen.get('source_verification',{}).get('criteria',[]):
            # A factual pass uses typed paths; text is only a failed-check explanation.
            checks['c'+str(index)]['anyOf']=[
                obj({'passed':{'type':'boolean','enum':[True]},'evidence':source_schema(frozen,artifact_refs=artifact_refs)},('passed','evidence')),
                obj({'passed':{'type':'boolean','enum':[False]},'evidence':evidence},('passed','evidence')),
                {'type':'null'}]
    return obj({'summary':text,'decision':{'type':'string','enum':['accept','revise','blocked'] if frozen.get('review_of') else ['delivered','blocked']},
                'instruction':text,'findings':copy.deepcopy(outcomes.SCHEMA),'checks':obj(checks,checks)},
               ('summary','decision','instruction','findings','checks'))


def freeze(frozen, *, version=None):
    bindings=artifact_bindings(frozen)
    policy=frozen.get('source_verification',{})
    required=set(policy.get('candidates',[])+policy.get('sources',[]))
    available={b['path'] for b in bindings.values()}
    version=version or frozen.get('report_contract',{}).get('version',3 if required and required<=available else 2)
    if version>=3 and not required<=available:raise ValueError('Artifact-reference reports require every declared evidence input to be bound.')
    result=dict(version=version,schema=schema(frozen,scoped_paths=version>=2,artifact_refs=version>=3),
                source_slots={'s'+str(i):copy.deepcopy(s) for i,s in enumerate(frozen.get('source_fidelity',{}).get('sources',[]),1)})
    if version>=3:result['artifact_slots']=bindings
    return result


def build(value,frozen):
    from task_relay.planning_contract import validate
    from . import contracts as c
    policy=frozen.get('report_contract')
    if not policy or policy.get('version') not in (1,2,3):raise ValueError('Typed report requires a frozen supported report contract.')
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
            if str(index) in frozen.get('final_quality',{}).get('checks',{}) or index==frozen.get('review_followup',{}).get('criterion'):
                result['checks'].append(dict(criterion=index,passed=detail['passed'],evidence=c.encoded(evidence)))
                continue
            if index in frozen.get('source_verification',{}).get('criteria',[]):
                if policy['version']>=3:
                    evidence=copy.deepcopy(evidence)
                    for claim in evidence['claims']:
                        candidate=policy['artifact_slots'][claim.pop('candidate_ref')]
                        claim['candidate_path']=candidate['path']
                        for support in claim['supports']:
                            source=policy['artifact_slots'][support.pop('source_ref')]
                            support.update(path=source['path'],sha256=source['sha256'])
                evidence=c.encoded(evidence)
                result['checks'].append(dict(criterion=index,passed=detail['passed'],evidence=evidence))
                continue
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
