"""Versioned planner wire shape, separate from executable assignments.

The same bounded JSON Schema is frozen in the request, sent to Gemini's native
structured-output API and checked locally for every provider. Domain validators
still own authorization, operation parameters, graph semantics and budgets.
"""
import copy

from orchestrator.worker_capabilities import CAPABILITIES


def obj(properties, required=(), additional=False):
    return {'type':'object', 'properties':properties, 'required':list(required),
            'additionalProperties':additional}


def array(items):
    return {'type':'array', 'items':items}


def contract(options, builder=None, *, bindings=False):
    text={'type':'string'}
    integer={'type':'integer'}
    opaque={'type':'object'}  # Validated by the owning domain contract.
    common={'path':text, 'purpose':text, 'authority':text, 'media_type':text,
            'visual_reference':{'type':'boolean'}}
    source=obj({**common,'artifact':text}, ('artifact','path','purpose','authority'))
    upstream=obj({**common,'from_task':text,'output':text},
                 ('from_task','output','path','purpose','authority'))
    worker={'requires':array({'type':'string','enum':list(CAPABILITIES)})}
    if not options.get('executor_locked'):
        ids=[x['id'] for x in options.get('worker_catalog',[])]
        if ids:worker['executor']={'type':'string','enum':ids}
    execution=obj({'capability':text,'version':integer,'parameters':opaque},
                  ('capability','version','parameters'))
    browser=obj({'profile':text,'origins':array(text),'interaction_scope':text,
                 'max_tabs':integer,'max_actions':integer,'uploads':array(text),
                 'downloads':array(text),'screenshots':array(text),
                 'session_source':text,'visual_inputs':array(text),
                 'image_sources':array(opaque)},
                ('profile','origins','interaction_scope','max_tabs','max_actions',
                 'uploads','downloads'))
    operations=set(options.get('step_capabilities',[])) | (set(options.get('optional_research_capabilities',[])) & {'web.sources'})
    if 'web.sources' in operations:
        web=obj({'capability':{'type':'string','enum':['web.sources']},
                 'version':{'type':'integer','enum':[1]},
                 'parameters':obj({'queries':array(text),'domains':array(text),
                                   'model':text},('queries','domains'))},
                ('capability','version','parameters'))
        others=sorted(operations-{'web.sources'})
        # Optional research still coexists with other frozen operations. Never
        # let web.sources fall through the opaque generic parameters branch.
        if others:
            execution['properties']['capability']={'type':'string','enum':others}
            execution={'anyOf':[web,execution]}
        else:
            execution=web
    task=obj({
        'id':text, 'role':text, 'objective':text, 'instruction':text,
        'inputs':array({'anyOf':[source,upstream]}),
        'outputs':array(obj({'path':text,'purpose':text,'media_type':text,'handoff':opaque},
                            ('path','purpose'))),
        'dependencies':array(text), 'criteria':array(text),
        'limits':obj({k:integer for k in ('seconds','tool_calls','output_bytes',
                                         'provider_requests','response_tokens')},
                     ('seconds','tool_calls','output_bytes')),
        'max_attempts':integer, 'review_of':text, 'user_gate':text,
        'selection_outputs':array(text), 'tools':array(text),
        'worker':obj(worker, ('requires',)), 'browser':browser,
        'computer':{'anyOf':[obj({'selection':text},('selection',)),
                    obj({'selection':text,'url':text,'allowed_urls':array(text),'max_seconds':integer},
                        ('selection','url','allowed_urls','max_seconds'))]},
        'execution':execution,
        'research':{'anyOf':[obj({'mode':{'type':'string','enum':['profile']}},('mode',)),
            obj({'mode':{'type':'string','enum':['discovery']},'parameters':obj({
                'entity_type':text,'required_fields':array(text),'max_records':integer},
                ('entity_type','required_fields','max_records'))},('mode','parameters'))]},
    }, ('id','role','objective','instruction','outputs',
        'criteria','limits','max_attempts'))
    if bindings:
        from .artifact_bindings import schema as binding_schema
        task['properties'].update(input_bindings=array(binding_schema()),after=array(text))
        for key in ('inputs','dependencies','selection_outputs'):task['properties'].pop(key)
        task['required'].append('input_bindings')
    schema=obj({
        'decision':{'type':'string','enum':['ready','needs_input','blocked']},
        'message':text,
        'plan':{'anyOf':[obj({'brief':text,'tasks':array(task)}, ('brief','tasks')),
                         {'type':'null'}]},
        'input_basis':obj({'mode':{'type':'string','enum':['new','modify_existing']},
                           'artifacts':array(text)}, ('mode','artifacts')),
        'geometry_basis':opaque,
        'design_intent':opaque,
        'deferred_operations':obj({}, additional=text),
        'deliverable_map':obj({}, additional={'anyOf':[
            obj({'task':text,'output':text}, ('task','output')),
            obj({'deferred_operation':text}, ('deferred_operation',))]}),
    }, ('decision','message','plan'))
    if options.get('research_advice_version') == 1:
        schema['properties']['research_advice']=obj({
            'recommended_mode':{'type':'string','enum':['none','sources']},
            'requirement':{'type':'string','enum':['unnecessary','optional','required']},
            'reason':text,'questions':array(text)}, ('recommended_mode','requirement','reason','questions'))
        schema['required'].append('research_advice')
    if builder:
        from .operation_builders import plan_schema
        schema['properties']['plan']={'anyOf':[plan_schema(builder,options),{'type':'null'}]}
        for key in ('deliverable_map','deferred_operations'):schema['properties'].pop(key)
    return {'version':1, 'schema':schema}


def validate(value, schema, path='$'):
    """Check only the JSON Schema keywords emitted above; not a general engine."""
    types={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None),'number':(int,float)}
    if 'anyOf' in schema:
        errors=[]
        branches=[s for s in schema['anyOf'] if 'type' not in s or type(value) in (types[s['type']] if isinstance(types[s['type']],tuple) else (types[s['type']],))]
        for branch in branches or schema['anyOf']:
            try:
                validate(value, branch, path)
                return
            except ValueError as exc:errors.append(str(exc))
        raise ValueError(' OR '.join(errors))
    kind=schema.get('type')
    if kind and type(value) not in (types[kind] if isinstance(types[kind],tuple) else (types[kind],)):
        raise ValueError(path+': expected '+kind+', got '+type(value).__name__+'.')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path+': expected one of '+', '.join(schema['enum'])+'.')
    if kind=='object':
        properties=schema.get('properties',{})
        for key in schema.get('required',[]):
            if key not in value:raise ValueError(path+'.'+key+': required field is missing.')
        for key,item in value.items():
            rule=properties.get(key,schema.get('additionalProperties',True))
            if rule is False:
                raise ValueError(path+'.'+key+': unsupported field; allowed fields: '+', '.join(properties)+'.')
            if isinstance(rule,dict):validate(item,rule,path+'.'+key)
    elif kind=='array':
        for i,item in enumerate(value):validate(item,schema['items'],path+'['+str(i)+']')


def prepare(result, payload, options, *, compiled=False):
    """Compile only redundant, exact locked selectors; never guess user intent.

    Raw provider JSON stays in production_plan_calls (and result for generic plans). Changes apply to a
    copy and are recorded in plan.origin. Unknown/conflicting selectors fail.
    Legacy frozen requests do not acquire a new response contract.
    """
    policy=payload.get('response_contract')
    if policy is None:return copy.deepcopy(result), []
    if policy.get('version')!=1:raise ValueError('Unsupported planner response contract version.')
    proposal=copy.deepcopy(result);bindings=[]
    plan=proposal.get('plan') if isinstance(proposal,dict) else None
    tasks=plan.get('tasks') if isinstance(plan,dict) else None
    if isinstance(tasks,list) and options.get('executor_locked'):
        selected=options['backend']['type']
        catalog=options.get('worker_catalog',[])
        if len(catalog)!=1 or catalog[0]['backend']!=options['backend']:
            raise ValueError('Locked worker catalog does not match the frozen executor.')
        for index,task in enumerate(tasks):
            if not isinstance(task,dict) or 'execution' in task:continue
            path='$.plan.tasks['+str(index)+']'
            worker=task.get('worker')
            holders=[(task,path)]
            if isinstance(worker,dict):holders.append((worker,path+'.worker'))
            for holder,location in holders:
                if 'executor' not in holder:continue
                if holder['executor']!=selected:
                    raise ValueError(location+'.executor: outside the frozen selection; conflicts with frozen executor '+selected+'; no fallback.')
                bindings.append({'path':location+'.executor','value':holder.pop('executor'),
                                 'source':'options.backend','reason':'redundant locked executor'})
    # Advertise only compact bindings for new generations. Retain an explicit
    # all-legacy compatibility path for existing integrations/recovery receipts.
    legacy_bindings=(payload.get('artifact_binding_version')==1 and not payload.get('operation_builder') and isinstance(tasks,list)
                     and all(isinstance(t,dict) and not ({'input_bindings','after'} & set(t)) for t in tasks))
    schema=contract(options)['schema'] if legacy_bindings or (compiled and (payload.get('operation_builder') or payload.get('artifact_binding_version'))) else policy['schema']
    try:validate(proposal,schema)
    except ValueError as exc:
        if not payload.get('operation_builder') or compiled:raise
        from .operation_builders import ContractError
        field,_,expected=str(exc).partition(': ')
        raise ContractError('missing_input' if expected=='required field is missing.' else 'invalid_detail',field,expected) from None
    if isinstance(tasks,list):
        operation=next((item for item in payload.get('graph_operations',[])
                        if item.get('id')=='web.sources'),None)
        for index,task in enumerate(tasks):
            execution=task.get('execution') if isinstance(task,dict) else None
            if not isinstance(execution,dict) or execution.get('capability')!='web.sources':
                continue
            params=execution.get('parameters')
            if isinstance(params,dict) and 'model' not in params:
                model=operation.get('configured_model') if operation else None
                if not operation or not operation.get('available') or not isinstance(model,str) or not model:
                    raise ValueError('The frozen web.sources model is unavailable; no model was inferred.')
                params['model']=model
                bindings.append({'path':'$.plan.tasks['+str(index)+'].execution.parameters.model',
                                 'value':model,'source':'graph_operations.web.sources.configured_model',
                                 'reason':'exact frozen model'})
    return proposal, bindings
