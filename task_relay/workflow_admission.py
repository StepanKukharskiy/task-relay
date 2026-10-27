"""Code-owned admission for compatible compact graphs; no domain or dispatch logic."""
import math


def enabled(scope):
    # Admission capacity is its own contract, independent of record schemas.
    return scope.get('planner_budget_binding_version')==2


def implementation_identity(roots=None):
    """Reconcile saved proposals after any compiler/adapter implementation change.

    Cover both runtime packages, including newly registered modules. Identity is
    only permission to revalidate unchanged data, never permission to dispatch.
    """
    import hashlib
    from pathlib import Path
    from orchestrator import contracts
    if roots is None:roots=(Path(__file__).parent,Path(contracts.__file__).parent)
    digest=hashlib.sha256()
    for root in sorted(roots,key=lambda p:p.name):
        for path in sorted(root.rglob('*.py')):
            digest.update((root.name+'/'+path.relative_to(root).as_posix()).encode()+b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def normalize(proposal,scope,options):
    """Discard only irrelevant legacy annotations; preserve the selected version.

    Never reinterpret native arguments, source IDs, providers, quantities or user
    limits. Original wire replies remain immutable in the planner call journal.
    """
    if not enabled(scope):return []
    receipts=[]
    for index,task in enumerate((proposal.get('plan') or {}).get('tasks',[])):
        if not isinstance(task,dict) or task.get('execution'):continue
        refs=[(f'$.plan.tasks[{index}].input_bindings[{n}]',ref)
              for n,ref in enumerate(task.get('input_bindings',[]))]
        for field in ('sourcing','records'):
            intent=task.get(field)
            if not isinstance(intent,dict):continue
            selected=intent.get('inputs',{}) if field=='records' else intent
            refs.extend((f'$.plan.tasks[{index}].{field}.{key}',ref) for key,ref in selected.items())
        for path,ref in refs:
            if isinstance(ref,dict) and set(ref)=={'source','role'} and ref['role']=='asset':
                ref.pop('role')
                receipts.append(dict(path=path+'.role',before='asset',value=None,
                    source='local record/file input binding',reason='adapter-only annotation has no meaning on a local file reference; exact source remains unchanged'))
    return receipts


def review_capacity(plan,scope,options):
    """Pair review allowance with producer attempts inside the frozen maximum."""
    if not enabled(scope):return []
    tasks={t['id']:t for t in plan['tasks']};receipts=[]
    for review in plan['tasks']:
        producer=tasks.get(review.get('review_of'))
        if not producer:continue
        required=producer['max_attempts'];before=review['max_attempts']
        if before>=required:continue
        if required>options.get('max_attempts',1):
            raise ValueError('Paired review capacity exceeds the frozen attempt allowance')
        if review.get('browser') or review.get('computer') or review.get('execution'):
            raise ValueError('Paired review capacity needs a compatible local reviewer')
        review['max_attempts']=required
        receipts.append(dict(path='$.plan.tasks.'+review['id']+'.max_attempts',before=before,value=required,
            source='producer attempt allowance within options.max_attempts',reason='each permitted producer candidate needs independent review capacity'))
    return receipts


def response_budgets(plan,scope,options):
    """Reserve reasoning plus a compact report; explicit ceilings remain binding."""
    if not enabled(scope) or not options.get('response_budgets'):return []
    from orchestrator import executors,worker_capabilities
    ceiling=min(options['limits'].get('response_tokens',executors.MAX_RESPONSE_TOKENS),executors.MAX_RESPONSE_TOKENS)
    receipts=[]
    for task in plan['tasks']:
        if task.get('execution') or worker_capabilities.backend_for(task,plan['backend'])['type'] not in executors.FILE_TYPES:
            continue
        if 'response_tokens' in task['limits']:continue
        # Estimates are an allocation, not a promise about provider reasoning.
        reserve=4096+1024+256*len(task['criteria'])
        value=min(ceiling,executors.MAX_RESPONSE_TOKENS,max(4096,math.ceil(reserve/1024)*1024))
        task['limits']['response_tokens']=value
        receipts.append(dict(path='$.plan.tasks.'+task['id']+'.limits.response_tokens',value=value,
            source='frozen response ceiling and criterion count',reason='reserve reasoning, per-check evidence and final report; explicit smaller response budgets are retained'))
    return receipts
