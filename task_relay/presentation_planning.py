"""Compile a declared document review into exact compatible preview evidence."""
import copy
import hashlib
from orchestrator import contracts as c
from orchestrator.execution import REGISTRY


def budgets(plan,scope):
    """Allocate review from registered output units within frozen scope ceilings."""
    import importlib
    if scope.get('planner_budget_binding_version')!=2:return []
    sources={s['artifact']:s for s in scope.get('sources',[])+scope.get('available_sources',[])}
    texts={t['artifact']:t['text'] for t in scope.get('source_texts',[])}
    costs={};receipts=[];tasks={t['id']:t for t in plan['tasks']}
    for task in plan['tasks']:
        hook=REGISTRY.get(task.get('execution',{}).get('capability'),{}).get('review_workload')
        if not hook:continue
        def read(path):
            item=next((i for i in task['inputs'] if i['path']==path),{});source=sources.get(item.get('artifact'))
            if not source:return None
            text=texts.get(source['artifact'])
            if text is None:return None
            raw=text.encode()
            return raw if len(raw)==source['bytes'] and hashlib.sha256(raw).hexdigest()==source['sha256'] else None
        correction=any(t.get('review_correction',{}).get('producer')==task['id'] for t in plan['tasks'])
        module,name=hook.split(':');cost=getattr(importlib.import_module(module),name)(task,read,correction=correction)
        if cost:costs[task['id']]=cost
    for review in plan['tasks']:
        producer=tasks.get(review.get('review_of'),{});cost=costs.get(producer.get('id'))
        if not cost and 'pptx.render' in REGISTRY.get(producer.get('execution',{}).get('capability'),{}).get('companions',{}):
            matches={i['from_task'] for i in producer['inputs'] if i.get('from_task') in costs}
            if len(matches)==1:cost=costs[next(iter(matches))]
        if not cost:continue
        for key in ('tool_calls','seconds'):
            value=cost[key];before=review['limits'][key]
            if value>scope['options']['limits'][key]:raise ValueError('Presentation review workload exceeds frozen '+key+' ceiling; partition before dispatch')
            if before<value:
                review['limits'][key]=value
                receipts.append(dict(task=review['id'],field=key,before=before,value=value,workload=cost,
                    source='registered output units within frozen planning scope'))
    return receipts


def bind(plan,scope):
    if scope.get('connector_companions_version')!=1:return []
    available={e['id']:e for e in scope.get('graph_operations',[]) if e.get('available')}
    receipts=[]
    for producer in list(plan['tasks']):
        if 'pptx.render' not in REGISTRY.get(producer.get('execution',{}).get('capability'),{}).get('companions',{}):continue
        reviewers=[r for r in plan['tasks'] if r.get('review_of')==producer['id']]
        if len(reviewers)!=1:raise ValueError('Presentation output requires one independent final reviewer')
        reviewer=reviewers[0]
        from orchestrator import executors,worker_capabilities
        if worker_capabilities.backend_for(reviewer,plan['backend'])['type'] not in (*executors.CODE_TYPES,'codex-cli'):
            raise ValueError('Presentation preview inspection needs the declared code-capable reviewer to open PNG ZIP evidence')
        existing=[t for t in plan['tasks'] if t.get('execution',{}).get('capability')=='pptx.render' and producer['id'] in t['dependencies']]
        if existing:
            if (len(existing)!=1 or len(existing[0]['inputs'])!=1
                    or existing[0]['inputs'][0].get('from_task')!=producer['id']
                    or existing[0]['inputs'][0].get('output')!=producer['outputs'][0]['path']
                    or existing[0]['id'] not in reviewer['dependencies']
                    or {i.get('output') for i in reviewer['inputs'] if i.get('from_task')==existing[0]['id']}!=set(REGISTRY['pptx.render']['outputs'])):
                raise ValueError('Existing presentation preview must bind the exact candidate and every registered preview output to its own reviewer')
            continue
        if 'pptx.render' not in available:raise ValueError('Presentation renderer unavailable before Start; retain the proposal without dispatch')
        ident=producer['id']+'_preview'
        if len(ident)>80:ident=producer['id'][:60]+'_preview_'+hashlib.sha256(producer['id'].encode()).hexdigest()[:8]
        if ident in {t['id'] for t in plan['tasks']}:raise ValueError('Presentation preview task ID conflicts with the proposed graph')
        spec=REGISTRY['pptx.render'];output=producer['outputs'][0]
        helper=dict(id=ident,role='operation',objective='Render exact candidate for independent final review',
                    instruction='Open the exact candidate and retain every page preview without changing source files.',
                    execution=dict(capability='pptx.render',version=1,parameters={}),tools=[],criteria=copy.deepcopy(spec['criteria']),
                    inputs=[dict(from_task=producer['id'],output=output['path'],path='candidate.pptx',media_type=output['media_type'],
                                 purpose='Exact unaccepted candidate for preview only',authority='Candidate bytes, not acceptance')],
                    outputs=[dict(path=p,media_type=m,purpose='Exact-candidate compatible presentation preview') for p,m in spec['outputs'].items()],
                    dependencies=[producer['id']],max_attempts=1,
                    limits=dict(seconds=spec['seconds'],tool_calls=1,output_bytes=spec['output_bytes']))
        helper=c.assignment(helper);plan['tasks'].append(helper);reviewer['dependencies'].append(ident)
        if len(plan['tasks'])>scope.get('options',{}).get('max_tasks',30):raise ValueError('Presentation companion exceeds the frozen stage task allowance; reserve one preview task per candidate')
        for output in helper['outputs']:
            reviewer['inputs'].append(dict(from_task=ident,output=output['path'],path='preview/'+output['path'].split('/')[-1],
                media_type=output['media_type'],purpose=output['purpose'],authority='Rendered evidence; inspect independently'))
        reviewer['instruction']+='\nUse preview/render.json to verify the exact candidate hash and completed compatible renderer. Inspect every PNG in preview/slide-previews.zip individually; do not rerun sourcing or require a specific presentation application when compatible opening is already proven. Layout/source defects still require precise findings. Preview generation is not visual approval.'
        receipts.append(dict(producer=producer['id'],reviewer=reviewer['id'],preview=ident,reason='registered-review-evidence-companion'))
    return receipts
