"""Join exact, independently reviewed typed partitions. No model or network."""
import hashlib
from . import operation_contracts as c,sourcing_contract as sourcing

OUTPUTS={'delivery/catalog.json':'application/json','delivery/catalog.md':'text/markdown','delivery/source-pack.json':'application/json'}
PARAMETERS={k:'Exact declared input path' for k in ('inventory_path','source_pack_path')}
PARAMETERS.update(max_records='Full inventory ceiling, 1–40',options_per_item='Original option goal',
                  count_policy='Original required or target policy',catalog_paths='Ordered partition JSON input paths',
                  review_paths='Matching independent review JSON input paths')

def build(frozen,read):
    p=frozen['execution']['parameters']
    if (not isinstance(p['catalog_paths'],list) or not isinstance(p['review_paths'],list)
            or not p['catalog_paths'] or len(p['catalog_paths'])!=len(p['review_paths'])):raise ValueError('Each partition needs its exact independent review')
    params={k:p[k] for k in ('inventory_path','source_pack_path','max_records','options_per_item','count_policy')}
    params['summary_path']='delivery/catalog.md'
    params.update({k:p[k] for k in ('field_definitions','identity_field') if k in p})
    first,_=sourcing.bound_json(frozen,p['catalog_paths'][0],read)
    contract=first.get('contract',{})
    family=c.identity(contract)
    from .record_transfers import artifact_parameters,equal_policy
    params.update(artifact_parameters(family,first.get('parameters',{})))
    if c.output_contract(frozen,'delivery/catalog.json')!=contract:
        raise ValueError('Partition content family differs from the registered merge output')
    if family.get('record_role')!='options':raise ValueError('Merge requires a registered record producer')
    f={**frozen,'operation_contract':dict(**contract,parameters=params,output='delivery/catalog.json')}
    ctx=sourcing.context(f,read);records=[];seen=set();proof=[]
    for catalog_path,review_path in zip(p['catalog_paths'],p['review_paths']):
        catalog,sha=sourcing.bound_json(frozen,catalog_path,read)
        review,rsha=sourcing.bound_json(frozen,review_path,read)
        cp=catalog.get('parameters',{});sourcing.parameters(cp)
        if (not equal_policy(family,cp,params)
                or catalog.get('source_versions')!=ctx['source_versions'] or 'record_range' not in cp):raise ValueError('Partition changed source versions, range or policy')
        start,end=cp['record_range'];subset=dict(list(ctx['inventory'].items())[start:end]);part={**ctx,'inventory':subset}
        for record in catalog['records']:sourcing.options_record(record,cp,part)
        if catalog!=sourcing.options_document(catalog['records'],cp,part) or not catalog['complete']:raise ValueError('Partition is not sealed against its exact range')
        judgments=review.get('records',[])
        if (review.get('contract')!=dict(id=family['review_family'],version=contract['version']) or review.get('catalog_sha256')!=sha
                or not review.get('complete') or len(judgments)!=len(subset)
                or {r['item'] for r in judgments}!=set(subset)):raise ValueError('Partition review is incomplete or targets different bytes')
        items={i['id']:i for i in catalog['items']}
        for judgment in judgments:
            sourcing.review_record(judgment,review['parameters'],dict(items=items))
            if judgment['verdict']!='supported':raise ValueError('Unsupported partition cannot be merged as reviewed')
        for record in catalog['records']:
            if record['item'] in seen:raise ValueError('Duplicate inventory item across partitions')
            seen.add(record['item']);records.append(record)
        proof.append(dict(catalog_sha256=sha,review_sha256=rsha,record_range=[start,end]))
    if seen!=set(ctx['inventory']):raise ValueError('Partition coverage differs from the exact full inventory')
    from .collection_core import join
    records=join([records],ctx['inventory'],key=lambda r:r['item'],validate=lambda r:sourcing.options_record(r,params,ctx))
    document=sourcing.options_document(records,params,ctx)
    sourcing.validate_result(document,dict(decision='delivered'))
    raw=(c.encoded(document)+'\n').encode()
    return raw,sourcing.summary(document).encode(),dict(partitions=proof,items=len(records),output_sha256=hashlib.sha256(raw).hexdigest(),acceptance=False)

def execute(frozen,control,read):
    from pathlib import Path
    from .workers import atomic
    raw,summary,validation=build(frozen,read)
    if len(raw)+len(summary)>frozen['limits']['output_bytes']:raise ValueError('Merged catalog exceeds its frozen export capacity')
    source=read(frozen['execution']['parameters']['source_pack_path'])
    if len(raw)+len(summary)+len(source)>frozen['limits']['output_bytes']:raise ValueError('Merged catalog and source pack exceed their frozen export capacity')
    for path,data in zip(OUTPUTS,(raw,summary,source)):
        output=Path(frozen['workspace'])/path;output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as stream:stream.write(data)
    details=dict(outcome='completed',execution=frozen['execution'],validation=validation,
                 output_sha256=hashlib.sha256(raw).hexdigest(),output_bytes=len(raw)+len(summary)+len(source),usage={})
    atomic(Path(control)/'operation.json',details)
    atomic(Path(frozen['workspace'])/'.relay/result.json',dict(assignment_id=frozen['assignment_id'],
        summary='Exact reviewed sourcing partitions merged',decision='delivered',instruction='',
        checks=[dict(criterion=1,passed=True,evidence=c.encoded(validation))]))
    return details
