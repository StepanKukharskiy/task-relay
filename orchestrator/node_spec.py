"""The node document contract consumed by admission, model tools and desktop UI.

This compiles into the existing assignments; it owns no queue or execution state.
Legacy saved grants keep their historical declarations.
"""
import copy
import json
from pathlib import Path
from . import contracts as c, parameter_contracts

PATH = Path(__file__).with_name('node.schema.json')


def schema(version=1):
    if version not in (1,2,3):raise ValueError("Unsupported node version")
    path=PATH if version==3 else PATH.with_name('node.v'+str(version)+'.schema.json')
    value = json.loads(path.read_text())
    return {k: v for k, v in value.items() if not k.startswith('$') and k != 'title'}


def validate(node, grant=None):
    parameter_contracts.validate(node, schema(node.get('schema_version',1)), 'node')
    if node.get('schema_version')==3:
        node = bind_fields(node)
    if node.get('schema_version') in (2,3):
        from .operation_definition import lower
        lower(node,grant)
    names = [o['name'] for o in node.get('outputs', [])]
    if len(names) != len(set(names)):
        raise ValueError('Node output names must be distinct')
    return copy.deepcopy(node)


def batch_schema(version=1):
    return dict(type='object', properties={'tasks': dict(type='array', items=schema(version), minItems=1, maxItems=29)},
                required=['tasks'], additionalProperties=False)


def legacy_tasks(args, version=1, grant=None, *, artifact=None, producer=None):
    parameter_contracts.validate(args, batch_schema(version), 'node_run')
    value = copy.deepcopy(args)
    if any('model' in item for item in value['tasks']):
        raise ValueError('Per-node models require explicit workflow admission; cannot override the frozen worker grant')
    if version==3:
        inspect_graph(value['tasks'], grant=grant, artifact=artifact, producer=producer)
    for item in value['tasks']:
        checked=validate(item,grant);item.clear();item.update(checked)
        if item.get('schema_version') in (2,3):
            from .operation_definition import lower
            lowered=lower(item,grant);item.clear();item.update(lowered)
        item.pop('schema_version', None)
        if item.get('operation') == 'model':
            item.pop('operation')
    return value


def capture(node):
    node = validate(node)
    version=node.get('schema_version',1)
    result=dict(version=version, schema_sha256=c.digest(schema(version)), document=node)
    if version in (2,3):
        from .operation_definition import definition
        result['operation_sha256']=c.digest(definition(node['operation']))
    return result


def check_capture(value):
    version=value.get('version') if isinstance(value,dict) else None
    keys={'version','schema_sha256','document'} | ({'operation_sha256'} if version in (2,3) else set())
    compatible = version in (1,2,3) and value.get('schema_sha256')==c.digest(schema(version))
    if version==3 and not compatible and 'model' not in value.get('document',{}):
        prior=schema(3);prior['properties'].pop('model',None)
        compatible=value['schema_sha256']==c.digest(prior)
    if (version not in (1,2,3) or set(value)!=keys or not compatible):
        raise ValueError('Unsupported or changed node contract')
    if version in (2,3):
        from .operation_definition import matches_capture
        if not matches_capture(value['document']['operation'],value['operation_sha256'],value['document']):
            raise ValueError('Changed operation definition')
    return validate(value['document'])


def artifact_inputs(node):
    if node.get('schema_version',1)==1:return node.get('inputs',[])
    return [v for v in node['inputs'].values() if set(v)=={'artifact'}]


def matches_artifact_inputs(node, inputs):
    """Compare exact bindings independent of serialized object-key order.

    Retain multiplicity: a set comparison would silently allow omitted or
    additional repeated bindings. Named ports remain in the captured document.
    """
    return sorted(c.encoded(v) for v in artifact_inputs(node)) == sorted(c.encoded(v) for v in inputs)


def presentation(capture_value):
    """UI fields and port declarations come from the admitted document, not guesses."""
    document = check_capture(capture_value)
    from .operation_definition import definition,presentation as operation_presentation
    named=document.get('schema_version') in (2,3)
    return dict(operation=definition(document['operation']) if named else None,
                presentation=operation_presentation(document['operation']) if named else None,
                document=document, schema=schema(capture_value["version"]), schema_sha256=capture_value['schema_sha256'])


def field_schema():
    return copy.deepcopy(schema(3)['properties']['input_definitions']['additionalProperties'])


def field_value(value, field, path):
    if field['type']=='artifact':
        raise ValueError(path+': artifact inputs require an exact reference, not a literal')
    rule={'type':field['type']}
    if field['type']=='array':
        rule['items']=schema(3)['properties']['inputs']['additionalProperties']['anyOf'][2]['properties']['value']
    parameter_contracts.validate(value,rule,path)


def check_fields(fields):
    import re
    parameter_contracts.validate(fields,dict(type='object',additionalProperties=field_schema()),'input definitions')
    for name,field in fields.items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}',name):raise ValueError('Invalid input name: '+name)
        if field['type']=='artifact':
            if 'default' in field:raise ValueError('Artifact defaults must use an explicit saved binding')
            if 'media_type' not in field:raise ValueError('Artifact input needs media_type: '+name)
        elif 'media_type' in field:raise ValueError('Only artifact inputs declare media_type')
        if 'default' in field:field_value(field['default'],field,'default '+name)
    return fields


def bind_fields(node, *, draft=False):
    """Validate the custom interface and apply literal defaults without changing a draft."""
    node=copy.deepcopy(node)
    if 'model' in node:
        from .operation_definition import definition
        if node['operation'] not in ('model','review') and not definition(node['operation']).get('content'):
            raise ValueError('Registered tools use their declared model input, not an AI worker choice')
        if node['model']['provider']!='codex' and 'reasoning' in node['model']:
            raise ValueError('Reasoning setting belongs to the Codex adapter')
    if node['operation']!='model':
        if 'input_definitions' in node:raise ValueError('Registered operation owns its input definitions')
        return node
    if 'input_definitions' not in node:raise ValueError('Model node requires input_definitions')
    fields=check_fields(node['input_definitions'])
    if set(node['inputs'])-set(fields):raise ValueError('Undeclared model input')
    for name,field in fields.items():
        if name not in node['inputs']:
            if 'default' in field:node['inputs'][name]={'value':copy.deepcopy(field['default'])}
            elif field['required'] and not draft:raise ValueError('Missing required input: '+node['id']+'.'+name)
            continue
        binding=node['inputs'][name]
        if 'workflow' in binding:
            if not draft:raise ValueError('Unresolved workflow input: '+binding['workflow'])
        elif 'value' in binding:field_value(binding['value'],field,node['id']+'.'+name)
        elif field['type']!='artifact':raise ValueError('Artifact connection cannot supply a literal input: '+name)
    return node


def workflow_schema():
    return dict(type='object',properties={
        'schema_version':dict(type='integer',enum=[1]),
        'kind':dict(type='string',enum=['workflow']),
        'inputs':dict(type='object',additionalProperties=field_schema()),
        'tasks':batch_schema(3)['properties']['tasks']},
        required=['schema_version','kind','inputs','tasks'],additionalProperties=False)


def run_schema(version):
    direct=batch_schema(version)
    if version!=3:return direct
    # Existing exact-artifact reader owns access and integrity checks.
    saved=dict(type='object',properties={
        'workflow':dict(type='object',properties={'artifact':dict(type='string',minLength=1)},required=['artifact'],additionalProperties=False),
        'values':dict(type='object')},required=['workflow','values'],additionalProperties=False)
    return dict(type='object',properties={**direct['properties'],**saved['properties']},additionalProperties=False,anyOf=[direct,saved])


def inspect_graph(tasks, *, grant=None, artifact=None, producer=None, fields=None, draft=False):
    """Pure UI/admission validation; no scheduling, artifact writes or model inference.

    Registered inputs/outputs use the operation definition. External references
    need the caller's authorized artifact/task lookup; never accept invented ports.
    """
    from .operation_definition import definition,input_rules
    from .owner_intents import ports
    by_id={};outputs={};edges={};missing=[];connections=[]
    for raw in tasks:
        parameter_contracts.validate(raw,schema(3),'node')
        node=bind_fields(raw,draft=draft)
        ident=node['id']
        if ident in by_id:raise ValueError('Duplicate task ID')
        by_id[ident]=node
        spec=definition(node['operation'],grant)
        outputs[ident]=({o['name']:o for o in node.get('outputs',[])} if node['operation']=='model' else spec['outputs'])
        if node['operation']=='model' and (not outputs[ident] or len(outputs[ident])!=len(node['outputs'])):
            raise ValueError('Model node requires distinct named outputs')
        if node['operation']!='model' and 'outputs' in node:raise ValueError('Registered operation owns its output ports')
    def source(ref):
        if 'artifact' in ref:
            if artifact is None:raise ValueError('Artifact lookup required for exact input')
            return artifact(ref['artifact'])
        tid=ref['task']
        if tid not in outputs:
            if producer is None:raise ValueError('Unknown task: '+tid)
            outputs[tid]=ports(producer(tid))
        if ref['output'] not in outputs[tid]:raise ValueError('Unknown named output '+tid+'/'+ref['output'])
        return outputs[tid][ref['output']]
    for ident,node in by_id.items():
        spec=definition(node['operation'],grant)
        edges[ident]=list(node.get('dependencies',[]))
        for dep in edges[ident]:
            if dep not in by_id:
                if producer is None:raise ValueError('Unknown dependency: '+dep)
                producer(dep)
        if node['operation']=='model':
            expected=node['input_definitions'];required=[k for k,v in expected.items() if v['required']]
        else:
            rules=input_rules(spec,node['inputs'])
            expected=rules.get('properties',{});required=rules.get('required',[])
        def connect(name,ref,rule):
            descriptor=source(ref)
            if node['operation']=='model':
                if rule['type']!='artifact' or (rule['media_type']!='*/*' and descriptor.get('media_type')!=rule['media_type']):
                    raise ValueError('Incompatible artifact media type: '+ident+'.'+name)
            else:
                from . import execution
                if node['operation'] in execution.REGISTRY:
                    execution.adapter(node['operation']).bind_reference_media(name,copy.deepcopy(descriptor))
            if 'task' in ref:edges[ident].append(ref['task'])
            connections.append(dict(task=ident,input=name,source=copy.deepcopy(ref),media_type=descriptor.get('media_type')))
        for name in required:
            if name not in node['inputs']:missing.append(ident+'.'+name)
        for name,binding in node['inputs'].items():
            if name not in expected:raise ValueError('Unknown input '+ident+'.'+name)
            rule=expected[name]
            if 'workflow' in binding:
                if fields is None or binding['workflow'] not in fields:raise ValueError('Unknown workflow input')
                field=fields[binding['workflow']]
                if field['type']=='artifact':
                    if node['operation']=='model' and rule.get('type')!='artifact':raise ValueError('File input needs an artifact port')
                    if node['operation']!='model':
                        parameter_contracts.validate({'artifact':'pending-file'},rule,ident+'.'+name)
                    if name in required:missing.append(ident+'.'+name)
                    continue
                if rule.get('type')!=field['type'] and not (rule.get('type')=='number' and field['type']=='integer'):
                    raise ValueError('Incompatible workflow input: '+ident+'.'+name)
                if 'default' in field:
                    if node['operation']=='model':field_value(field['default'],rule,ident+'.'+name)
                    else:parameter_contracts.validate(field['default'],rule,ident+'.'+name)
                elif name in required:missing.append(ident+'.'+name)
                continue
            if 'value' in binding:
                if node['operation']=='model':field_value(binding['value'],rule,ident+'.'+name)
                else:
                    parameter_contracts.validate(binding['value'],rule,ident+'.'+name)
                    from . import execution
                    is_many=(name=='files' or node['operation'] in execution.REGISTRY and execution.adapter(node['operation']).references.get(name)=='paths')
                    if is_many and isinstance(binding['value'],list):
                        for ref in binding['value']:connect(name,ref,rule)
                    elif node['operation'] in execution.REGISTRY and name in execution.adapter(node['operation']).references and isinstance(binding['value'],dict):
                        connect(name,binding['value'],rule)
            else:
                if node['operation']!='model':
                    parameter_contracts.validate(binding,rule,ident+'.'+name)
                connect(name,binding,rule)
        if not draft:validate(node,grant)
    # Reuse the Runtime's dependency rule, with prior tasks treated as existing leaves.
    graph={**{k:[] for values in edges.values() for k in values if k not in by_id},**edges}
    c.validate_dependencies(graph)
    if missing and not draft:raise ValueError('Missing required inputs: '+', '.join(missing))
    return dict(tasks=list(by_id.values()),connections=connections,missing_inputs=missing,ready=not missing)


def resolve_workflow(document, values=None, *, grant=None, artifact=None, producer=None, draft=False):
    """A saved draft plus run values becomes a new bound graph, never a rewritten draft."""
    schema=workflow_schema()
    if values is None:schema['properties']['tasks']['minItems']=0
    parameter_contracts.validate(document,schema,'workflow')
    fields=check_fields(document['inputs'])
    view=inspect_graph(document['tasks'],grant=grant,artifact=artifact,producer=producer,fields=fields,draft=True)
    if values is None:
        if not document['tasks']:view['missing_inputs'].append('workflow.tasks')
        pending=[name for name,field in fields.items() if field['required'] and 'default' not in field]
        view['missing_inputs']+=['workflow.'+name for name in pending]
        view['ready']=not view['missing_inputs']
        return dict(document=copy.deepcopy(document),fields=copy.deepcopy(fields),**view)
    if not isinstance(values,dict) or set(values)-set(fields):raise ValueError('Unknown workflow run input')
    bound={k:copy.deepcopy(values[k] if k in values else v['default']) for k,v in fields.items() if k in values or 'default' in v}
    for name,value in bound.items():
        field=fields[name]
        if field['type']=='artifact':
            if not isinstance(value,dict) or set(value)!={'artifact'} or not isinstance(value['artifact'],str):raise ValueError('Choose a registered file for '+name)
            if artifact is None:raise ValueError('Artifact lookup required for '+name)
            media=artifact(value['artifact']).get('media_type')
            if field['media_type']!='*/*' and media!=field['media_type']:raise ValueError('Incompatible file for '+name)
        else:field_value(value,field,'workflow input '+name)
    for name,field in fields.items():
        if field['required'] and name not in bound and not draft:raise ValueError('Missing workflow input: '+name)
    tasks=copy.deepcopy(document['tasks'])
    for node in tasks:
        for name,binding in list(node['inputs'].items()):
            if 'workflow' in binding:
                if binding['workflow'] in bound:
                    chosen=copy.deepcopy(bound[binding['workflow']]);node['inputs'][name]=chosen if fields[binding['workflow']]['type']=='artifact' else {'value':chosen}
                else:del node['inputs'][name]
    view=inspect_graph(tasks,grant=grant,artifact=artifact,producer=producer,draft=draft)
    if draft:
        view['missing_inputs']+=['workflow.'+name for name,field in fields.items() if field['required'] and name not in bound]
        view['ready']=not view['missing_inputs']
    return dict(document=copy.deepcopy(document),values=bound,template_sha256=c.digest(document),**view)
