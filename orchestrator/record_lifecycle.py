"""Registered content hooks for the shared transactional record engine.

Hooks interpret content; only Store/controller code commits, exports or retries.
No family identifier is consulted by the engine.
"""
from dataclasses import dataclass
import hashlib
import copy


def inherit_parameters(intent, baseline):
    """Project all public semantic choices from an already verified baseline.

    Internal paths, checkpoint proofs and workload ranges are rebound elsewhere.
    An explicit conflicting choice is a new intent, never a correction override.
    """
    from . import operation_contracts, parameter_contracts
    family=operation_contracts.identity(intent['family'])
    schema=family['planning_interface']['schema']
    saved={k:copy.deepcopy(baseline[k]) for k in schema['properties'] if k in baseline}
    parameter_contracts.validate(saved,schema,'baseline content choices')
    try:
        parameter_contracts.validate(intent['parameters'],{**schema,'required':[]},'correction choices')
    except ValueError as exc:
        raise ValueError('Recovery must preserve baseline semantic parameter types: '+str(exc)) from exc
    for key,value in intent['parameters'].items():
        if key not in saved or value!=saved[key]:
            raise ValueError('Recovery must preserve baseline semantic parameters: '+key)
    intent['parameters']=saved
    return dict(parameters=copy.deepcopy(saved),parameters_sha256=operation_contracts.digest(saved))


@dataclass(frozen=True)
class Lifecycle:
    context: object = None
    maximum: object = lambda store: store.contract['parameters']['max_records']
    progress: object = lambda store, records: {}
    document: object = lambda store, records: dict(
        contract={k:store.contract[k] for k in ('id','version')},
        parameters=store.contract['parameters'], records=records)
    complete: object = lambda store, records: bool(records)
    projections: object = None
    normalize: object = lambda record, context: record
    order: object = None
    verify_result: object = None
    require_active: bool = False
    amendable: bool = False
    export_empty: bool = False
    resumable: bool = False
    rejection_resumable: bool = False
    indexed: bool = False
    fragment_only: bool = False
    owned_parameters: tuple = ()
    tools: object = lambda contract: []
    instructions: str = ''
    completion_error: str = 'Incomplete operation record set'
    preflight: object = None
    evidence_parameter: str = ''
    evidence_output_parameter: str = ''
    freeze: object = None
    review_units: object = None
    evidence_extension: str = ''
    prepare_recovery: object = None
    initial_records: object = lambda store: []


def audit_context(frozen, read):
    from .research_quality import load_json
    binding=frozen['computer_review'];research=binding['research']
    for item in frozen['inputs']:
        if hashlib.sha256(read(item['path'])).hexdigest()!=item['sha256']:
            raise ValueError('Frozen operation input changed')
    raw=read(binding['path'])
    if hashlib.sha256(raw).hexdigest()!=binding['sha256']:raise ValueError('Raw source binding changed')
    pack=load_json(raw)
    if pack['research']!=research:raise ValueError('Research units differ from the frozen binding')
    sources={o['observation']:o['text'] for o in pack['observations']}
    sources['coverage']=pack['coverage_note']
    return dict(sources=sources,units=research['units'])


def audit_progress(store, records):
    done={r['claim'] for r in records}
    pending=[u for u in store.frozen['computer_review']['research']['units'] if u['claim'] not in done]
    return dict(remaining=len(pending),next_claims=pending[:store.family['batch']])


def audit_document(store, records):
    binding=store.frozen['computer_review'];research=binding['research']
    return {**{k:research[k] for k in ('summary_sha256','evidence_sha256','post_count','max_posts')},
            'raw_sha256':binding['sha256'],'claims':sorted(records,key=lambda r:r['claim'])}


def audit_order(store, keys, existing, context):
    pending=[str(u['claim']) for u in context['units'] if str(u['claim']) not in existing][:store.family['batch']]
    if keys!=pending[:len(keys)]:raise ValueError('Submit only the next frozen claim IDs in order')


def audit_freeze(frozen):
    from .executors import request_limit
    n=len(frozen['computer_review']['research']['units']);minimum=(n+2)//3+2
    if request_limit(frozen)<minimum or frozen['limits']['tool_calls']<minimum:
        raise ValueError(f'Typed audit needs at least {minimum} frozen requests/tools for {n} claims; replan without resetting attempts')


AUDIT=Lifecycle(context=audit_context,freeze=audit_freeze,
    maximum=lambda s:len(s.frozen['computer_review']['research']['units']),
    progress=audit_progress,document=audit_document,order=audit_order,
    complete=lambda s,r:bool(r) and len(r)==s.maximum())
LEDGER=Lifecycle()
EMPTY_LEDGER=Lifecycle(complete=lambda s,r:True,export_empty=True)


def inventory_progress(store, records):
    doc=store.document(records)
    return dict(next_slot=len(doc['items'])+1,sealed=doc['complete'],image=doc['image'],
                remaining=0 if doc['complete'] else store.contract['parameters']['max_records']-len(doc['items'])+1)


def item_progress(store, records):
    ctx=store.context();done={r['item'] for r in records}
    units=ctx.get('items',ctx['inventory']);pending=[k for k in units if k not in done]
    result=dict(remaining=len(pending),next_items=[dict(item=k,
        **(dict(item_sha256=c.digest(units[k]),candidate=units[k]) if 'items' in ctx else dict(inventory=units[k]))) for k in pending[:store.family['batch']]],
        record_versions={r['item']:c.digest(r) for r in records})
    # A transport batch is a ceiling, not a reason to copy arbitrarily large
    # candidates into the working context. Keep a literal prefix of whole units.
    while len(result['next_items'])>1 and len(c.encoded(result['next_items']).encode())>c.MAX_SUBMISSION_BYTES:
        result['next_items'].pop()
    if store.contract['parameters'].get('record_range') or store.contract['parameters'].get('resume_checkpoint'):
        result['scope']=dict(items=list(units),record_range=store.contract['parameters'].get('record_range'),
            inherited_checkpoint=bool(store.contract['parameters'].get('resume_checkpoint')),acceptance=False,
            completion='All assigned records saved; semantic corrections still require independent review')
    checkpoint=store.contract['parameters'].get('resume_checkpoint')
    if checkpoint:
        result['checkpoint']=dict(baseline=checkpoint['baseline'],source=checkpoint['source'],
            parent=checkpoint['parent'],proof_sha256=c.digest(checkpoint),acceptance=False,
            unresolved_findings=checkpoint['unresolved_findings'])
    if 'items' not in ctx:
        from .sourcing_contract import source_index
        current=pending[0] if pending else None
        result['source_lookup']=dict(tool='source_find',total_observations=len(ctx['observations']),
            note='Current-item observations below are a subset. Empty observation/query lists all exact saved pages, even after completion.')
        result['observations']=[page for page in source_index(ctx) if current is not None and (not ctx.get('observation_targets',{}).get(page['observation']) or current in ctx['observation_targets'][page['observation']])]
        if pending:
            from .evidence_workload import item_evidence
            result['next_items'][0]['evidence']=item_evidence(ctx,pending[0])
        if ctx.get('base_records'):result['retained_option_counts']={k:len(r['options']) for k,r in ctx['base_records'].items() if k in units}
        if ctx.get('base_records'):
            before={k:c.digest(v) for k,v in ctx['base_records'].items() if k in units}
            now=result['record_versions']
            result['baseline_comparison']=dict(baseline_path=store.contract['parameters']['base_catalog_path'],
                unchanged=[k for k in before if now.get(k)==before[k]],
                changed=[k for k in before if k in now and now[k]!=before[k]],
                absent=[k for k in before if k not in now],added=[k for k in now if k not in before],
                authority='Exact raw-record equality only; no semantic or visual approval.')
    return result


def summary_projections(store, records):
    from .sourcing_contract import summary
    result={store.contract['parameters']['summary_path']:summary(store.document(records)).encode()}
    if store.contract['parameters'].get('source_pack_output'):
        result[store.contract['parameters']['source_pack_output']]=store.context()['composed_source_pack']
    return result


def content_result(store, records, result):
    from .sourcing_contract import validate_result
    if result.get('decision') in ('delivered','accept'):
        from .visual_selection import verify_observations
        verify_observations(store,store.document(records))
        if store.family.get('record_role')=='review':
            context=store.context()
            verify_observations(store,dict(parameters=context['catalog_parameters'],items=list(context['items'].values())))
    validate_result(store.document(records),result)


def inventory_document(store, records):
    from .sourcing_inventory import document
    return document(records,store.contract['parameters'],store.context())


def options_document(store, records):
    from .sourcing_contract import options_document
    return options_document(records,store.contract['parameters'],store.context())


def review_document(store, records):
    from .sourcing_contract import review_document
    return review_document(records,store.contract['parameters'],store.context())


def source_context(frozen, read):
    from .sourcing_contract import context
    return context(frozen,read)


def normalize_option(record, context):
    from .sourcing_contract import retain_record
    return retain_record(record,context)


def source_tools(contract):
    from .sourcing_contract import tools
    return tools(contract)

def source_preflight(frozen, context):
    from .sourcing_contract import preflight
    preflight(frozen,context)


def prepare_source_recovery(task,session):
    from .sourcing_contract import prepare_recovery
    return prepare_recovery(task,session)

def saved_records(store):
    params=store.contract['parameters'];checkpoint=params.get('resume_checkpoint')
    if not checkpoint and not params.get('allow_baseline_amend'):return []
    context=store.context()
    # context verifies the sealed catalog, every fragment, policy and exact
    # source bytes. Inherit only an explicitly compiled correction baseline;
    # new selection tasks without that binding still start empty.
    records=list(context.get('base_records',{}).values())
    if checkpoint:
        base=next(i for i in store.frozen['inputs'] if i['path']==params['base_catalog_path'])
        if base['artifact']!=checkpoint['baseline'] or c.digest(records)!=checkpoint['records_sha256']:
            raise ValueError('Correction checkpoint differs from the exact bound baseline or assigned scope')
    return [r for r in records if r['item'] in context['inventory']]


_CONTENT=dict(context=source_context,complete=lambda s,r:s.document(r)['complete'],
    projections=summary_projections,verify_result=content_result,require_active=True,
    export_empty=True,resumable=True,indexed=True,owned_parameters=('summary_path','source_pack_output'),
    completion_error='Sourcing completion requires every inventory item checkpoint',preflight=source_preflight)
INVENTORY=Lifecycle(**_CONTENT,maximum=lambda s:s.contract['parameters']['max_records']+1,
                    document=inventory_document,progress=inventory_progress)
OPTIONS=Lifecycle(**_CONTENT,document=options_document,progress=item_progress,
                  initial_records=saved_records,
                  instructions='When selection_policy is visual, first retain a broad provisional pool. After image_view of exact product and reference pixels, amend selection status/reason/hash references and shared design_id. Unknown buying fields remain unknown and do not disqualify visual suitability. Independent review is still required. Never mark suitable without actually observing both images. Selection.reason is the current visual comparison; do not carry stale photo-status prose forward. Use concise buying disclosures and preserve literal source spans.',
                  normalize=normalize_option,amendable=True,fragment_only=True,rejection_resumable=True,tools=source_tools,evidence_parameter='source_pack_path',evidence_output_parameter='source_pack_output',
                  evidence_extension='orchestrator.source_fallback:extends',prepare_recovery=prepare_source_recovery)
REVIEW=Lifecycle(**_CONTENT,document=review_document,progress=item_progress,
                 instructions='For selection_policy visual catalogs, independently inspect the cited candidate and original reference images before accepting suitable/excluded judgments. Verify distinct design identities, typed counts and current visual reasons; unknown buying facts do not disqualify visual suitability. Provisional leads are not selected alternatives. Request correction for wrong photos, unsuitable designs, duplicates or stale prose. Missing visual observations cannot be accepted.',
                 rejection_resumable=True,fragment_only=True,tools=source_tools,evidence_parameter='source_pack_path',
                 review_units=lambda frozen,context:len(context['items']))


def definition(contract):
    """Only the registry supplies hooks; JSON cannot supply executable behavior."""
    from . import operation_contracts as c
    family=c.identity({k:contract[k] for k in ('id','version')})
    return family.get('lifecycle')

# Hooks are defined before loading their registry, including direct module imports.
from . import operation_contracts as c


def implementation_sources(contract):
    """Pin registered content hooks without naming a new family in the worker."""
    import importlib
    from pathlib import Path
    family=c.identity({k:contract[k] for k in ('id','version')})
    hooks=family.get('lifecycle')
    functions=[v for v in family.values() if callable(v)]
    if hooks:functions.extend(v for v in vars(hooks).values() if callable(v))
    names={f.__module__ for f in functions}|set(family.get('support_modules',()))
    if family.get('local_record_tool'):names.add('orchestrator.record_tool')
    result={}
    for name in names:
        module=importlib.import_module(name);path=Path(module.__file__)
        key=path.name if name.startswith('orchestrator.') else name.replace('.','/')+'.py'
        result[key]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_implementation(frozen):
    for key,digest in implementation_sources(frozen['operation_contract']).items():
        if frozen.get('runtime_sources',{}).get(key)!=digest:
            raise ValueError('Registered content implementation changed after freezing: '+key)
