"""Compile selected source/output references into assignment bindings."""
import copy
from orchestrator import contracts as c

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


def schema():
    from .planning_contract import obj
    text={'type':'string'}
    return {'anyOf':[obj({'source':text,'role':{'type':'string','enum':['asset']}},('source',)),
                     obj({'producer':text,'output':text},('producer','output'))]}


def build(result,payload):
    value=copy.deepcopy(result);plan=value.get('plan');receipts=[]
    if not isinstance(plan,dict) or not isinstance(plan.get('tasks'),list):return value,receipts
    sources={s['artifact']:s for s in payload['sources']+payload.get('available_sources',[])}
    tasks=plan['tasks'];known={t.get('id'):t for t in tasks}
    if len(known)!=len(tasks):raise ValueError('Binding task IDs must be distinct.')
    for task in tasks:
        if 'input_bindings' not in task:continue
        if any(k in task for k in ('inputs','dependencies','selection_outputs')):
            raise ValueError('input_bindings cannot be combined with authored inputs, dependencies or selection_outputs.')
        original=copy.deepcopy(task['input_bindings']);selected=list(original)
        if task.get('review_of'):
            producer=known.get(task['review_of'])
            if producer is None:raise ValueError('Unknown review producer.')
            for output in producer['outputs']:
                ref={'producer':producer['id'],'output':output['path']}
                if ref not in selected:selected.append(ref)
        inputs=[];dependencies=list(task.pop('after',[]));seen=set();versions=[]
        for ref in selected:
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
        if task.get('user_gate') and len(task['outputs'])>1:task['selection_outputs']=[o['path'] for o in task['outputs']]
        receipts.append(dict(task=task['id'],selections=original,input_versions=versions,
                             resolved_inputs=copy.deepcopy(inputs),dependencies=task['dependencies']))
    return value,receipts
