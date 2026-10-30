"""Job authoring over the existing desktop canvas, registry and admission boundary."""
import copy
import uuid
from orchestrator import contracts, node_spec, parameter_contracts
from orchestrator.operation_definition import catalog, definition

PROTOCOL = 1
TEXT = dict(type='string', minLength=1, maxLength=200)
HASH = dict(type='string', pattern='^[a-f0-9]{64}$')
OBJECT = dict(type='object')
BOOL = dict(type='boolean')


def obj(fields, optional=()):
    return dict(type='object', properties=fields, required=[k for k in fields if k not in optional], additionalProperties=False)


TARGET = obj(dict(kind=dict(type='string',enum=['draft','canvas']),id=TEXT))
BASE = obj(dict(kind=dict(type='string',enum=['new','draft','canvas']),id=dict(anyOf=[TEXT,dict(type='null')]),revision=dict(anyOf=[HASH,dict(type='null')])))
EDIT = obj(dict(target=BASE,title=dict(type='string',minLength=1,maxLength=180),workflow=OBJECT,
                request=dict(type='string',minLength=1,maxLength=20000),request_id=TEXT),('request_id',))
COMMAND = obj(dict(target=TARGET,revision=HASH,scope=TEXT,values=OBJECT,request_id=TEXT))
SCHEMAS = {
    'commands':obj(dict(command=TEXT),('command',)),
    'jobs':obj(dict(offset=dict(type='integer',minimum=0,maximum=1000000),kind=dict(type='string',enum=['draft','job'])),('offset','kind')),
    'open':TARGET,
    'operations':obj(dict(query=dict(type='string',maxLength=100),include_legacy=BOOL),('query','include_legacy')),
    'operation':obj(dict(id=TEXT)),
    'schema':obj({}),
    'edit-preview':EDIT,
    'edit-save':obj(dict(proposal=EDIT,fingerprint=HASH)),
    'files':obj({}),
    'file-import':obj(dict(paths=dict(type='array',items=dict(type='string',minLength=1,maxLength=4000),minItems=1,maxItems=20))),
    'setup':obj({}),
    'run-preview':obj(dict(target=TARGET,revision=HASH,scope=TEXT,values=OBJECT,request_id=TEXT),('request_id',)),
    'run-start':obj(dict(command=COMMAND,fingerprint=HASH,allow_paid=BOOL,
        approve_host_code=dict(type='array',items=obj(dict(node=TEXT,digest=HASH))),
        acknowledge_uncertain=dict(type='array',items=OBJECT))),
    'run-status':obj(dict(run=TEXT)),
    'templates':obj({}),
    'template':obj(dict(id=TEXT)),
}
DESCRIPTIONS = {
    'commands':'List commands, or return the exact input schema for one command.',
    'jobs':'Page saved drafts (default) or workspace jobs. Does not choose a job for you.',
    'open':'Read one exact draft or owning canvas, with revision and editable workflow.',
    'operations':'Search compact registered operation names and descriptions.',
    'operation':'Read one operation: ports, defaults, preparation schemas and runtime guidance.',
    'schema':'Read the canonical workflow and node schemas; no implementation lookup needed.',
    'edit-preview':'Validate proposed workflow and show changes against the exact saved revision; no writes.',
    'edit-save':'Save the exact preview. Retain the original request and prior revision; no execution.',
    'files':'List explicitly selected input files, with exact artifact identities.',
    'file-import':'Register explicitly chosen local files through the existing immutable artifact store.',
    'setup':'Read configured model/tool availability; no connection or credential mutation.',
    'run-preview':'Compile the saved revision for one node ID or all; return exact admission, costs and host-code reviews.',
    'run-start':'Admit the exact reviewed command with explicit paid, host-code and uncertainty choices; no retry loop.',
    'run-status':'Read saved run state, task versions and artifacts; does not advance or retry work.',
    'templates':'List built-in templates.',
    'template':'Read a built-in template without importing or executing it.',
}


def bridge(action,value):
    from .desktop_bridge import dispatch
    return dispatch(action,value)


def validate(action,value):
    if action not in SCHEMAS:raise ValueError('Unknown authoring command; use author commands')
    parameter_contracts.validate(value,SCHEMAS[action],action)


def request_id(value):
    ident=value or str(uuid.uuid4())
    if str(uuid.UUID(ident))!=ident:raise ValueError('Use the exact canonical request_id returned by preview')
    return ident


def open_target(target):
    validate('open',target)
    return bridge('node-draft',{'id':target['id']}) if target['kind']=='draft' else bridge('node-canvas',{'run':target['id']})


def fingerprint(proposal):
    operations=sorted({n['operation'] for n in proposal['workflow']['tasks']})
    return contracts.digest(dict(proposal=proposal,node_schema=node_spec.schema(3),
        operations={op:definition(op) for op in operations}))


def preview(value):
    validate('edit-preview',value)
    p=copy.deepcopy(value);p['request_id']=request_id(p.get('request_id'))
    if not p['title'].strip() or not p['request'].strip():raise ValueError('Supply a title and the exact change request')
    base=p['target'];old=None
    if base['kind']=='new':
        if base['id'] is not None or base['revision'] is not None:raise ValueError('A new draft has null id and revision')
    else:
        if base['id'] is None or base['revision'] is None:raise ValueError('Select an exact saved job revision')
        old=open_target(dict(kind=base['kind'],id=base['id']))
        if old['revision']!=base['revision']:raise ValueError('Job changed; reopen it before preparing the edit')
    args=dict(workflow=p['workflow'])
    if base['kind']=='canvas':args['canvas']=base['id']
    checked=bridge('node-validate',args)['validation'];p['workflow']=checked['document']
    before={n['id']:n for n in old['workflow']['tasks']} if old else {}
    after={n['id']:n for n in p['workflow']['tasks']}
    changes=dict(added=sorted(after.keys()-before.keys()),removed=sorted(before.keys()-after.keys()),
        changed=sorted(k for k in before.keys()&after.keys() if before[k]!=after[k]),
        title_changed=old is None or old['title']!=p['title'],
        workflow_inputs_changed=old is None or old['workflow']['inputs']!=p['workflow']['inputs'])
    return dict(proposal=p,fingerprint=fingerprint(p),changes=changes,validation=checked,execution_authorized=False)


def save(value):
    """Called inside the desktop updater mutation lock. Canvas owns its transaction."""
    validate('edit-save',value)
    p=value['proposal']
    if 'request_id' not in p:raise ValueError('Save the exact proposal returned by edit-preview')
    request_id(p['request_id'])
    if fingerprint(p)!=value['fingerprint']:raise ValueError('Proposal or operation contract changed; preview again')
    receipt=dict(request=p['request'],request_id=p['request_id'],base=copy.deepcopy(p['target']),fingerprint=value['fingerprint'])
    base=p['target'];kind='draft' if base['kind']=='new' else base['kind']
    ident=uuid.UUID(p['request_id']).hex if base['kind']=='new' else base['id']
    # Observe an exact completed save without rewriting a newer revision.
    if base['kind']=='new':
        from .relay_paths import PATHS
        exists=(PATHS.data/'node-drafts'/(ident+'.json')).is_file()
    else:exists=True
    if exists:
        current=open_target(dict(kind=kind,id=ident))
        if current.get('authoring')==receipt:return dict(current,target=dict(kind=kind,id=ident),reused=True,execution_authorized=False)
    checked=preview(p)
    if checked['fingerprint']!=value['fingerprint']:raise ValueError('Normalized proposal changed; preview again')
    settings=dict(revision=base['revision'],title=p['title'],workflow=p['workflow'])
    if kind=='draft':
        from .desktop_node_drafts import dispatch
        result=dispatch('node-draft-save',dict(settings,id=base['id']),authoring=receipt)
    else:
        from .desktop_node_runs import save_canvas
        result=save_canvas(dict(settings,run=base['id']),authoring=receipt)
    return dict(result,target=dict(kind=kind,id=ident),execution_authorized=False)


def run_command(value):
    target=value['target']
    command=dict(revision=value['revision'],scope=value['scope'],values=value['values'],request_id=request_id(value.get('request_id')))
    command['id' if target['kind']=='draft' else 'canvas']=target['id']
    return command


def dispatch(action,value):
    validate(action,value)
    if action=='commands':
        if value:
            name=value['command']
            if name not in SCHEMAS:raise ValueError('Unknown authoring command')
            return dict(command=name,description=DESCRIPTIONS[name],input_schema=SCHEMAS[name])
        return dict(protocol=PROTOCOL,commands=DESCRIPTIONS,input='JSON via --input FILE or --input -',
            scope='Local saved jobs; data and paths are private. Saving never grants execution.')
    if action=='schema':return dict(workflow=node_spec.workflow_schema(),node=node_spec.schema(3))
    if action=='operation':
        row=catalog(operations=[value['id']],include_legacy=True)[0]
        return dict(operation=row,contract_sha256=contracts.digest(row['definition']),execution_authorized=False)
    if action=='operations':
        query=value.get('query','').casefold()
        return dict(operations=[{k:r[k] for k in ('id','title','category','legacy','replaced_by')} | {'description':r['definition'].get('description',r['title'])}
            for r in catalog(include_legacy=value.get('include_legacy',False))
            if query in (r['id']+' '+r['title']+' '+r['definition'].get('description','')).casefold()],execution_authorized=False)
    if action=='jobs':
        offset=value.get('offset',0)
        if value.get('kind','draft')=='job':
            page=bridge('workspace-jobs',dict(offset=offset))
            return {k:page[k] for k in ('items','total','next_offset')}
        items=sorted(bridge('node-drafts',{})['items'],key=lambda x:(-x['stamp'],x['id']))
        return dict(items=items[offset:offset+40],total=len(items),next_offset=offset+40 if offset+40<len(items) else None)
    if action=='open':return dict(open_target(value),target=value,execution_authorized=False)
    if action=='edit-preview':return preview(value)
    if action=='edit-save':return bridge('node-author-save',value)
    if action=='run-preview':
        command=run_command(value);checked=bridge('node-run-preview',command)
        public=dict(value,request_id=command['request_id'])
        return dict(command=public,preview=checked,execution_authorized=False)
    if action=='run-start':
        args=run_command(value['command'])
        args.update({k:value[k] for k in ('fingerprint','allow_paid','approve_host_code','acknowledge_uncertain')})
        return bridge('node-run-start',args)
    actions={'files':'node-files','file-import':'node-file-import','setup':'node-setup',
             'run-status':'workspace-detail','templates':'node-templates','template':'node-template'}
    return bridge(actions[action],value)
