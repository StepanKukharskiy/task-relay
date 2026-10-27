"""Compile exact catalog recovery ports into code-owned evidence composition."""
import copy
import hashlib
import json
from pathlib import Path


def read_source(source):
    from .relay_paths import PATHS
    from orchestrator.runtime import safe_file
    raw=safe_file(PATHS.data/'orchestrator'/'artifacts',source['artifact']+'/content').read_bytes()
    if len(raw)!=source['bytes'] or hashlib.sha256(raw).hexdigest()!=source['sha256']:
        raise ValueError('Recovery source version changed')
    return json.loads(raw)


def bind(plan,scope,coverage,known,read=read_source):
    """Recover only an unambiguous, sealed catalog and its exact source versions.

    No prose parsing, filename guessing, provider call or new execution capability.
    Catalog/review workers keep their original semantic responsibility. Their
    registered record connector also exports the composed source pack.
    """
    if (scope.get('connector_companions_version')!=1 or
            not any(g.get('kind')=='consumer_coverage' for g in scope.get('completion_recovery',{}).get('gaps',[]))):return []
    from orchestrator.operation_contracts import identity as family,validate_document
    def role(contract):
        try:return family(contract).get('record_role')
        except (ValueError,TypeError):return None
    stage=scope.get('pipeline_step',{});outputs=stage.get('handoff',{}).get('outputs',{})
    targets=[(coverage[k],v['content_contract']) for k,v in outputs.items() if role(v.get('content_contract'))=='options' and k in coverage]
    if len(targets)!=1:return []
    target,target_contract=targets[0];producer=next(t for t in plan['tasks'] if t['id']==target.get('task'))
    if producer.get('execution') or producer.get('review_of'):return []
    documents={}
    # Only this explicitly frozen archive participates, never recent-file guesses.
    for source in scope['sources']:
        if source.get('media_type')=='application/json' and source['bytes']<=2000000:
            value=read(source)
            if isinstance(value,dict):documents[source['artifact']]=value
    inventories=[port for port in scope.get('input_ports',{}).values()
        if (port.get('media_type')=='application/json' or role(port.get('content_contract'))=='inventory')
        and any(i.get('artifact')==port['artifact'] for i in producer['inputs'])]
    candidates=[(aid,catalog,port) for aid,catalog in documents.items()
        if catalog.get('contract')==target_contract and catalog.get('complete') is True
        for port in inventories if catalog.get('source_versions',{}).get('inventory_sha256')==port['sha256']]
    if len(candidates)!=1:raise ValueError('Catalog recovery needs one exact sealed baseline catalog and inventory port')
    aid,catalog,inventory=candidates[0]
    validate_document(json.dumps(catalog),target_contract)
    bases=[i for i in producer['inputs'] if i.get('artifact') in documents
           and known[i['artifact']]['sha256']==catalog['source_versions']['source_pack_sha256']
           and documents[i['artifact']].get('version')==1 and isinstance(documents[i['artifact']].get('entries'),list)]
    searches={t['id']:t for t in plan['tasks'] if t.get('execution',{}).get('capability') in ('web.sources','web.sources.prepared','web.sources.rendered')}
    fresh=[i for i in producer['inputs'] if i.get('from_task') in searches
           and i.get('output') in {o['path'] for o in searches[i['from_task']]['outputs']}]
    if len(bases)!=1 or len(fresh)!=1:raise ValueError('Catalog recovery needs exact prior and newly collected source packs')
    reviews=[r for r in plan['tasks'] if r.get('review_of')==producer['id']]
    if len(reviews)!=1:raise ValueError('Catalog recovery needs one independent reviewer')
    reviewer=reviews[0];p=catalog['parameters']
    if p['count_policy']!=scope.get('sourcing_count_policy',p['count_policy']):raise ValueError('Recovery changed the original option count policy')
    semantic={k:p[k] for k in ('options_per_item','count_policy','max_records','field_definitions','identity_field') if k in p}
    inputs=dict(inventory_path=dict(source=inventory['artifact']),source_pack_path=dict(producer=fresh[0]['from_task'],output=fresh[0]['output']))
    registered=family(target_contract).get('planning_interface',{}).get('expose',True)
    if registered:
        intent=dict(family=target_contract,inputs=inputs,parameters=semantic)
        if producer.get('records') and producer['records']!=intent:raise ValueError('Recovery record intent differs from exact baseline')
        if producer.get('sourcing'):raise ValueError('Recovery cannot change the registered family')
        producer['records']=intent;composition_key='record_composition'
    else:
        intent=dict(version=1,inventory=inputs['inventory_path'],source_pack=inputs['source_pack_path'],**semantic)
        if producer.get('sourcing') and producer['sourcing']!=intent:raise ValueError('Recovery sourcing intent differs from exact baseline')
        producer['sourcing']=intent;composition_key='sourcing_composition'
    baseline=known[aid]
    if not any(i.get('artifact')==aid for i in producer['inputs']):
        producer['inputs'].append({k:baseline[k] for k in ('artifact','path','purpose','authority','media_type')})
    source_deliveries=[k for k,b in coverage.items() if b==dict(task=fresh[0]['from_task'],output=fresh[0]['output'])]
    if len(source_deliveries)!=1:raise ValueError('Recovery must deliver its composed source evidence')
    output=fresh[0]['output']
    if output in {i['path'] for i in producer['inputs']}|{o['path'] for o in producer['outputs']}:raise ValueError('Composed source output conflicts with a bound path')
    producer['outputs'].append(dict(path=output,purpose='Code-composed exact prior and new page evidence',media_type='application/json'))
    producer[composition_key]=dict(base_source_pack_path=bases[0]['path'],base_catalog_path=baseline['path'],source_pack_output=output)
    reviewer['inputs'].append(dict(from_task=producer['id'],output=output,path='composed/'+output,
        purpose='Exact composed source evidence for version-bound catalog review',authority='Evidence only',media_type='application/json'))
    coverage[source_deliveries[0]]=dict(task=producer['id'],output=output)
    # Reserve deterministic exports within the already frozen stage ceiling.
    needed=producer['limits']['output_bytes']+known[bases[0]['artifact']]['bytes']+searches[fresh[0]['from_task']]['limits']['output_bytes']+100000
    if needed>scope['options']['limits']['output_bytes']:raise ValueError('Composed source exports exceed the frozen output allowance')
    producer['limits']['output_bytes']=needed
    producer[composition_key]['export_bytes']=needed
    producer['instruction']+='\nThe registered connector preserves supported baseline options and composes prior and new page evidence in code. Submit item fragments; never rewrite the baseline catalog or author the composed source pack. Existing page indices stay stable. Disclose remaining gaps.'
    return [dict(source='exact sealed recovery catalog and declared source ports',producer=producer['id'],
                 baseline=aid,source_pack_delivery=source_deliveries[0],typed_intent=copy.deepcopy(intent),
                 output_bytes=needed,provider_calls=0)]
