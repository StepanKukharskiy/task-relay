"""Source-bound sourcing fragments and independent item-review checkpoints.

Code extracts values and builds files. Agents select source spans and make semantic
judgments. A captured value is neither a purchasing guarantee nor user acceptance.
"""
import hashlib
import json
import re

from . import product_evidence as evidence

FAMILIES = ('sourcing.options', 'sourcing.review')
FIELDS = ('name_variant', 'price', 'dimensions', 'order_terms', 'us_context')

def field_rules(params):
    return params.get('field_definitions',{k:('price' if k=='price' else 'text') for k in FIELDS})

def identity_field(params):return params.get('identity_field','name_variant')

def is_review(contract):
    from .operation_contracts import identity
    return identity({k:contract[k] for k in ('id','version')}).get('record_role')=='review'

def family_id(contract,review=False):
    from .operation_contracts import identity
    family=identity({k:contract[k] for k in ('id','version')})
    return family['review_family' if review else 'producer_family']

def capture(ctx,params,field,observation,span):
    if ctx['observations'].get(observation,{}).get('discovery'):
        if params.get('selection_policy')!='visual' or field!=identity_field(params):
            raise ValueError('Discovery evidence identifies visual leads only; buying details remain unknown')
    result=evidence.capture(ctx['journal'],dict(field='price' if field_rules(params)[field]=='price' else 'name_variant',
        observation=observation,start=span['start'],end=span['end']))
    result['field']=field
    return result
SEMANTIC_CRITERION = 'Every sourcing item has an independent version-bound semantic review; unsupported or uncertain judgments cannot be accepted.'

def obj(properties, required=None):
    return dict(type='object', properties=properties,
                required=list(properties) if required is None else required, additionalProperties=False)

STRING = {'type':'string'}
SPAN = {'anyOf':[
    obj({'status':{'type':'string','enum':['observed']}, 'start':{'type':'integer'}, 'end':{'type':'integer'}}),
    obj({'status':{'type':'string','enum':['unknown']}, 'reason':{'type':'string','maxLength':300}})]}
OPTION_SCHEMA = obj({'observation':STRING, 'fields':obj({k:SPAN for k in FIELDS}),
                     'comparison':{'type':'string','maxLength':600}})
OPTIONS_SCHEMA = obj({'item':STRING, 'options':{'type':'array','maxItems':10,'items':OPTION_SCHEMA},
                      'gap':{'type':'string','maxLength':600}})

def options_schema(params):
    option={
        'observation':STRING,'fields':obj({k:SPAN for k in field_rules(params)}),
        'comparison':{'type':'string','maxLength':600}}
    if params.get('selection_policy')=='visual':
        from .visual_selection import SCHEMA
        option['selection']=SCHEMA
    return obj({'item':STRING,'options':{'type':'array','maxItems':10,'items':obj(option)},'gap':{'type':'string','maxLength':600}})
REVIEW_SCHEMA = obj({'item':STRING, 'item_sha256':STRING,
                     'verdict':{'type':'string','enum':['supported','unsupported','uncertain']},
                     'reason':{'type':'string','maxLength':1000}})

def bounded_text(value, limit, *, empty=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):
        raise ValueError('Expected bounded sourcing text')

def parameters(value, review=False):
    from . import operation_contracts as c
    keys=('inventory_path','source_pack_path','max_records','summary_path')
    keys+=('catalog_path',) if review else ('options_per_item','count_policy')
    if not review and 'selection_policy' in value:
        keys+=('selection_policy',)
        if value['selection_policy']!='visual':raise ValueError('Unknown selection policy')
    composition=('base_source_pack_path','base_catalog_path','source_pack_output')
    if not review and any(k in value for k in composition):keys+=composition
    if 'record_range' in value:keys+=('record_range',)
    if 'field_definitions' in value or 'identity_field' in value:
        keys+=('field_definitions','identity_field')
        rules=value.get('field_definitions')
        if (not isinstance(rules,dict) or not 1<=len(rules)<=12
                or any(not isinstance(k,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',k)
                       or v not in ('text','price') for k,v in rules.items())
                or value.get('identity_field') not in rules):raise ValueError('Invalid registered field definitions or identity field')
    if not review and 'allow_baseline_amend' in value:
        keys+=('allow_baseline_amend',)
        if value['allow_baseline_amend'] is not True:raise ValueError('Invalid prospective baseline correction policy')
    if not review and 'resume_checkpoint' in value:
        keys+=('resume_checkpoint',)
        proof=value['resume_checkpoint']
        c.fields(proof,('version','attempt','baseline','source','parent','record_range','frozen_sha256','receipt_sha256',
            'result_sha256','unresolved_findings','revision','records_sha256','outputs','acceptance'))
        if proof['version']!=1 or proof['acceptance'] is not False or not isinstance(proof['unresolved_findings'],list):
            raise ValueError('Invalid checkpoint continuation policy')
    c.fields(value,keys)
    from .contracts import relative
    for k in keys:
        if k.endswith('_path') or k=='source_pack_output': relative(value[k])
    if type(value['max_records']) is not int or not 1<=value['max_records']<=40:
        raise ValueError('Sourcing record ceiling must be 1–40')
    if 'record_range' in value:
        bounds=value['record_range']
        if (not isinstance(bounds,list) or len(bounds)!=2 or any(type(n) is not int for n in bounds)
                or not 0<=bounds[0]<bounds[1]<=value['max_records']):raise ValueError('Invalid code-owned sourcing record range')
    if not review and (type(value['options_per_item']) is not int or not 1<=value['options_per_item']<=10
                       or value['count_policy'] not in ('required','target')):
        raise ValueError('Invalid sourcing option count policy')

def options_record(value, params, context=None):
    from . import operation_contracts as c
    c.fields(value,('item','options','gap'));bounded_text(value['item'],80)
    bounded_text(value['gap'],600,empty=True)
    if not isinstance(value['options'],list) or len(value['options'])>10:
        raise ValueError('Sourcing item supports zero to ten options')
    identities=[]
    if context is not None and value['item'] not in context['inventory']:
        raise ValueError('Foreign sourcing inventory item')
    for option in value['options']:
        c.fields(option,('observation','fields','comparison')+(('selection',) if params.get('selection_policy')=='visual' else ()));bounded_text(option['observation'],160)
        if params.get('selection_policy')=='visual':
            from .visual_selection import validate
            validate(option['selection'])
        bounded_text(option['comparison'],600,empty=True);c.fields(option['fields'],field_rules(params))
        for field,span in option['fields'].items():
            if not isinstance(span,dict):raise ValueError('Sourcing field needs observed span or explicit unknown')
            if span.get('status')=='unknown':
                c.fields(span,('status','reason'));bounded_text(span['reason'],300)
            elif span.get('status')=='observed':
                c.fields(span,('status','start','end'))
                if type(span['start']) is not int or type(span['end']) is not int or not 0<=span['start']<span['end'] or span['end']-span['start']>4000:
                    raise ValueError('Invalid sourcing evidence span')
                if context is not None:
                    capture(context,params,field,option['observation'],span)
            else:raise ValueError('Unknown sourcing field status')
        if option['fields'][identity_field(params)]['status']!='observed':
            raise ValueError('An option needs observed product identity; record unresolved items as gaps')
        if context is not None:
            from urllib.parse import urlsplit
            page=urlsplit(context['observations'][option['observation']]['url'])
            identities.append((page.hostname.lower(),page.path.rstrip('/')))
    if len(set(identities))!=len(identities):raise ValueError('Duplicate product URL in sourcing item')
    return value['item']

def review_record(value, params, context=None):
    from . import operation_contracts as c
    c.fields(value,('item','item_sha256','verdict','reason'));bounded_text(value['item'],80)
    if not isinstance(value['item_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['item_sha256']):
        raise ValueError('Invalid sourcing item version')
    if value['verdict'] not in ('supported','unsupported','uncertain'):raise ValueError('Unknown sourcing verdict')
    bounded_text(value['reason'],1000)
    if context is not None:
        item=context['items'].get(value['item'])
        if item is None or c.digest(item)!=value['item_sha256']:raise ValueError('Sourcing review targets a different item version')
    return value['item']

def bound_json(frozen, path, read):
    matches=[i for i in frozen['inputs'] if i['path']==path]
    if len(matches)!=1 or not matches[0].get('sha256'):raise ValueError('Missing frozen sourcing input')
    raw=read(path)
    if hashlib.sha256(raw).hexdigest()!=matches[0]['sha256']:raise ValueError('Frozen sourcing input changed')
    from .research_quality import load_json
    value=load_json(raw)
    if not isinstance(value,dict):raise ValueError('Sourcing inputs must contain JSON objects')
    return value,matches[0]['sha256']

def context(frozen, read):
    if frozen['operation_contract']['id']=='sourcing.inventory':
        from .sourcing_inventory import context as inventory_context
        return inventory_context(frozen,read)
    contract=frozen['operation_contract'];p=contract['parameters'];review=is_review(contract)
    parameters(p,review)
    inventory,inv_sha=bound_json(frozen,p['inventory_path'],read)
    source_pack,source_sha=bound_json(frozen,p['source_pack_path'],read)
    baseline=None;composed=None
    if not review and p.get('source_pack_output'):
        base,base_sha=bound_json(frozen,p['base_source_pack_path'],read)
        baseline,_=bound_json(frozen,p['base_catalog_path'],read)
        original={k:v for k,v in p.items() if k not in ('base_source_pack_path','base_catalog_path','source_pack_output')}
        original.pop('record_range',None)
        original.pop('resume_checkpoint',None)
        original['source_pack_path']=p['base_source_pack_path']
        base_frozen={**frozen,'operation_contract':{**contract,'parameters':original}}
        base_ctx=context(base_frozen,read)
        bp=baseline.get('parameters',{})
        parameters(bp)
        if bp.get('record_range'):
            start,end=bp['record_range'];base_ctx={**base_ctx,'inventory':dict(list(base_ctx['inventory'].items())[start:end])}
        if (baseline.get('contract')!=dict(id=family_id(contract),version=1) or not baseline.get('complete')
                or baseline.get('source_versions')!=base_ctx['source_versions']
                or any(bp.get(k)!=p.get(k) for k in ('count_policy','options_per_item','max_records','field_definitions','identity_field','selection_policy'))):
            raise ValueError('Recovery baseline is not the exact sealed source-bound catalog')
        for record in baseline['records']:options_record(record,bp,base_ctx)
        if baseline!=options_document(baseline['records'],bp,base_ctx):raise ValueError('Baseline catalog differs from its source fragments')
        selected_pack=source_pack
        source_pack=compose_sources(base,source_pack,base_sha,source_sha)
        from .operation_contracts import encoded
        # Retaining an unchanged pack is an exact-byte handoff, not a new
        # serialization identity. Actual appended captures still get a new hash.
        composed=read(p['source_pack_path']) if source_pack==selected_pack else (encoded(source_pack)+'\n').encode()
        source_sha=hashlib.sha256(composed).hexdigest()
    from .subject_contract import validate_input
    validate_input(inventory)
    items=inventory.get('items')
    if inventory.get('contract'):
        from .operation_contracts import validate_document,identity
        if identity(inventory['contract']).get('record_role') not in ('inventory','subjects'):raise ValueError('Collection input is not a subject contract')
        validate_document(json.dumps(inventory).encode(),inventory['contract'])
        if not inventory['complete']:raise ValueError('Inventory is not sealed')
    from .operation_contracts import identity as registered_family
    permits_empty=registered_family({k:contract[k] for k in ('id','version')}).get('allow_empty_subjects',False)
    if not isinstance(items,list) or len(items)>p['max_records'] or (not items and inventory.get('contract',{}).get('id')!='sourcing.inventory' and not permits_empty):
        raise ValueError('Sourcing inventory exceeds frozen record capacity')
    mapping={}
    for item in items:
        if not isinstance(item,dict):raise ValueError('Invalid sourcing inventory')
        ident=item.get('id');bounded_text(ident,80)
        if ident in mapping:raise ValueError('Duplicate sourcing inventory identity')
        mapping[ident]=item
    if 'record_range' in p:
        start,end=p['record_range'];mapping=dict(list(mapping.items())[start:end])
    if source_pack.get('version')!=1 or not isinstance(source_pack.get('entries'),list):
        raise ValueError('Expected native public source-pack version 1')
    for entry in source_pack['entries']:
        if not isinstance(entry,dict) or not isinstance(entry.get('pages',[]),list):raise ValueError('Invalid source-pack entry')
        for page in entry.get('pages',[]):
            if not isinstance(page,dict) or not isinstance(page.get('url'),str) or not isinstance(page.get('text'),str):
                raise ValueError('Source observation needs an exact URL and text')
    visual=p.get('selection_policy')=='visual'
    if review:
        candidate,_=bound_json(frozen,p['catalog_path'],read)
        visual=candidate.get('parameters',{}).get('selection_policy')=='visual'
    journal=evidence.source_pack_journal(source_pack,discovery=visual)
    observations={a['id']:a['result'] for a in journal['actions']}
    for page in observations.values():
        if not isinstance(page['text'],str):raise ValueError('Source observation lacks exact text')
        from .web_sources import allowed
        if not allowed(page['url'],[]):raise ValueError('Sourcing requires a public HTTPS product URL')
    targets={f"page-{ei}-{pi}":entry.get("target_ids",[]) for ei,entry in enumerate(source_pack["entries"]) for pi,page in enumerate(entry.get("pages",[]))}
    targets.update({a['id']:a['result']['target_ids'] for a in journal['actions'] if a['result'].get('discovery')})
    result=dict(inventory=mapping,journal=journal,observations=observations,observation_targets=targets,
                source_versions=dict(inventory_sha256=inv_sha,source_pack_sha256=source_sha))
    result.update(producer_contract=dict(id=family_id(contract),version=1),review_contract=dict(id=family_id(contract,True),version=1))
    result['parameters']=p
    if baseline is not None:result.update(base_records={r['item']:r for r in baseline['records']},composed_source_pack=composed)
    if review:
        catalog,catalog_sha=bound_json(frozen,p['catalog_path'],read)
        if catalog.get('contract')!=dict(id=family_id(contract),version=1):raise ValueError('Review requires a typed sourcing catalog')
        source_params=catalog.get('parameters',{});parameters(source_params)
        if any(source_params.get(k)!=p.get(k) for k in ('record_range','field_definitions','identity_field')):raise ValueError('Catalog record range differs from review assignment')
        if catalog.get('source_versions')!=result['source_versions']:raise ValueError('Catalog source versions differ from review inputs')
        records=catalog.get('records')
        if not isinstance(records,list):raise ValueError('Missing submitted sourcing records')
        for record in records:options_record(record,source_params,result)
        expected=options_document(records,source_params,result)
        if catalog!=expected or not expected['complete']:raise ValueError('Catalog differs from its bound fragments or is incomplete')
        result.update(items={i['id']:i for i in catalog['items']},catalog_sha256=catalog_sha,catalog_parameters=source_params)
    return result


def prepare_recovery(task,session):
    """Bind only an explicitly supplied, unambiguous sealed baseline.

    This registered family hook supplies mechanical ports, never chooses items,
    changes semantic parameters, or grants new research/acceptance authority.
    """
    from task_relay.record_planning import path
    from .research_quality import load_json
    intent=task['records'];inventory=intent['inputs']['inventory_path']
    selection=task.pop('record_recovery_selection',None)
    if 'source' not in inventory:
        if selection and selection.get('baseline'):raise ValueError('Content baseline requires an existing bound inventory')
        return None
    inv,_=session.artifact(inventory['source']);documents=[]
    for item in task['inputs']:
        if not item.get('artifact') or item.get('media_type')!='application/json':continue
        artifact,raw=session.artifact(item['artifact'])
        try:value=load_json(raw)
        except (ValueError,UnicodeError):continue
        if isinstance(value,dict):documents.append((item,artifact,value))
    candidates=[(i,a,v) for i,a,v in documents if v.get('contract')==intent['family'] and v.get('complete') is True
        and v.get('source_versions',{}).get('inventory_sha256')==inv['sha256']]
    if selection is not None:
        explicit=selection.get('baseline')
        selected=[explicit] if explicit else selection['inputs']
        identities={i['artifact'] for i in selected if i.get('artifact')}
        # An exact selection never silently falls back to another catalog.
        candidates=[(i,a,v) for i,a,v in candidates if a['id'] in identities or not explicit and
            any(x.get('from_task')==a['task'] and x.get('output')==a['path'] for x in selected if x.get('from_task'))]
        if explicit and not candidates:raise ValueError('Content baseline is not a compatible sealed catalog for the bound inventory')
    # Equal bytes from different artifact IDs remain different choices.
    candidates=list({a['id']:(i,a,v) for i,a,v in candidates}.values())
    if not candidates:return None
    if len(candidates)!=1:raise ValueError('Select one exact sealed baseline catalog with content.baseline:{artifact:ID}; inherited candidates are evidence only')
    item,artifact,catalog=candidates[0]
    checkpoint=None
    if artifact['attempt']:
        attempt=session.rt.db.execute('SELECT state,receipt FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
        if attempt and (attempt['state']=='blocked' or catalog['parameters'].get('resume_checkpoint')):
            from .record_recovery import collected_checkpoint
            checkpoint=collected_checkpoint(session.rt,artifact)
        if not attempt or (attempt['state']!='completed' or catalog['parameters'].get('resume_checkpoint')) and checkpoint is None:
            raise ValueError('Content baseline requires a completed collected producer; active or uncertain work cannot supply it')
        if attempt['state']=='completed':
            receipt=json.loads(attempt['receipt'] or '{}')
            if (receipt.get('status')!='finished' or receipt.get('exit_code')!=0
                    or receipt.get('pending_requests')!=[] or receipt.get('external_outcome')!='no_pending_response'
                    or receipt.get('reason') is not None or receipt.get('cleanup_error')):
                raise ValueError('Content baseline requires a confirmed completed collected producer without pending effects')
    from .record_lifecycle import inherit_parameters
    inherited=inherit_parameters(intent,catalog['parameters'])
    bases=[i for i,a,v in documents if a['sha256']==catalog['source_versions']['source_pack_sha256']
        and v.get('version')==1 and isinstance(v.get('entries'),list)]
    # The declared source port is already an exact choice. If it carries the
    # baseline bytes, inherited copies cannot make that choice ambiguous.
    chosen_source=path(task,intent['inputs']['source_pack_path'])
    selected_base=[i for i in bases if i['path']==chosen_source]
    if selected_base:bases=selected_base
    if len(bases)!=1:raise ValueError('Recovery needs the exact baseline source pack among its declared evidence')
    output='delivery/retained-sources.json'
    if output in {i['path'] for i in task['inputs']}|{o['path'] for o in task['outputs']}:
        raise ValueError('Composed evidence port conflicts with an existing path')
    task['record_composition']=dict(base_source_pack_path=bases[0]['path'],base_catalog_path=item['path'],
        source_pack_output=output,allow_baseline_amend=True,export_bytes=task['limits']['output_bytes'])
    if checkpoint:
        task['record_composition']['resume_checkpoint']=checkpoint
        if catalog['parameters'].get('record_range'):
            task['records_range']=catalog['parameters']['record_range'][:]
        task['instruction']+='\nVerified correction checkpoint: revision zero already retains the exact saved records. Do not resubmit them. Inspect operation_progress.record_versions; use guarded operation_amend only for remaining changes in this assigned record range. Prior semantic findings remain unresolved until exact independent re-review. Other partitions are evidence only; they are not this worker\'s completion criteria. Reserve four requests for bounded export inspection and finish.'
    task['outputs'].append(dict(path=output,purpose='Exact retained and new evidence',media_type='application/json'))
    task['instruction']+='\nCode initializes revision zero from the exact supplied baseline within the assigned scope. Do not resubmit retained records. operation_progress.record_versions and baseline_comparison identify saved versions and exact raw changes; equality is not semantic approval. Submit only new items; use guarded operation_amend for changes, additions to existing items or current gaps. Originals remain preserved; independent review is required. source_find locates exact evidence and offsets without another helper. option_id is a code-owned content-version hash, not a stable product identity: a substantive amendment must regenerate it. Preserve unchanged records and exact source-page/image provenance; never rewrite or reject an otherwise valid amendment solely to retain its old option_id. Downstream consumers must use the exported catalog with its exact source_pack_output when present, including that version in independent review.'
    return dict(kind='retained_record_evidence',producer=task['id'],baseline=artifact['id'],baseline_sha256=artifact['sha256'],checkpoint=checkpoint,
        inherited_parameters=inherited,
        original_source=catalog['source_versions']['source_pack_sha256'],original_source_artifact=bases[0]['artifact'],selected_source=chosen_source,
        output=output,acceptance=False,output_bytes=task['limits']['output_bytes'])


def compose_sources(base,fresh,base_sha,fresh_sha):
    """Append captures without moving any previous observation or changing text."""
    import copy
    for pack in (base,fresh):
        if pack.get('version')!=1 or not isinstance(pack.get('entries'),list):raise ValueError('Composition needs native source-pack version 1')
    if fresh['entries'][:len(base['entries'])]==base['entries']:
        # A proven retained prefix already has stable observation IDs. Do not
        # duplicate it or discard the descendant's read counters/receipts.
        return copy.deepcopy(fresh)
    value=copy.deepcopy(base)
    value['entries'].extend(copy.deepcopy(fresh['entries']))
    value['composition']=dict(version=1,inputs=[dict(sha256=base_sha,entry_start=0,entry_count=len(base['entries'])),
        dict(sha256=fresh_sha,entry_start=len(base['entries']),entry_count=len(fresh['entries']))],
        policy='Prior page indices and bytes preserved; appended captures are candidates, not verification.')
    # Native packs carry the hashes needed for the complete mechanical index.
    if all('sha256' in page for entry in value['entries'] for page in entry.get('pages',[])):
        from .web_sources import mechanical_index
        value['mechanical']=mechanical_index(value)
    return value


def retain_record(value,ctx):
    """Preserve baseline fragments; agents only supply additions and current gaps."""
    import copy
    prior=ctx.get('base_records',{}).get(value.get('item'))
    if not prior:return value
    from .web_sources import page_identity
    result=copy.deepcopy(value);options=copy.deepcopy(prior['options']);urls=set()
    prior_by_url={page_identity(ctx['observations'][o['observation']]['url']):o for o in options}
    urls.update(prior_by_url)
    for option in value['options']:
        url=page_identity(ctx['observations'][option['observation']]['url'])
        if url in prior_by_url and option!=prior_by_url[url]:
            from .operation_contracts import digest
            raise ValueError('Existing option differs from retained checkpoint; no change committed. Retain with options:[] first if not yet committed, then use operation_amend with current operation_progress revision and expected_record_sha256='+digest(prior))
        if url not in urls:options.append(copy.deepcopy(option));urls.add(url)
    result['options']=options
    return result

def options_document(records, params, ctx):
    from . import operation_contracts as c
    by_id={r['item']:r for r in records}
    if len(by_id)!=len(records):raise ValueError('Duplicate sourcing records')
    items=[]
    for ident in ctx['inventory']:
        if ident not in by_id:continue
        r=by_id[ident];options=[]
        for source in r['options']:
            page=ctx['observations'][source['observation']]
            fields={}
            for field,span in source['fields'].items():
                fields[field]=(dict(status='unknown',reason=span['reason']) if span['status']=='unknown' else
                    dict(status='observed',**capture(ctx,params,field,source['observation'],span)))
            option=dict(product_url=page['url'],fields=fields,comparison=source['comparison'])
            if params.get('selection_policy')=='visual':option['selection']=source['selection']
            option['option_id']=c.digest([ident,option])
            options.append(option)
        shortfall=max(0,params['options_per_item']-len(options))
        coverage=None
        if params.get('selection_policy')=='visual':
            from .visual_selection import counts
            coverage=counts(options,params['options_per_item']);shortfall=coverage['shortfall']
        if shortfall and not r['gap'].strip():raise ValueError('Sourcing shortfall needs an explicit gap')
        items.append(dict(id=ident,options=options,gap=r['gap'],shortfall=shortfall))
        if coverage is not None:items[-1]['coverage']=coverage
    return dict(contract=ctx.get('producer_contract',dict(id='sourcing.options',version=1)),parameters=params,
                source_versions=ctx['source_versions'],records=records,items=items,
                complete=set(by_id)==set(ctx['inventory']))

def review_document(records, params, ctx):
    for record in records:review_record(record,params,ctx)
    return dict(contract=ctx.get('review_contract',dict(id='sourcing.review',version=1)),parameters=params,
                catalog_sha256=ctx['catalog_sha256'],records=records,
                complete={r['item'] for r in records}==set(ctx['items']))

def summary(document):
    if document['contract']['id']=='sourcing.inventory':
        from .sourcing_inventory import summary as inventory_summary
        return inventory_summary(document)
    lines=['# Sourcing review' if is_review(document['contract']) else '# Sourcing schedule','']
    if is_review(document['contract']):
        for r in document['records']:lines.extend([f"## {r['item']} — {r['verdict']}",r['reason'],''])
    else:
        for item in document['items']:
            lines.extend(['## '+item['id'],''])
            visual=document['parameters'].get('selection_policy')=='visual'
            if visual:
                v=item['coverage'];lines.append(f"Visually suitable: {v['suitable']}; target: {document['parameters']['options_per_item']}; shortfall: {v['shortfall']}; provisional: {v['provisional']}; excluded: {v['excluded']}; unavailable: {v['unavailable']}.")
            for option in item['options']:
                for k,v in option['fields'].items():
                    lines.append(k+': '+(v['reason'] if v['status']=='unknown' else v['excerpt']))
                from .visual_selection import description
                lines.extend([option['product_url'],description(option) if visual else option['comparison'],''])
            if item['gap']:lines.extend([('Recorded sourcing note: ' if visual else 'Gap: ')+item['gap'],''])
    lines.append('Literal source support and semantic review do not establish current stock or user acceptance.')
    return '\n'.join(lines)+'\n'

def validate_assignment(frozen):
    contract=frozen['operation_contract'];review=is_review(contract);p=contract['parameters']
    parameters(p,review)
    if frozen.get('tools')!=['files'] or frozen.get('execution') or frozen.get('computer') or frozen.get('browser'):
        raise ValueError('Typed sourcing requires a declared-file API worker; no provider or host fallback')
    if review!=bool(frozen.get('review_of')):raise ValueError('Sourcing review must independently review its producer')
    outputs={o['path'] for o in frozen['outputs']};inputs={i['path'] for i in frozen['inputs']}
    if contract['output']==p['summary_path'] or not {contract['output'],p['summary_path']}<=outputs:
        raise ValueError('Sourcing JSON and code-generated summary must be declared separately')
    required={p['inventory_path'],p['source_pack_path']}|({p['catalog_path']} if review else set())
    if p.get('source_pack_output'):
        required|={p['base_source_pack_path'],p['base_catalog_path']}
        if p['source_pack_output'] not in outputs or p['source_pack_output'] in inputs:
            raise ValueError('Composed source pack needs a separate code-owned output')
    if not required<=inputs:raise ValueError('Sourcing inputs must be explicitly bound')
    from .executors import request_limit,response_limit
    minimum=(p['record_range'][1]-p['record_range'][0] if 'record_range' in p else p['max_records'])+2
    if request_limit(frozen)<minimum or frozen['limits']['tool_calls']<minimum:
        raise ValueError(f'Typed sourcing needs at least {minimum} tools/requests; split or replan within existing budgets')
    if response_limit(frozen)<4096:raise ValueError('Typed sourcing needs at least 4096 response tokens')

def validate_result(document, result):
    if result['decision']=='blocked':return
    if not document['complete']:raise ValueError('Sourcing completion requires every inventory item checkpoint')
    if document['contract']['id']=='sourcing.inventory':return
    if is_review(document['contract']):
        if result['decision']=='accept' and any(r['verdict']!='supported' for r in document['records']):
            raise ValueError('Unsupported or uncertain sourcing records cannot be accepted')
    elif document['parameters']['count_policy']=='required' and any(i['shortfall'] for i in document['items']):
        raise ValueError('Required sourcing alternatives remain missing')

def preflight(frozen,ctx):
    """Reject known impossible work before an attempt exists, without raising grants."""
    from .executors import request_limit
    if frozen['operation_contract']['id']=='sourcing.inventory':return
    count=len(ctx['inventory']);minimum=count+2
    if not is_review(frozen['operation_contract']) and frozen['operation_contract']['parameters']['count_policy']=='required':
        minimum+=sum(1 for page in source_index(ctx) if page['duplicate_of'] is None)
    if min(request_limit(frozen),frozen['limits']['tool_calls'])<minimum:
        raise ValueError(f'Sourcing batch needs {minimum} tools/requests including saved-page reads; split or replan within frozen budgets')

def source_index(ctx):
    from .web_sources import page_identity
    seen={};result=[]
    for key,page in ctx['observations'].items():
        version=(page_identity(page['url']),hashlib.sha256(page['text'].encode()).hexdigest())
        result.append(dict(observation=key,url=page['url'],characters=len(page['text']),duplicate_of=seen.get(version),
            image_candidates=len(page.get('images',[])),structured_products=len(page.get('products',[]))))
        seen.setdefault(version,key)
    return result

def source_read(ctx,args):
    from . import operation_contracts as c
    c.fields(args,('observation','offset','limit'))
    page=ctx['observations'].get(args['observation'])
    if page is None:raise ValueError('Unknown sourcing observation ID; select an observation from source_index, not a URL')
    if type(args['offset']) is not int or not 0<=args['offset']<=len(page['text']) or type(args['limit']) is not int or not 1<=args['limit']<=12000:
        raise ValueError('Sourcing offset must be within the saved text; limit must be 1–12000 characters')
    start=args['offset'];end=min(start+args['limit'],len(page['text']))
    from .product_evidence import capture,displayed_prices
    text=page['text'];prices=[{k:p[k] for k in ('start','end','text')} for p in displayed_prices(text)
                            if start<=p['start']<p['end']<=end]
    for match in re.finditer(r'\{[^{}]{1,4000}\}',text):
        if not start<=match.start()<match.end()<=end:continue
        if '"price"' not in match.group() or '"priceCurrency"' not in match.group():continue
        try:
            captured=capture(dict(actions=[dict(id='span',result=dict(observation='span',url=page['url'],text=text))]),
                             dict(field='price',observation='span',start=match.start(),end=match.end()))
        except ValueError:continue
        prices.append(dict(start=match.start(),end=match.end(),text=match.group(),currency=captured['currency'],basis='observed-jsonld-offer'))
    prices.sort(key=lambda s:s['start'])
    spans=[]
    pos=start
    while pos<end:
        stop=min(pos+600,end);newline=text.find('\n',pos,stop)
        if newline>=pos:stop=newline+1
        spans.append(dict(start=pos,end=stop,text=text[pos:stop]));pos=stop
    return dict(observation=args['observation'],url=page['url'],text=page['text'][start:end],
                offset=start,next_offset=end if end<len(page['text']) else None,
                price_spans=prices,text_spans=spans,
                image_candidates=page.get('images',[]),structured_products=page.get('products',[]),
                discovery=page.get('discovery'),
                metadata_authority='Captured page metadata, separate from visible text. Image URLs are candidates only: not downloaded or visually verified photos. Missing metadata does not establish that the live page has no images. Structured offers do not establish selected variant or current stock.',
                span_authority='Exact selectable offsets only; price variant/currentness and field meaning still require semantic review.')

def source_find(ctx,args):
    """Find exact literals without depending on the current item's progress cursor."""
    from .operation_contracts import fields
    fields(args,('observation','query','offset','limit'))
    observation=args['observation'];query=args['query'];offset=args['offset'];limit=args['limit']
    if (not isinstance(observation,str) or not isinstance(query,str) or len(query)>4000
            or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=40):
        raise ValueError('Use a literal up to 4000 characters, nonnegative result offset and limit 1–40')
    if observation and observation not in ctx['observations']:
        raise ValueError('Unknown observation; empty observation/query lists exact saved observations')
    matches=[];total=0
    def retain(value):
        nonlocal total
        if offset<=total<offset+limit:matches.append(value)
        total+=1
    for entry in source_index(ctx):
        ident=entry['observation']
        if observation and ident!=observation:continue
        text=ctx['observations'][ident]['text']
        meta={**entry,'page_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
              'target_ids':ctx.get('observation_targets',{}).get(ident,[])}
        if not query:retain(meta);continue
        pos=0
        while True:
            start=text.find(query,pos)
            if start<0:break
            end=start+len(query);retain({**meta,'start':start,'end':end,'text':text[start:end],
                'context':text[max(0,start-80):min(len(text),end+80)]});pos=end
    return dict(matches=matches,total=total,
        next_offset=offset+limit if offset+limit<total else None,source_versions=ctx['source_versions'],
        authority='Exact literal locations only. Correspondence and field meaning require review; no network or acceptance.')


def tools(contract):
    result=[dict(name='source_find',description='Find exact literals and code-calculated offsets in saved evidence. Empty observation searches all pages; empty query lists selectable observations across all items, including committed records. Use this instead of delegating character counting. No network or inferred meaning.',
        parameters=obj({'observation':STRING,'query':{'type':'string','maxLength':4000},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':40}}))]
    if not is_review(contract):
        result.append(dict(name='source_read' if contract['id'].startswith('collection.') else 'sourcing_source_read',description='Read exact saved page text with selectable price_spans/text_spans. Use their code-calculated absolute start/end offsets; do not manually count characters. These spans establish literal text only, not product/variant correspondence or stock. No search, browser or network call; never retype prices.',
            parameters=obj({'observation':STRING,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':12000}})))
        result.append(dict(name='operation_amend',description='Correct one committed sourcing item before delivery. Exact current revision and record SHA-256 guard the change. Original record and receipt remain durable; this grants no acceptance.',
            parameters=obj({'request_key':STRING,'revision':{'type':'integer'},'expected_record_sha256':STRING,'record':options_schema(contract['parameters'])})))
    return result
