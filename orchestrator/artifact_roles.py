"""Code-owned consumption, inspection and provenance bindings; no execution authority.

An assignment may inspect evidence that none of its native operations consume.
Representation proofs are supplied by registered adapters, never guessed from names.
"""
import copy
import hashlib
from . import contracts as c, execution


class CompatibilityError(ValueError):
    def __init__(self,item,role,origin,check,remedy):
        self.diagnostic=dict(artifact=item.get('artifact'),path=item.get('path','<unbound>'),media_type=item.get('media_type'),
            role=role,origin=origin,failed_check=check,remedy=remedy,model_correctable=origin['kind']=='selected')
        super().__init__('Artifact compatibility: '+c.encoded(self.diagnostic))


def supplied_json_port(task, name):
    """A single registered content port comes from its declared preceding step.

    Original JSON remains inspectable context, not a second renderer manifest.
    Ambiguous preceding outputs still fail normal input admission.
    """
    from .producer_binding import requirements
    step=task['work_tools']['steps'][name]
    ports=requirements(step['operation'])
    if len(ports)!=1 or ports[0]['selector']!='json':return False
    return any(output.get('media_type')=='application/json'
               for source in step.get('from_steps',[])
               for output in task['work_tools']['steps'][source]['outputs'].values())


def supplied_single_port(task,name):
    """A registered one-file consumer takes its current preceding result only."""
    step=task['work_tools']['steps'][name];spec=execution.REGISTRY[step['operation']]
    if spec.get('max_inputs')!=1:return False
    values=[o for source in step.get('from_steps',[]) for o in task['work_tools']['steps'][source]['outputs'].values()
            if o.get('media_type') in spec['input_types']]
    return len(values)==1


def bind(task,rt,closure):
    if not (task.get('work_tools') or task.get('operation_contract') or task.get('records')):return
    from .worker_capabilities import has_binary
    from .operation_adapters import resolve
    from .handoff_closure import capture
    inherited={v['path']:v for receipt in closure if receipt['task']==task['id'] for v in receipt['inherited']}
    views={}
    # Hooks can bind only files already authorized in this assignment. No ancestor
    # import or discovery happens here; closure and job authorization own that scope.
    hooks={execution.adapter(cap).evidence_views for cap,spec in execution.REGISTRY.items() if spec.get('review_evidence')}
    for hook in sorted(h for h in hooks if h):views.update(resolve(hook)(rt,task['inputs']))
    work=task.get('work_tools');build=work['steps']['build']['operation'] if work else None
    spec=execution.REGISTRY[build] if build else {}
    assets=capture([build]).get(build,[]) if build else [];prepared=bool(work and work['preparation'])
    rows={}
    for item in task['inputs']:
        path=item['path'];origin=dict(kind='inherited',via=list(inherited[path]['via'])) if path in inherited else dict(kind='selected')
        inspection=None
        if not has_binary(dict(inputs=[item])):inspection=dict(tool='file_read',path=path)
        elif item.get('media_type') in ('image/png','image/jpeg','application/zip'):
            inspection=dict(tool='image_view',path=path)
        elif path in views:inspection=views[path]
        elif not work or work['version']>=2:inspection=dict(tool='artifact_inspect',path=path)
        if inspection is None:
            raise CompatibilityError(item,'inspection_evidence',origin,'No granted reader or exact registered representation',
                'Bind an authorized exact inspection representation or repair the registered evidence route; do not discard required review evidence')
        # Linked historic render outputs are inspection evidence, never build assets.
        render_evidence=path in views or any(v['path']==path for v in views.values())
        consumes=[]
        if work and not render_evidence and ((prepared and item.get('media_type') in assets) or
                (not prepared and origin['kind']=='selected' and item.get('media_type') in spec['input_types'])):
            consumes=['build']
        if work and work['version']>=2 and origin['kind']=='selected' and not render_evidence:
            consumes=[name for name,step in task['work_tools']['steps'].items() if item.get('media_type') in execution.REGISTRY[step['operation']]['input_types'] and (name!='build' or not prepared or item.get('media_type') in assets)]
        if item.get('media_type')=='application/json':
            consumes=[name for name in consumes if not supplied_json_port(task,name)]
        if work:consumes=[name for name in consumes if not supplied_single_port(task,name)]
        if work and work['version']==3 and work['intent'].get('data') and path!=work['intent']['data']:
            if item.get('media_type') not in assets:consumes=[n for n in consumes if n!='build']
        rows[path]=dict(origin=origin,consumes=consumes,inspection=inspection,
            provenance={k:item[k] for k in ('artifact','from_task','output') if k in item})
    task['artifact_roles']=dict(version=1,inputs=rows,results={o['path']:dict(media_type=o['media_type']) for o in task['outputs']})
    validate(task)


def validate(task):
    roles=task.get('artifact_roles')
    if not roles:return
    if not (task.get('work_tools') or task.get('operation_contract') or task.get('records')) or roles.get('version')!=1 or set(roles)!={'version','inputs','results'}:raise ValueError('Invalid artifact role binding')
    items={i['path']:i for i in task['inputs']}
    if set(roles['inputs'])!=set(items) or roles['results']!={o['path']:dict(media_type=o['media_type']) for o in task['outputs']}:raise ValueError('Artifact roles differ from exact assignment files')
    for path,row in roles['inputs'].items():
        item=items[path];view=row['inspection']
        if set(row)!={'origin','consumes','inspection','provenance'} or row['origin'].get('kind') not in ('selected','inherited'):raise ValueError('Invalid artifact role or inheritance origin')
        if row['provenance']!={k:item[k] for k in row['provenance'] if k in item}:raise ValueError('Artifact role provenance changed')
        if view['path'] not in items or view['tool'] not in ('file_read','image_view','artifact_inspect'):raise ValueError('Evidence inspection route is outside assignment')
        if view['path']!=path:
            proof=view.get('proof',{})
            if proof.get('artifact')!=item.get('artifact') or proof.get('representation')!=items[view['path']].get('artifact'):raise ValueError('Evidence representation identity changed')
            target=roles['inputs'][view['path']]['inspection']
            if target['path']!=view['path']:raise ValueError('Evidence representation must be direct, not cyclic')
        for step in row['consumes']:
            if not task.get('work_tools'):raise ValueError('Evidence-only assignments cannot grant operation consumption')
            cap=task['work_tools']['steps'][step]['operation']
            if item.get('media_type') not in execution.REGISTRY[cap]['input_types']:
                raise CompatibilityError(item,'operation_input',row['origin'],'Format is outside '+cap+' input contract','Choose an input accepted by this operation')


def compatible(task,capabilities,*,diagnose=True):
    validate(task)
    for path,row in task['artifact_roles']['inputs'].items():
        need='images.view' if row['inspection']['tool']=='image_view' else 'files.text'
        if need not in capabilities:
            if not diagnose:return False
            item=next(i for i in task['inputs'] if i['path']==path)
            raise CompatibilityError(item,'inspection_evidence',row['origin'],'Granted worker lacks '+need,'Select an already authorized worker with '+need)
    return True


def validate_tools(task,tools):
    """Fail before model dispatch if a bound inspection route is hidden."""
    validate(task)
    names={tool['name'] for tool in tools}
    for path,row in task.get('artifact_roles',{}).get('inputs',{}).items():
        if row['inspection']['tool'] not in names:
            raise ValueError('Declared inspection route is absent from worker tools: '+path+' -> '+row['inspection']['tool'])


def operation_inputs(task,step):
    """Prepared-content adapters and execution share the same consumed-file view."""
    rows=task.get('artifact_roles',{}).get('inputs')
    if rows is None:return task['inputs']
    validate(task)
    return [i for i in task['inputs'] if step in rows[i['path']]['consumes']]


def content_inputs(task):
    """Registered record assets are separate from native operation consumption."""
    if task.get('work_tools'):return operation_inputs(task,'build')
    if not task.get('artifact_roles'):return task['inputs']
    from .executors import asset_policy
    media=asset_policy(task).get('media_types',[])
    roles=task.get('artifact_roles')
    representations=set()
    if roles:
        validate(task)
        for path,row in roles['inputs'].items():
            if row['inspection'].get('proof'):
                representations.update((path,row['inspection']['path']))
    return [i for i in task['inputs'] if i.get('media_type') in media and i['path'] not in representations]


def verify(rt,task):
    """Recheck exact renderer provenance before freeze, not just model file shapes."""
    if not task.get('artifact_roles'):return
    validate(task)
    from .operation_adapters import resolve
    views={}
    hooks={execution.adapter(cap).evidence_views for cap,spec in execution.REGISTRY.items() if spec.get('review_evidence')}
    for hook in sorted(h for h in hooks if h):views.update(resolve(hook)(rt,task['inputs']))
    for path,row in task['artifact_roles']['inputs'].items():
        if row['inspection'].get('proof') and views.get(path)!=row['inspection']:raise ValueError('Evidence representation no longer matches its exact registered receipt')


def view(files,path):
    row=getattr(files,'frozen',{}).get('artifact_roles',{}).get('inputs',{}).get(path)
    if not row:return None
    route=row['inspection'];proof=route.get('proof')
    if proof:
        for p,key in ((path,'sha256'),(route['path'],'representation_sha256')):
            if hashlib.sha256(files.read_bytes(p)).hexdigest()!=proof[key]:raise ValueError('Exact evidence representation changed')
    return copy.deepcopy(route)
