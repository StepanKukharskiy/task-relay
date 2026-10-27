"""One fragment lifecycle for registered operation preparations, not a controller."""
import copy
import hashlib
from . import parameter_contracts as wire, prepared_schemas as schemas

IDENTITY=dict(id='operation.preparation',version=1)
SCALAR_CHUNK = 32


def constraints(p):
    spec=definition(p)
    description=spec['schema'].get('description','Registered document relationships are checked at sealing')
    from .native_apps import SCRIPT_OPERATIONS
    if p['target'] in SCRIPT_OPERATIONS:
        from .host_script import preparation_context
        import json
        runtime=preparation_context(p['target'])
        if runtime:description+='\nRegistered consumer runtime: '+json.dumps(runtime,sort_keys=True)
    return description


def definition(p):
    if (not isinstance(p,dict) or set(p)!={'target','max_records','hash_bindings'} or p['target'] not in schemas.REGISTRY
            or type(p['max_records']) is not int or not 1<=p['max_records']<=100):
        raise ValueError('Invalid registered preparation parameters')
    spec=schemas.REGISTRY[p['target']]
    if not isinstance(p['hash_bindings'],dict) or set(p['hash_bindings'])!=set(spec['hash_inputs']):
        raise ValueError('Preparation requires compiler-bound source hashes')
    return spec


def schema(p):
    spec=definition(p);variants=[]
    for field,rule in spec['schema']['properties'].items():
        base=dict(field=schemas.enum(field))
        if rule.get('type')=='array':
            item_rule=copy.deepcopy(rule['items'])
            for binding in spec.get('item_hashes',[]):
                if binding['field']!=field:continue
                for alternative in item_rule.get('anyOf',[item_rule]):
                    if binding['hash'] in alternative.get('properties',{}):
                        alternative['properties'].pop(binding['hash']);alternative['required'].remove(binding['hash'])
            variants.append(schemas.obj(dict(**base,kind=schemas.enum('append'),index=schemas.integer(0,rule['maxItems']-1),value=item_rule)))
            # Group scalar values only: the native item ceiling stays authoritative.
            # Compound/asset records retain their existing individual bindings.
            if item_rule.get('type') in ('string','integer','number','boolean'):
                variants.append(schemas.obj(dict(**base,kind=schemas.enum('extend'),
                    index=schemas.integer(0,rule['maxItems']-1),
                    values=schemas.array(item_rule,1,min(SCALAR_CHUNK,rule['maxItems'])))))
        elif rule.get('type')=='object' and isinstance(rule.get('additionalProperties'),dict):
            variants.append(schemas.obj(dict(**base,kind=schemas.enum('entry'),key=schemas.text(500,1),value=rule['additionalProperties'])))
        else:variants.append(schemas.obj(dict(**base,kind=schemas.enum('field'),value=rule)))
    variants.append(schemas.obj(dict(kind=schemas.enum('end'))))
    return dict(anyOf=variants,description=constraints(p))


def record(value,p,context=None):
    wire.validate(value,schema(p))
    if value['kind']=='end':return 'end'
    return value['field']+('/'+str(value['index']) if value['kind'] in ('append','extend') else '/'+value['key'] if value['kind']=='entry' else '')


def context(frozen,read):
    by_path={i['path']:i for i in frozen['inputs']}
    for path,item in by_path.items():
        if hashlib.sha256(read(path)).hexdigest()!=item['sha256']:raise ValueError('Preparation source version changed: '+path)
    p=frozen['operation_contract']['parameters'];spec=definition(p);fixed=copy.deepcopy(spec['fixed'])
    for field,path in p['hash_bindings'].items():
        item=by_path.get(path)
        if not item or item.get('media_type')!=spec['hash_inputs'][field]:raise ValueError('Preparation source binding differs')
        fixed[field]=item['sha256']
    return dict(fixed=fixed,assets={p:i.get('media_type') for p,i in by_path.items()},hashes={p:i['sha256'] for p,i in by_path.items()})


def document(store,records):
    p=store.contract['parameters'];spec=definition(p);ctx=store.context();doc=copy.deepcopy(ctx['fixed']);sealed=False
    for key,rule in spec['schema']['properties'].items():
        if key not in spec['schema']['required']:continue
        if rule.get('type')=='array':doc[key]=[]
        elif rule.get('type')=='object' and isinstance(rule.get('additionalProperties'),dict):doc[key]={}
    for value in records:
        record(value,p)
        if sealed:raise ValueError('Preparation fragments cannot follow the completion seal')
        if value['kind']=='end':
            schemas.validate(p['target'],doc,ctx['assets']);sealed=True;continue
        field=value['field']
        if value['kind'] in ('append','extend'):
            doc.setdefault(field,[])
            if value['index']!=len(doc[field]):raise ValueError('Append consecutive field indices')
            if value['kind']=='extend':
                doc[field].extend(copy.deepcopy(value['values']))
                if len(doc[field])>spec['schema']['properties'][field]['maxItems']:
                    raise ValueError('Preparation array exceeds registered item ceiling: '+field)
                continue
            item=copy.deepcopy(value['value'])
            for binding in spec.get('item_hashes',[]):
                if binding['field']!=field or binding['path'] not in item:continue
                path=item[binding['path']]
                if path not in ctx['hashes']:raise ValueError('Preparation item requires an exact declared file: '+path)
                item[binding['hash']]=ctx['hashes'][path]
            doc[field].append(item)
            if len(doc[field])>spec['schema']['properties'][field]['maxItems']:
                raise ValueError('Preparation array exceeds registered item ceiling: '+field)
        elif value['kind']=='entry':doc.setdefault(field,{})[value['key']]=copy.deepcopy(value['value'])
        else:doc[field]=copy.deepcopy(value['value'])
    return doc


def progress(store,records):
    doc=document(store,records);spec=definition(store.contract['parameters'])
    from .contracts import digest
    sealed=bool(records) and records[-1]['kind']=='end'
    try:
        schemas.validate(store.contract['parameters']['target'],doc,store.context()['assets'])
        seal_error=None
    except ValueError as exc:seal_error=str(exc)
    minimum=1+sum(max(0,rule.get('minItems',0)-len(doc.get(key,[]))) if rule.get('type')=='array' else int(key not in doc)
                  for key,rule in spec['schema']['properties'].items() if key in spec['schema']['required'])
    return dict(sealed=sealed,remaining=0 if sealed else minimum,remaining_kind='minimum',
                completion=dict(pending=not sealed,record=dict(kind='end'),ready=seal_error is None,diagnostic=seal_error),
                fragments=[{k:v for k,v in r.items() if k in ('kind','field','index','key')}|dict(record_sha256=digest(r)) for r in records],
                constraints=constraints(store.contract['parameters']),
                missing_fields=[k for k in spec['schema']['required'] if k not in doc],
                next_indices={k:len(doc.get(k,[])) for k,r in spec['schema']['properties'].items() if r.get('type')=='array'},
                target=store.contract['parameters']['target'])


def complete(store,records):
    document(store,records)
    return bool(records) and records[-1]['kind']=='end'


def validate_document(doc):
    # The envelope identifies a family of preparations. Exact target semantics
    # and asset bindings are checked by the frozen producer and consuming port.
    wire.validate(doc,dict(anyOf=[schemas.document_schema(name) for name in schemas.REGISTRY]))


def validate_assignment(task):
    from .executors import FILE_TYPES,request_limit
    p=task['operation_contract']['parameters'];spec=definition(p)
    backend=task.get('backend',task.get('worker',{}).get('backend',{}))
    if (not (backend.get('type') in FILE_TYPES and task.get('tools')==['files'] or backend.get('type')=='codex-cli' and task.get('tools')==['files','shell'])
            or task.get('execution') or task.get('review_of')):
        raise ValueError('Preparation fragments require a declared-file worker')
    output=task['operation_contract']['output']
    outputs=task['outputs']
    if task.get('work_tools',{}).get('preparation',{}):
        from .worker_tools import CONTENT,validate_assignment as validate_work
        validate_work(task)
        outputs=[o for o in outputs if o['path']==CONTENT]
    if len(outputs)!=1 or outputs[0].get('path')!=output or outputs[0].get('media_type')!='application/json':
        raise ValueError('Preparation owns one declared JSON projection')
    from .operation_contracts import REGISTRY
    batch=REGISTRY['operation.preparation',1]['batch']
    reserved=9 if task.get('work_tools') else 2
    if min(request_limit(task),task['limits']['tool_calls'])<(p['max_records']+batch-1)//batch+reserved:
        raise ValueError('Preparation batches and completion exceed the frozen request/tool allowance')
    # At least the required scalar fields and minimum collection items plus seal.
    minimum=1
    for key in spec['schema']['required']:
        rule=spec['schema']['properties'][key]
        minimum+=rule.get('minItems',0) if rule.get('type')=='array' else 0 if isinstance(rule.get('additionalProperties'),dict) else 1
    if minimum>p['max_records']:raise ValueError('Preparation cannot fit the frozen fragment allocation')
    by_path={i['path']:i for i in task['inputs']}
    for field,path in p['hash_bindings'].items():
        if path not in by_path or by_path[path].get('media_type')!=spec['hash_inputs'][field]:raise ValueError('Missing exact preparation baseline')


def register(registry,lifecycle):
    registry['operation.preparation',1]=dict(schema_for=schema,schema=schema(dict(target='web.sources.prepared',max_records=20,hash_bindings={})),
        validate=record,batch=8,validate_assignment=validate_assignment,validate_document=validate_document,local_record_tool=True,
        support_modules=('orchestrator.prepared_schemas',*schemas.support_modules()),
        file_context=dict(mode='assets',input_bytes=100000000,media_types=['image/png','image/jpeg','application/zip',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation','application/x-blender','application/vnd.rhino',
            'audio/mpeg','audio/wav','video/mp4','video/webm']),
        lifecycle=lifecycle.Lifecycle(context=context,maximum=lambda s:s.contract['parameters']['max_records'],
            progress=progress,document=document,complete=complete,require_active=True,export_empty=True,resumable=True,amendable=True,
            instructions='Submit only the registered field, array-item or map-entry fragments. Code chooses the envelope, version and exact baseline hashes. Use consecutive indices per array. For scalar arrays use kind:extend with index and up to 32 values per fragment; this is a lossless contiguous group, not a sample. max_records counts fragments, not array items. Preserve every required item within the unchanged registered document item ceiling. Compound and asset items still use append individually. Correct committed fragments with operation_amend and the exact record_sha256 from progress; originals remain versioned. An amendment changes the preparation version and requires fresh dependent build/inspection. Empty collections are code-owned. Batch up to eight bounded fragments per operation_submit within the declared byte bound. Include kind:end after the last fields/items in the same atomic submission to validate and seal before finish; do not spend the final work call on an unsealed fragment. This does not grant host execution or semantic acceptance.',
            completion_error='Complete and seal the registered preparation before finishing'))
