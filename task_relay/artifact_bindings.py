"""Compile selected source/output references into assignment bindings."""
import copy
from orchestrator import contracts as c


def resolve_port(ref,payload,sources):
    if 'port' not in ref:return ref
    if payload.get('handoff_binding_version')!=1:raise ValueError('Handoff ports are not enabled in this saved contract.')
    if set(ref)!={'port'}:raise ValueError('A handoff port cannot override source metadata.')
    port=payload.get('input_ports',{}).get(ref['port'])
    if port is None:raise ValueError('Unknown captured handoff port: '+ref['port'])
    source=sources.get(port['artifact'])
    if source is None or any(source[k]!=port[k] for k in ('path','sha256','bytes','purpose','authority')):
        raise ValueError('Captured handoff port version changed: '+ref['port'])
    return {'source':port['artifact']}

INSTRUCTIONS='''For new responses use task.input_bindings; the frozen schema owns its shape.
Do not author inputs/dependencies/selection_outputs.
Each binding is {source: exact captured artifact ID} or {producer: task ID, output:
exact declared output path}. For rhino3dm additional files only, role:"asset" marks
an extra input rather than primary script/checks/model. Relay supplies paths, source
authority, types and dependency edges. Optional after lists explicit ordering-only
task dependencies. Reviewers name review_of; Relay binds all that producer's outputs.
A user_gate selects all declared companions. Do not combine input_bindings with
inputs, dependencies or selection_outputs. These bindings do not grant acceptance,
execution permission, source conversion or access to uncaptured files.'''


def schema(*,ports=False,asset_roles=False):
    from .planning_contract import obj
    text={'type':'string'}
    source={'source':text}
    if asset_roles:source['role']={'type':'string','enum':['asset']}
    variants=[obj(source,('source',)),
              obj({'producer':text,'output':text},('producer','output'))]
    if ports:variants.append(obj({'port':text},('port',)))
    return {'anyOf':variants}


def build(result,payload):
    value=copy.deepcopy(result);plan=value.get('plan');receipts=[]
    if not isinstance(plan,dict) or not isinstance(plan.get('tasks'),list):return value,receipts
    sources={s['artifact']:s for s in payload['sources']+payload.get('available_sources',[])}
    tasks=plan['tasks'];known={t.get('id'):t for t in tasks}
    if len(known)!=len(tasks):raise ValueError('Binding task IDs must be distinct.')
    # Stage context is an already captured handoff, not a model-selected native
    # input. For an all-native producer graph, its sole semantic reviewer owns
    # omitted context ports. Ambiguous owners and named operation ports stay held.
    context_ports={}
    producers=[t for t in tasks if not t.get('review_of')]
    reviewers=[t for t in tasks if t.get('review_of') in known]
    if (payload.get('handoff_binding_version')==1 and producers and all(t.get('execution') for t in producers)
            and len(reviewers)==1 and 'input_bindings' in reviewers[0]):
        selected=[]
        for task in tasks:
            for ref in task.get('input_bindings',[]):
                resolved=resolve_port(ref,payload,sources)
                if 'source' in resolved:selected.append(resolved['source'])
        for edge in payload.get('pipeline_step',{}).get('handoff',{}).get('inputs',[]):
            port=edge['stage']+'.'+edge['deliverable']
            captured=payload.get('input_ports',{}).get(port)
            if edge['consumer']=='context' and captured and captured['artifact'] not in selected:
                context_ports.setdefault(reviewers[0]['id'],[]).append(port)
    for task in tasks:
        if 'input_bindings' not in task:continue
        if any(k in task for k in ('inputs','dependencies','selection_outputs')):
            raise ValueError('input_bindings cannot be combined with authored inputs, dependencies or selection_outputs.')
        original=copy.deepcopy(task['input_bindings']);selected=list(original)
        selected.extend({'port':port} for port in context_ports.get(task['id'],[]))
        if task.get('review_of'):
            producer=known.get(task['review_of'])
            if producer is None:raise ValueError('Unknown review producer.')
            for output in producer['outputs']:
                ref={'producer':producer['id'],'output':output['path']}
                if ref not in selected:selected.append(ref)
        inputs=[];dependencies=list(task.pop('after',[]));seen=set();versions=[]
        for ref in selected:
            ref=resolve_port(ref,payload,sources)
            if 'source' in ref:
                aid=ref['source']
                if aid not in sources:raise ValueError('Unknown selected binding artifact: '+aid)
                s=sources[aid];key=('artifact',aid)
                item={k:s[k] for k in ('path','purpose','authority')};item['artifact']=aid
                if not task.get('execution') and s.get('media_type'):item['media_type']=s['media_type']
                if s.get('visual_reference'):item['visual_reference']=True
                if ref.get('role')=='asset':
                    if task.get('execution',{}).get('capability')!='rhino3dm.run_python':
                        raise ValueError('Additional asset role requires rhino3dm.run_python.')
                    item['media_type']='application/octet-stream'
                versions.append({'artifact':aid,'sha256':s['sha256']})
            else:
                tid=ref['producer'];path=ref['output'];key=('output',tid,path)
                producer=known.get(tid)
                outputs=[o for o in producer.get('outputs',[]) if o['path']==path] if producer else []
                if tid==task['id'] or len(outputs)!=1:raise ValueError('Unknown, ambiguous or self-referencing producer output.')
                c.relative(path);c.relative(tid)
                out=outputs[0]
                item=dict(from_task=tid,output=path,path='upstream/'+tid+'/'+path,
                          purpose=out['purpose'],authority='Unaccepted upstream output; review is required.')
                if out.get('media_type'):item['media_type']=out['media_type']
                dependencies.append(tid)
            if key in seen:raise ValueError('Duplicate artifact binding.')
            seen.add(key);inputs.append(item)
        if any(tid not in known or tid==task['id'] for tid in dependencies):raise ValueError('Invalid ordering dependency.')
        task.pop('input_bindings');task['inputs']=inputs;task['dependencies']=list(dict.fromkeys(dependencies))
        parameter_bindings=[]
        if payload.get('handoff_binding_version')==1 and task.get('execution'):
            from orchestrator.execution import REGISTRY
            spec=REGISTRY.get(task['execution']['capability'],{})
            for name,parameter_value in task['execution']['parameters'].items():
                if not isinstance(parameter_value,dict) or set(parameter_value)!={'input_path'}:continue
                if not name.endswith('_path') or name not in spec.get('parameters',{}):
                    raise ValueError('Input path reference requires a registered path parameter: '+name)
                ref=parameter_value['input_path']
                if not isinstance(ref,dict) or set(ref) not in ({'port'},{'source'},{'producer','output'}):
                    raise ValueError('Input path parameter needs one exact source, port or producer/output reference.')
                resolved=resolve_port(ref,payload,sources)
                matches=[i for i in inputs if (i.get('artifact')==resolved['source'] if 'source' in resolved else
                         i.get('from_task')==resolved['producer'] and i.get('output')==resolved['output'])]
                if len(matches)!=1:raise ValueError('Input path parameter must select one already declared input: '+name)
                task['execution']['parameters'][name]=matches[0]['path']
                parameter_bindings.append(dict(parameter=name,reference=copy.deepcopy(ref),path=matches[0]['path']))
        if task.get('user_gate') and len(task['outputs'])>1:task['selection_outputs']=[o['path'] for o in task['outputs']]
        receipts.append(dict(task=task['id'],selections=original,input_versions=versions,
                             resolved_inputs=copy.deepcopy(inputs),dependencies=task['dependencies']))
        if parameter_bindings:receipts[-1]['parameter_bindings']=parameter_bindings
        if task['id'] in context_ports:receipts[-1]['compiled_context_ports']=context_ports[task['id']]
    return value,receipts
