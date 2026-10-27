"""Bounded targeted discovery from exact reviewed catalog shortfalls."""
import hashlib,json,re
from . import operation_contracts as c,sourcing_contract as sourcing,web_sources

def specification(catalog,pack):
    """Domain qualification rules feed the common coverage/fallback engine."""
    if c.identity(catalog.get('contract',{})).get('record_role')!='options' or not catalog.get('complete'):raise ValueError('Coverage discovery requires a sealed typed catalog')
    from .collection_core import coverage,fallback_queries
    targets=pack.get('query_specification',{}).get('data',{}).get('targets',[])
    by_id={i['id']:i for i in catalog['items']}
    def qualified(option):
        fields=option['fields']
        if catalog['parameters'].get('field_definitions'):
            return fields[sourcing.identity_field(catalog['parameters'])].get('status')=='observed'
        return (fields['price'].get('status')=='observed'
                and (fields['price'].get('currency')=='USD' or re.search(r'\bUSD\b|\bUS\s*\$',fields['price'].get('excerpt','')))
                and fields['us_context'].get('status')=='observed')
    states=[]
    for target in targets:
        if target['id'] not in by_id:raise ValueError('Source query target is absent from the reviewed catalog')
        if catalog['parameters'].get('selection_policy')=='visual':
            from .visual_selection import counts
            value=counts(by_id[target['id']]['options'],target['required_options'])
            states.append(dict(item=target['id'],supported_options=value['suitable'],goal=target['required_options'],shortfall=value['shortfall']))
        else:states.extend(coverage([target],[by_id[target['id']]],target['required_options'],qualified))
    # Exclude observed unsuccessful publishers only when the request permits
    # unrestricted public research. Exact reviewed queries and domain allowlists
    # stay authoritative; exclusions diversify discovery, never manufacture URLs.
    avoid={}
    if not pack.get('domains'):
        for entry in pack['entries']:
            hosts=[]
            for read in entry.get('retrievals',[]):
                host=read.get('publisher','')
                if read.get('outcome')=='failed' and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}',host):hosts.append(host)
            for ident in entry.get('target_ids',[]):avoid.setdefault(ident,[]).extend(h for h in hosts if h not in avoid.get(ident,[]))
    result=fallback_queries(targets,states,[e.get('query','') for e in pack['entries']],avoid=avoid,suffix=' public source detailed information' if catalog['parameters'].get('field_definitions') else ' US retailer buy online current price')
    spec=dict(version=1,targets=result)
    if result:web_sources.validate_prepared(spec)
    return spec,states

def collect(frozen,read,control,config):
    p=frozen['execution']['parameters']
    catalog,csha=sourcing.bound_json(frozen,p['catalog_path'],read)
    pack,psha=sourcing.bound_json(frozen,p['source_pack_path'],read)
    if catalog.get('source_versions',{}).get('source_pack_sha256')!=psha:raise ValueError('Coverage discovery catalog and source-pack versions differ')
    spec,states=specification(catalog,pack)
    if spec['targets']:
        queries=web_sources.validate_prepared(spec)
        prepared=dict(path='code-owned-coverage-queries.json',sha256=c.digest(spec),data=spec)
        raw,validation=web_sources.collect(queries,p['domains'],p['model'],control,config,prepared_spec=prepared)
        out=json.loads(raw)
    else:
        out=dict(version=1,kind='public_source_candidates',entries=[],domains=p['domains'],model=p['model'],
            interpretation='No new discovery needed or no unused mapped subject query remains; preserved base evidence is required.')
        validation=dict(queries=0,grounded=0,fetched=0,unresolved=0)
    out['coverage_recovery']=dict(version=1,catalog_sha256=csha,source_pack_sha256=psha,targets=states,
        query_specification=spec,maximum_rounds=1,interpretation='Candidate coverage only; new alternatives require exact-span catalog construction and independent semantic review. Remaining gaps may be delivered only under target policy.')
    return c.encoded(out),validation|dict(coverage=states)
