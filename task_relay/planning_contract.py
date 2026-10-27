"""Versioned planner wire shape, separate from executable assignments.

The same bounded JSON Schema is frozen in the request, sent to Gemini's native
structured-output API and checked locally for every provider. Domain validators
still own authorization, operation parameters, graph semantics and budgets.
"""
import copy

from orchestrator.worker_capabilities import CAPABILITIES


# Version 2 extends the record planner with subject schemas and retains every
# version-1 operation. This explicit compatibility relation leaves captured
# connector definitions intact; unknown future versions acquire no operations.
SCOPE_COMPATIBILITY={'record_interfaces_version':{1:(1,2)}}


def compatible_scope(scope, requirements):
    return all(scope.get(key) in SCOPE_COMPATIBILITY.get(key,{}).get(version,(version,))
               for key,version in requirements.items())


def obj(properties, required=(), additional=False):
    return {'type':'object', 'properties':properties, 'required':list(required),
            'additionalProperties':additional}


def array(items):
    return {'type':'array', 'items':items}

def operation_capabilities(selected,scope):
    """Shared companion scope for wire schemas, compilation and workflow Start."""
    result=set(selected)
    if scope.get('prepared_research_policy_version')==1 and 'web.sources' in result:result.add('web.sources.prepared')
    if scope.get('sourcing_records_version',0)>=2 and 'pptx.create' in result:result.add('sourcing.slides')
    if scope.get('record_interfaces_version') in (1,2) and 'pptx.create' in result:result.add('collection.slides')
    recovery=scope.get('completion_recovery',{}).get('policy',{})
    if recovery.get('version')==3 or scope.get('delivery_completion_policy_version')==1:
        from orchestrator.execution import REGISTRY
        for capability in list(result):result.update(REGISTRY.get(capability,{}).get('completion_companions',{}))
    if scope.get('connector_companions_version')==1:
        from orchestrator.execution import REGISTRY
        for capability in list(result):result.update(REGISTRY.get(capability,{}).get('companions',{}))
    from orchestrator.execution import REGISTRY
    result={cap for cap in result if compatible_scope(scope,REGISTRY.get(cap,{}).get('scope_versions',{}))}
    return result


def unused_completion_companions(selected, actual, payload):
    """Optional helpers belong to an executed owner, never stand-alone outcomes.

    Owners may be current operations or receipt-bound reused reads; the caller
    must validate reuse before saving or dispatching. Use metadata captured in
    this request, not a newer live registry. Legacy
    stages and missing owners keep their original selected-operation obligations.
    Deliverable binding independently requires every requested reviewed output.
    """
    if (payload.get('connector_companions_version')!=1
            or payload.get('delivery_completion_policy_version')!=1):return {}
    companions={}
    for spec in payload.get('graph_operations',[]):
        if spec.get('id') not in actual:continue
        for capability,reason in spec.get('completion_companions',{}).items():
            if capability in selected and capability not in actual:
                companions[capability]={'owner':spec['id'],'reason':reason}
    return companions


def contract(options, builder=None, *, bindings=False):
    from orchestrator.handoff_contracts import descriptor_schema
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
    image_subject=obj({'id':text,'label':text,'query':text,'identity':text,
                       'exclude_titles':array(text)},('id','label','query'))
    image_grant=obj({'path':text,'subjects':array(image_subject)},('path','subjects'))
    from orchestrator.browser_action_sets import ACTION_SETS
    custom_action=obj({'name':{'type':'string','enum':list(ACTION_SETS)},
                       'mode':{'type':'string','enum':['observe','interact']}},('name','mode'))
    custom_action['description']='Registered DOM controls. observe permits recognition only; interact requires explicit user authorization within interaction_scope, including any generation or spending.'
    browser=obj({'profile':text,'origins':array(text),'interaction_scope':text,
                 'max_tabs':integer,'max_actions':integer,'uploads':array(text),
                 'downloads':array(text),'screenshots':array(text),
                 'session_source':text,'visual_inputs':array(text),
                 'image_sources':array(image_grant),'custom_actions':array(custom_action),
                 'visual_actions':array({'type':'string','enum':['click','scroll','drag'],'description':'Optional visual fallback within existing interaction_scope. Requires declared screenshot output pairs and a vision-capable model. An empty list permits screenshot vision only.'})},
                ('profile','origins','interaction_scope','max_tabs','max_actions',
                 'uploads','downloads'))
    operations=operation_capabilities(set(options.get('step_capabilities',[])) | (set(options.get('optional_research_capabilities',[])) & {'web.sources','web.sources.prepared'}),options)
    typed=[]
    if options.get('connector_companions_version')==1:
        from orchestrator.execution import REGISTRY,parameter_schema
        for capability in sorted(operations & set(REGISTRY)):
            parameters=copy.deepcopy(parameter_schema(capability))
            if parameters is None:continue
            if bindings and options.get('handoff_binding_version')==1:
                reference={'anyOf':[obj({'port':text},('port',)),obj({'source':text},('source',)),obj({'producer':text,'output':text},('producer','output'))]}
                for name,shape in list(parameters['properties'].items()):
                    if name.endswith('_path'):parameters['properties'][name]={'anyOf':[shape,obj({'input_path':reference},('input_path',))]}
            typed.append(obj({'capability':{'type':'string','enum':[capability]},'version':{'type':'integer','enum':[REGISTRY[capability]['version']]},'parameters':parameters},('capability','version','parameters')))
        operations-=set(v['properties']['capability']['enum'][0] for v in typed)
        if operations:execution['properties']['capability']={'type':'string','enum':sorted(operations)}
    if operations & {'web.sources','web.sources.prepared'}:
        web=obj({'capability':{'type':'string','enum':['web.sources']},
                 'version':{'type':'integer','enum':[1]},
                 'parameters':obj({'queries':array(text),'domains':array(text),
                                   'model':text},('queries','domains'))},
                ('capability','version','parameters'))
        prepared=obj({'capability':{'type':'string','enum':['web.sources.prepared']},
                      'version':{'type':'integer','enum':[1]},
                      'parameters':obj({'domains':array(text),'model':text},('domains',))},
                     ('capability','version','parameters'))
        variants=([web] if 'web.sources' in operations else [])+([prepared] if 'web.sources.prepared' in operations else [])
        others=sorted(operations-{'web.sources','web.sources.prepared'})
        # Optional research still coexists with other frozen operations. Never
        # let web.sources fall through the opaque generic parameters branch.
        if others:
            execution['properties']['capability']={'type':'string','enum':others}
            execution={'anyOf':variants+[execution]}
        else:
            execution=variants[0] if len(variants)==1 else {'anyOf':variants}
    if typed:
        if operations:execution={'anyOf':typed+[execution]}
        else:execution=typed[0] if len(typed)==1 else {'anyOf':typed}
    task=obj({
        'id':text, 'role':text, 'objective':text, 'instruction':text,
        'inputs':array({'anyOf':[source,upstream]}),
        'outputs':array(obj({'path':text,'purpose':text,'media_type':text,'handoff':descriptor_schema()},
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
    if options.get('sourcing_records_version') in (1,2):
        from .sourcing_planning import schema as sourcing_schema
        task['properties']['sourcing']=sourcing_schema(options['sourcing_records_version']>=2)
    if options.get('record_interfaces_version') in (1,2):
        from .record_planning import schema as records_schema
        task['properties']['records']=records_schema(options['record_interfaces_version'])
    if options.get('producer_binding_version')==1:
        from orchestrator.producer_binding import semantic_schema
        task['properties']['content_parameters']=semantic_schema()
    if bindings:
        from .artifact_bindings import schema as binding_schema
        task['properties'].update(input_bindings=array(binding_schema(ports=options.get('handoff_binding_version')==1,
            asset_roles='rhino3dm.run_python' in operation_capabilities(set(options.get('step_capabilities',[])),options))),after=array(text))
        for key in ('inputs','dependencies','selection_outputs'):task['properties'].pop(key)
        task['required'].append('input_bindings')
    schema=obj({
        'decision':{'type':'string','enum':['ready','needs_input','blocked']},
        'message':text,
        'plan':{'anyOf':[obj({'brief':text,'tasks':array(task)}, ('brief','tasks')),
                         {'type':'null'}]},
        'input_basis':{'anyOf':[
            obj({'mode':{'type':'string','enum':['new']},'artifacts':{**array(text),'maxItems':0}},('mode','artifacts')),
            obj({'mode':{'type':'string','enum':['modify_existing']},'artifacts':{**array(text),'minItems':1}},('mode','artifacts'))]},
        'geometry_basis':opaque,
        'deferred_operations':obj({}, additional=text),
        'reused_operations':obj({}, additional=array(text)),
        'deliverable_map':obj({}, additional={'anyOf':[
            obj({'task':text,'output':text}, ('task','output')),
            obj({'deferred_operation':text}, ('deferred_operation',))]}),
    }, ('decision','message','plan'))
    if options.get('design_intent'):
        schema['properties']['design_intent']=opaque
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


class ValidationError(ValueError):
    def __init__(self,field,expected):
        self.field=field;self.expected=expected
        super().__init__(field+': '+expected)
    def receipt(self):return dict(version=1,phase='compile',status='correction_needed',code='invalid_field',field=self.field,expected=self.expected,effect='none')


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
            except ValueError as exc:errors.append(exc)
        if len(errors)==1:raise errors[0]
        raise ValueError(' OR '.join(map(str,errors)))
    kind=schema.get('type')
    if kind and type(value) not in (types[kind] if isinstance(types[kind],tuple) else (types[kind],)):
        raise ValidationError(path,'expected '+kind+', got '+type(value).__name__+'.')
    if 'enum' in schema and value not in schema['enum']:
        raise ValidationError(path,'expected one of '+', '.join(str(v) for v in schema['enum'])+'.')
    if kind=='object':
        properties=schema.get('properties',{})
        for key in schema.get('required',[]):
            if key not in value:raise ValidationError(path+'.'+key,'required field is missing.')
        for key,item in value.items():
            rule=properties.get(key,schema.get('additionalProperties',True))
            if rule is False:
                raise ValidationError(path+'.'+key,'unsupported field; allowed fields: '+', '.join(properties)+'.')
            if isinstance(rule,dict):validate(item,rule,path+'.'+key)
    elif kind=='array':
        if 'minItems' in schema and len(value)<schema['minItems']:raise ValidationError(path,'too few items.')
        if 'maxItems' in schema and len(value)>schema['maxItems']:raise ValidationError(path,'too many items.')
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
    if (isinstance(proposal,dict) and not payload.get('design_intent_policy')
            and proposal.get('design_intent')=={}):
        proposal.pop('design_intent')
        bindings.append({'path':'$.design_intent','before':{},'source':'disabled frozen design-intent policy',
                         'reason':'empty historical optional annotation adds no requirements'})
    plan=proposal.get('plan') if isinstance(proposal,dict) else None
    tasks=plan.get('tasks') if isinstance(plan,dict) else None
    basis=proposal.get('input_basis') if isinstance(proposal,dict) else None
    if (payload.get('connector_companions_version')==1 and isinstance(tasks,list)
            and isinstance(basis,dict) and basis.get('mode')=='new'
            and isinstance(basis.get('artifacts'),list) and basis['artifacts']):
        # New documents may use sources without modifying a baseline. Correct
        # only this redundant annotation when all those exact IDs remain bound.
        selected=set();ports=payload.get('input_ports',{})
        for task in tasks:
            if not isinstance(task,dict):continue
            for binding in task.get('input_bindings',[]):
                if not isinstance(binding,dict):continue
                artifact=binding.get('source') or ports.get(binding.get('port'),{}).get('artifact')
                if isinstance(artifact,str):selected.add(artifact)
            selected.update(i['artifact'] for i in task.get('inputs',[]) if isinstance(i,dict) and isinstance(i.get('artifact'),str))
        ids=basis['artifacts'];known={s['artifact'] for s in payload.get('sources',[])}
        if all(isinstance(i,str) for i in ids) and len(ids)==len(set(ids)) and set(ids)<=selected&known:
            basis['artifacts']=[]
            bindings.append({'path':'$.input_basis.artifacts','before':ids,'value':[],
                'source':'input_basis.mode=new and exact assignment input bindings',
                'reason':'source references remain selected; new work has no modification baseline'})
    if isinstance(tasks,list) and payload.get('connector_companions_version')==1:
        # Registered record formats own procedural checks for both members of
        # the pair. Preserve model proposals as audit data, not a second schema.
        from orchestrator.operation_contracts import REGISTRY
        for task in tasks:
            if not isinstance(task,dict) or task.get('review_of'):continue
            intent=task.get('records',{}).get('family',{})
            if task.get('sourcing',{}).get('kind')=='inventory':intent={'id':'sourcing.inventory','version':1}
            family=REGISTRY.get((intent.get('id'),intent.get('version')), {})
            expected=family.get('planning_criteria')
            if not expected:continue
            for member in [task]+[r for r in tasks if isinstance(r,dict) and r.get('review_of')==task.get('id')]:
                before=member.get('criteria')
                if not isinstance(before,list) or before==expected:continue
                member['criteria']=copy.deepcopy(expected)
                bindings.append(dict(path='$.plan.tasks['+str(tasks.index(member))+'].criteria',before=before,value=copy.deepcopy(expected),
                    source='registered record contract '+intent['id'],proposal_criteria_authority='audit_only',
                    reason='Exact user request and assignment scope remain authoritative; registered format checks cannot be redefined by proposed or historical review criteria.'))
        # Empty optional descriptors add no constraints. Bind only their exact
        # declared MIME type; retain nonempty restrictions and raw responses.
        from orchestrator.handoff_contracts import descriptor
        for index,task in enumerate(tasks):
            if not isinstance(task,dict):continue
            for output_index,output in enumerate(task.get('outputs',[])):
                if not isinstance(output,dict) or output.get('handoff')!={} or not isinstance(output.get('media_type'),str):continue
                value={'media_type':output['media_type']};descriptor(value)
                output['handoff']=value
                bindings.append({'path':'$.plan.tasks['+str(index)+'].outputs['+str(output_index)+'].handoff',
                    'before':{},'value':value,'source':'output.media_type',
                    'reason':'bind empty optional descriptor to exact declared output type'})
        # A native operation is one scheduler/tool invocation. Its internal
        # HTTP/provider ceiling belongs to the frozen operation contract.
        from orchestrator.handoff_contracts import operation
        frozen={spec['id']:spec for spec in payload.get('graph_operations',[])}
        for index,task in enumerate(tasks):
            if not isinstance(task,dict) or not isinstance(task.get('execution'),dict):continue
            execution=task['execution'];capability=execution.get('capability');spec=frozen.get(capability)
            if not spec or execution.get('version')!=spec['version']:continue
            bounds=operation(capability,spec)
            criteria=task.get('criteria');expected=spec.get('criteria')
            if isinstance(criteria,list) and isinstance(expected,list) and criteria!=expected:
                reviews=[review for review in tasks if isinstance(review,dict) and review.get('review_of')==task.get('id')]
                task['criteria']=copy.deepcopy(expected)
                bindings.append({'path':'$.plan.tasks['+str(index)+'].criteria','before':criteria,'value':expected,
                    'source':'frozen registered operation '+capability,
                    'semantic_review_task':reviews[0]['id'] if len(reviews)==1 else None,'proposal_criteria_authority':'audit_only',
                    'reason':'registered native checks are authoritative, including intermediate operations; retain proposed checks in this receipt without promoting them into reviewer requirements'})
            maxima={'seconds':min(bounds['seconds'],options.get('limits',{}).get('seconds',bounds['seconds'])),
                    'output_bytes':bounds['output_bytes'],'tool_calls':1}
            limits=task.get('limits',{})
            if not isinstance(limits,dict):continue
            for key,maximum in maxima.items():
                value=limits.get(key)
                if type(value) is int and value>maximum:
                    limits[key]=maximum
                    bindings.append({'path':'$.plan.tasks['+str(index)+'].limits.'+key,'before':value,'value':maximum,
                        'source':'frozen registered operation '+capability,
                        'reason':'narrow scheduler limits; retain separate registered internal request ceiling'})
    if isinstance(tasks,list) and payload.get('planner_budget_binding_version') in (1,2):
        keys=('seconds','tool_calls','output_bytes') if payload.get('planner_budget_binding_version')==2 else ('output_bytes',)
        for index,task in enumerate(tasks):
            if not isinstance(task,dict) or task.get('execution'):continue
            if payload.get('planner_budget_binding_version')==2:
                maximum=options.get('max_attempts');value=task.get('max_attempts')
                if type(maximum) is int and type(value) is int and value>maximum:
                    task['max_attempts']=maximum
                    bindings.append({'path':'$.plan.tasks['+str(index)+'].max_attempts',
                                     'value':maximum,'before':value,'source':'options.max_attempts',
                                     'reason':'narrow generated allowance to exact frozen maximum'})
            limits=task.get('limits',{})
            if not isinstance(limits,dict):continue
            for key in keys:
                maximum=options.get('limits',{}).get(key)
                value=limits.get(key)
                if type(maximum) is int and type(value) is int and value>maximum:
                    limits[key]=maximum
                    bindings.append({'path':'$.plan.tasks['+str(index)+'].limits.'+key,
                                     'value':maximum,'before':value,'source':'options.limits.'+key,
                                     'reason':'narrow generated allowance to exact frozen maximum'})
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
    if not compiled:
        from .workflow_admission import normalize
        bindings.extend(normalize(proposal,payload,options))
    schema=contract(options)['schema'] if legacy_bindings or (compiled and (payload.get('operation_builder') or payload.get('artifact_binding_version'))) else policy['schema']
    try:validate(proposal,schema)
    except ValueError as exc:
        if not payload.get('operation_builder') or compiled:raise
        from .operation_builders import ContractError
        field,_,expected=str(exc).partition(': ')
        raise ContractError('missing_input' if expected=='required field is missing.' else 'invalid_detail',field,expected) from None
    if isinstance(tasks,list):
        for index,task in enumerate(tasks):
            execution=task.get('execution') if isinstance(task,dict) else None
            if not isinstance(execution,dict) or execution.get('capability') not in ('web.sources','web.sources.prepared'):
                continue
            capability=execution['capability']
            operation=next((item for item in payload.get('graph_operations',[]) if item.get('id')==capability),None)
            params=execution.get('parameters')
            if isinstance(params,dict) and 'model' not in params:
                model=operation.get('configured_model') if operation else None
                if not operation or not operation.get('available') or not isinstance(model,str) or not model:
                    raise ValueError('The frozen '+capability+' model is unavailable; no model was inferred.')
                params['model']=model
                bindings.append({'path':'$.plan.tasks['+str(index)+'].execution.parameters.model',
                                 'value':model,'source':'graph_operations.'+capability+'.configured_model',
                                 'reason':'exact frozen model'})
    return proposal, bindings
