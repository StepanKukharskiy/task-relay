"""Pure, versioned connector boundaries over the existing operation registry.

No scheduler, grant store, transport or inferred conversion lives here. The
registry remains authoritative; snapshots bind its definition and the runtime
enforces receipt uncertainty before any result can be collected.
"""
import copy
import hashlib
import json
import re

VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def interface(capability, spec=None):
    from .execution import REGISTRY, parameter_schema, adapter
    if spec is None:spec=REGISTRY[capability]
    if not isinstance(capability,str) or not re.fullmatch(r'[a-z][a-z0-9_.-]*',capability):raise ValueError('Invalid connector identity')
    if type(spec.get('version')) is not int or spec['version']<1:raise ValueError('Connector needs a positive version')
    if spec.get('kind') not in ('api','host','procedure'):raise ValueError('Connector needs an execution kind')
    for key in ('max_inputs','input_bytes','seconds','output_bytes'):
        if type(spec.get(key)) is not int or spec[key]<(1 if key in ('seconds','output_bytes') else 0):raise ValueError('Invalid connector capacity: '+key)
    minimum=spec.get('min_inputs',1)
    if type(minimum) is not int or not 0<=minimum<=spec['max_inputs']:raise ValueError('Invalid connector input cardinality')
    media=spec.get('input_types')
    if not isinstance(media,list) or len(media)!=len(set(media)) or any(not isinstance(m,str) or '/' not in m for m in media):raise ValueError('Invalid connector input media')
    outputs=spec.get('outputs') or ({'*':spec['output_type']} if spec.get('output_type') else {})
    if not outputs or any(not isinstance(p,str) or not isinstance(m,str) or '/' not in m for p,m in outputs.items()):raise ValueError('Connector must declare every output media type')
    for key in ('permissions','cancellation'):
        if not isinstance(spec.get(key),str) or not spec[key].strip():raise ValueError('Connector must declare '+key)
    requests=spec.get('external_requests')
    if 'external_requests' not in spec or requests is not None and (type(requests) is not int or requests<0):raise ValueError('Connector must declare external request capacity, or null for host-owned effects')
    if not isinstance(spec.get('parameters'),dict) or not spec.get('criteria') or any(not isinstance(c,str) or not c for c in spec['criteria']):raise ValueError('Connector needs parameter and validation contracts')
    # Include every execution field, including companion/recovery metadata.
    # UI labels do not change authorization or invalidate saved connector pins.
    # Null external capacity is unknown host-owned scope, never zero or a grant.
    definition=copy.deepcopy(spec)
    definition.pop('node_ui',None)
    wire=parameter_schema(capability) if capability in REGISTRY else None
    admission=adapter(capability).manifest() if capability in REGISTRY else None
    contract=dict(version=VERSION,operation=dict(id=capability,version=spec['version']),
        definition_sha256=digest(dict(definition=definition,parameter_schema=wire,admission=admission)),
        inputs=dict(media_types=list(media),minimum=minimum,maximum=spec['max_inputs'],max_bytes=spec['input_bytes'],
                    registered_versions_required=bool(spec.get('requires_registered_inputs'))),
        outputs=dict(ports=copy.deepcopy(outputs),max_bytes=spec['output_bytes']),
        execution=dict(kind=spec['kind'],seconds=spec['seconds'],external_requests=requests,permissions=spec['permissions']),
        parameters=dict(schema=wire,descriptions=copy.deepcopy(spec['parameters']),bound_validation_required=True),
        admission=admission,
        review=dict(technical_checks=list(spec['criteria']),semantic_acceptance=False),
        recovery=dict(cancellation=spec['cancellation'],unknown_effect='reconcile_without_replay',
                      retry_authority='existing_controller_and_saved_grant'),
        companions=copy.deepcopy(spec.get('companions',{})))
    return contract


def capture(capability):
    """Small immutable reference; full contracts remain in the registry/report."""
    value=interface(capability)
    return {key:value[key] for key in ('version','operation','definition_sha256')}


def verify(capability, captured):
    """Missing snapshots are legacy; a supplied snapshot must match in full."""
    if captured is None:return
    if captured!=capture(capability):raise ValueError('Connector interface changed since capture: '+capability)


def bind(assignment, captured=None):
    """Bind new admissions; never replace a previously captured definition."""
    result=copy.deepcopy(assignment)
    if not result.get('execution'):return result
    capability=result['execution']['capability']
    previous=result.get('connector_interface')
    verify(capability,previous)
    verify(capability,captured)
    result['connector_interface']=copy.deepcopy(previous or captured or capture(capability))
    return result


def edge(source, consumer, *, max_bytes=None, content_contract=None):
    """Classify a port, never claim MIME compatibility proves semantic fit."""
    inputs=consumer['inputs'];reasons=[]
    if source['media_type'] not in inputs['media_types'] or inputs['maximum']==0:
        return dict(status='incompatible',reasons=['input_media_or_cardinality'],runtime_checks=[])
    if max_bytes is not None and max_bytes>inputs['max_bytes']:
        return dict(status='incompatible',reasons=['input_capacity'],runtime_checks=[])
    if content_contract is not None and source.get('content_contract')!=content_contract:
        return dict(status='incompatible',reasons=['content_contract_version'],runtime_checks=[])
    if max_bytes is None:reasons.append('actual_input_bytes')
    if inputs['registered_versions_required']:reasons.append('registered_artifact_versions')
    # Parameters and source evidence may be unknown until preceding work ends.
    # Every direct consumer must still validate its exact bound input bytes.
    reasons.extend(['bound_parameters_and_content','required_input_set','exact_artifact_identity','required_review'])
    return dict(status='requires_runtime_validation',reasons=[],runtime_checks=reasons)


def receipt(value):
    """A common terminal-effect guard for every factory, preserving raw data.

    Adapters still reconcile transport-specific journals. An absent legacy
    certainty field is not upgraded to confirmed; explicit uncertainty always
    takes precedence over a process reporting success or cancellation.
    """
    raw=copy.deepcopy(value)
    def invalid(reason):
        return dict(status='uncertain',reason=reason,
            connector_receipt=dict(version=VERSION,raw_sha256=digest(raw),original=raw,
                effect='uncertain',action='reconcile',acceptance=False,invalid=True))
    if not isinstance(raw,dict):return invalid('Connector receipt must be an object')
    state=raw.get('status')
    # A committed dispatch may still be inside its adapter's bounded startup
    # grace. Observing that state is neither lost-effect evidence nor replay
    # permission; the adapter retains ownership of its deadline/receipt proof.
    if state not in ('launching','running','finished','uncertain'):return invalid('Unsupported connector receipt status')
    pending=raw.get('pending_requests',[])
    if not isinstance(pending,list):return invalid('Connector pending requests must be a list')
    for key in ('browser','computer','operation'):
        if key in raw and not isinstance(raw[key],dict):return invalid('Connector '+key+' receipt must be an object')
    uncertain=(state=='uncertain' or raw.get('external_outcome')=='unknown' or bool(pending)
        or bool(raw.get('browser',{}).get('uncertain_actions')) or bool(raw.get('computer',{}).get('uncertain_actions'))
        or raw.get('operation',{}).get('outcome')=='uncertain')
    normalized=copy.deepcopy(raw)
    if state=='uncertain' and not normalized.get('reason'):
        normalized['reason']='Connector outcome is uncertain; reconcile its receipt without replay.'
    if uncertain and state=='finished':
        normalized.update(status='uncertain',local_terminal=True,
            reason='Terminal process has an unresolved external outcome; reconcile its receipt without replay.')
    normalized['connector_receipt']=dict(version=VERSION,raw_sha256=digest(raw),process_status=state,
        effect='uncertain' if uncertain else 'confirmed' if raw.get('external_outcome')=='no_pending_response' else 'unspecified',
        action='reconcile' if uncertain else 'collect_and_validate' if state=='finished' else 'observe',acceptance=False)
    if normalized.get('reason')!=raw.get('reason') or normalized['status']!=state:normalized['connector_receipt']['original']=raw
    return normalized


def conformance():
    """Inventory and all directed port pairs, without invoking any adapter."""
    from .execution import REGISTRY
    interfaces={key:interface(key) for key in sorted(REGISTRY)};pairs=[]
    for producer,definition in interfaces.items():
        for port,media in definition['outputs']['ports'].items():
            for consumer,target in interfaces.items():
                pairs.append(dict(producer=producer,port=port,consumer=consumer,
                    **edge(dict(media_type=media),target)))
    return dict(version=VERSION,interfaces=interfaces,pairs=pairs,
        limitations=['Directed port compatibility is not complete-workflow or semantic acceptance.',
            'No provider, host application, browser, render or transport was executed.',
            'Recovery eligibility remains owned by existing controller proofs and grants.'])
