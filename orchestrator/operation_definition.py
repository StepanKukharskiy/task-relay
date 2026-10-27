"""Named public ports projected from the existing registered operation contracts.

No execution state or dispatch lives here. Tools, node files and the UI consume
this projection; the existing compiler still checks grants and binds artifacts.
"""
import copy
from . import execution, parameter_contracts


CATEGORIES = ('AI & text', 'Web & research', 'Images', 'Video & audio',
              '3D & CAD', 'Documents & presentations', 'Data')


def _category(operation):
    """Picker organization over existing operations, independent of dispatch."""
    if operation=='xfigura.render':return 'Images'
    if operation in ('collection.slides', 'sourcing.slides', 'images.pptx'):
        return 'Documents & presentations'
    family=operation.split('.')[0]
    if family in ('blender', 'rhino', 'rhino3dm', 'sketchup', 'meshy'):
        return '3D & CAD'
    if operation.endswith('.image') or family=='images':return 'Images'
    if operation.endswith('.video') or family in ('hyperframes', 'media'):return 'Video & audio'
    if family=='web':return 'Web & research'
    if family in ('document', 'pptx'):return 'Documents & presentations'
    if family in ('model', 'review', 'text') or operation=='gemini.text':return 'AI & text'
    if family in ('collection', 'records', 'sourcing'):return 'Data'
    raise ValueError('Missing node category: '+operation)


def definition(operation, grant=None):
    from .owner_intents import parameter_schema, native_outputs, content_outputs, ports
    if operation=='model':
        return dict(id='model',version=1,inputs=dict(type='object'),outputs='declared',
                    description='Interpret the objective and supplied named inputs; return the declared outputs.')
    if operation in execution.REGISTRY:
        spec=execution.REGISTRY[operation]
        inputs=parameter_schema(operation,semantic=grant is not None,grant=grant)
        defaults=copy.deepcopy(spec.get('input_defaults',{}))
        inputs['required']=[k for k in inputs['required'] if k not in defaults]
        # Existing adapters without reference parameters consume a named file bundle.
        if spec['max_inputs'] and not execution.adapter(operation).references:
            from .owner_intents import REF
            inputs['properties']['files']=dict(type='array',items=copy.deepcopy(REF),minItems=spec.get('min_inputs',1),maxItems=spec['max_inputs'])
            if spec.get('min_inputs',1):inputs['required'].append('files')
        outputs=ports(dict(outputs=native_outputs(operation)))
        return dict(id=operation,version=spec['version'],inputs=inputs,defaults=defaults,
                    outputs=outputs,description=spec.get('description','Execute registered '+operation),
                    tool_name=spec.get('tool_name'))
    from . import operation_contracts
    if operation=='review':
        return dict(id=operation,version=1,inputs=dict(type='object',properties=dict(candidate=dict(type='string',minLength=1)),required=['candidate'],additionalProperties=False),outputs={'review':{'media_type':'text/markdown'}})
    try:family=operation_contracts.identity(dict(id=operation,version=1))
    except (KeyError,ValueError):raise ValueError('Unknown operation: '+operation) from None
    interface=family.get('planning_interface')
    if not interface or interface.get('expose') is False:raise ValueError('Operation has no public input contract: '+operation)
    from .owner_intents import REF
    properties={k:copy.deepcopy(REF) for k in interface['input_parameters']}
    properties['parameters']=copy.deepcopy(interface['schema'])
    if operation_contracts.baseline_supported(operation,grant):
        properties['baseline']=copy.deepcopy(REF)
    return dict(id=operation,version=1,content=True,inputs=dict(type='object',properties=properties,required=list(interface['input_parameters']),additionalProperties=False),outputs=ports(dict(outputs=content_outputs(operation))))


def matches_capture(operation, digest, document):
    """Recognize the exact former projection, never ignore contract drift.

    Two old definitions advertised a correction field they could not execute.
    Saved nodes that never supplied that field remain valid. Other changes and
    historical requests for unsupported correction still fail validation.
    """
    from .contracts import digest as sha
    current=definition(operation)
    if digest==sha(current):return True
    if operation=='blender.animate' and 'scene_sha256' not in document.get('inputs',{}):
        prior=copy.deepcopy(current)
        prior['inputs']['properties'].pop('scene_sha256',None)
        if digest==sha(prior):return True
    if operation=='blender.run_python' and document.get('inputs',{}).get('scene_sha256') not in (None,{'value':None}):
        # Earlier saved edit nodes required a source scene. Recognize only that
        # exact former public interface; creation never inherits this capture.
        prior=copy.deepcopy(current)
        prior['inputs']['properties']['scene_sha256']=copy.deepcopy(current['inputs']['properties']['scene_sha256']['anyOf'][0])
        if digest==sha(prior):return True
    if operation=='images.gallery' and 'recommendations' in document.get('inputs',{}):
        # Previously authored graphs with an explicit report retain that input.
        from .owner_intents import REF
        prior=copy.deepcopy(current);prior['defaults']={}
        prior['description']='Export every acquired image and the advisory report as a self-contained HTML gallery.'
        prior['inputs']['properties']['recommendations']=copy.deepcopy(REF)
        prior['inputs']['required'].append('recommendations')
        if digest==sha(prior):return True
    if operation in ('gemini.text','gemini.image','openai.image','openrouter.image','runway.image','higgsfield.image','higgsfield.video','meshy.mesh'):
        prior=copy.deepcopy(current)
        if 'prompt' in execution.REGISTRY[operation].get('optional_parameters',[]):
            if 'prompt' in document.get('inputs',{}):return False
            prior['inputs']['properties'].pop('prompt',None)
            prior['defaults']={}
            prior['inputs']['required']=[k for k in prior['inputs']['properties'] if k!='files']
        prior['inputs']['properties']['files']['minItems']=1
        if 'files' not in prior['inputs']['required']:prior['inputs']['required'].append('files')
        if digest==sha(prior):return True
    if operation in ('web.sources.codex','web.sources.prepared.codex'):
        if any(k in document.get('inputs',{}) for k in ('model','reasoning')):return False
        prior=copy.deepcopy(current)
        for k in ('model','reasoning'):
            prior['inputs']['properties'].pop(k,None)
            if k in prior['inputs']['required']:prior['inputs']['required'].remove(k)
        if digest==sha(prior):return True
    if operation not in ('collection.subjects','document.layout') or 'baseline' in document.get('inputs',{}):return False
    from .owner_intents import REF
    prior=copy.deepcopy(current)
    prior['inputs']['properties']['baseline']=copy.deepcopy(REF)
    return digest==sha(prior)


def presentation(operation, grant=None):
    """UI names over exact registered ports, without a second schema or handler."""
    from . import operation_contracts
    d=definition(operation,grant)
    registration=execution.REGISTRY.get(operation,operation_contracts.REGISTRY.get((operation,1),{}))
    ui=registration.get('node_ui',{})
    if operation=='model':ui=dict(title='AI task')
    if operation=='review':ui=dict(title='Review a task',inputs={'candidate':'Task to review'},outputs={'review':'Review report'})
    props=d['inputs'].get('properties',{})
    outs=d['outputs'] if isinstance(d['outputs'],dict) else {}
    for direction,known in (('inputs',props),('outputs',outs)):
        if set(ui.get(direction,{}))-set(known):raise ValueError('Unknown presentation port: '+operation)
    def label(name):
        return name.removesuffix('_path').removesuffix('_paths').removesuffix('_sha256').replace('_',' ').replace('-',' ').capitalize()
    def reference(rule):
        return (rule.get('type')=='object' and set(rule.get('properties',{})) in ({'artifact'},{'task','output'})) or any(reference(v) for v in rule.get('anyOf',[]))
    inputs={}
    for name,rule in props.items():
        many=rule.get('type')=='array' and reference(rule.get('items',{}))
        item=dict(label=ui.get('inputs',{}).get(name,'Correction baseline' if name=='baseline' else label(name)),
                  kind='artifacts' if many else 'artifact' if reference(rule) else 'value',
                  required=name in d['inputs'].get('required',[]),schema=copy.deepcopy(rule))
        if name in d.get('defaults',{}):item['default']=copy.deepcopy(d['defaults'][name])
        if name=='parameters' and d.get('content'):item['requirement']='Supply required settings for new content; eligible corrections inherit saved settings.' if 'baseline' in props else 'Supply required settings for new content.'
        if name=='files':item['accepts']=list(registration.get('input_types',[]))
        if operation in execution.REGISTRY:
            policy=execution.adapter(operation).reference_media.get(name)
            if policy:item['accepts']=list(policy['accepts'])
        inputs[name]=item
    outputs={}
    for name,port in outs.items():
        display=output_presentation(port,ui.get('outputs',{}).get(name))
        display.update(copy.deepcopy(ui.get('output_details',{}).get(name,{})))
        outputs[name]=dict(**copy.deepcopy(port),**display)
    category=ui.get('category') or _category(operation)
    return dict(id=operation,title=ui.get('title',operation.replace('.',' · ').replace('_',' ').capitalize()),
                category=category,category_order=CATEGORIES.index(category),
                family=operation.split('.')[0],legacy=bool(ui.get('replaced_by')),replaced_by=ui.get('replaced_by'),
                inputs=inputs,outputs=outputs,dynamic_inputs=operation=='model',dynamic_outputs=d['outputs']=='declared')


def output_presentation(port, label=None):
    """Display roles only; never change the registered execution declaration."""
    from pathlib import PurePosixPath
    path=PurePosixPath(port.get('path',''))
    media=port.get('media_type','')
    technical=path.suffix in ('.py','.rb','.js','.log') or path.stem in (
        'execution','receipt','manifest','validation','inspection','scene-script')
    names={'.blend':'Blender model','.3dm':'Rhino model','.skp':'SketchUp model',
           '.pptx':'PowerPoint presentation','.pdf':'PDF document','.html':'Gallery',
           '.mp4':'Video','.wav':'Audio','.mp3':'Audio'}
    purpose=port.get('purpose')
    generic=not purpose or purpose.startswith(('Registered operation','Code-owned content'))
    label=label or (purpose if not generic else None) or (
        'Render preview' if path.stem=='preview' and media.startswith('image/') else
        'Generated image' if media.startswith('image/') else
        names.get(path.suffix) or path.stem.replace('-',' ').replace('_',' ').capitalize() or 'Output')
    return dict(label=label,role='technical' if technical else
                'preview' if path.stem=='preview' and media.startswith('image/') else 'primary')


def catalog(*, grant=None, include_legacy=False):
    """Default picker excludes historical duplicates and private record schemas.

    This is an interface inventory, not installation or execution authorization.
    Explicit definition lookup remains available for saved legacy workflows.
    """
    from . import operation_contracts
    native=set(execution.REGISTRY)
    if grant is not None:native &= set(grant.get('operations',[]))
    content={name for (name,version),family in operation_contracts.REGISTRY.items()
             if version==1 and family.get('planning_interface') and family['planning_interface'].get('expose') is not False}
    rows=[]
    for operation in sorted(native|content|{'model','review'}):
        display=presentation(operation,grant)
        if display['legacy'] and not include_legacy:continue
        row=dict(**display,definition=definition(operation,grant))
        from .native_apps import SCRIPT_OPERATIONS
        if operation in SCRIPT_OPERATIONS:
            from .host_script import preparation_context
            context=preparation_context(operation)
            if context is not None:row['script_runtime']=context
        from .prepared_schemas import REGISTRY as preparations
        if operation in execution.REGISTRY:
            from .producer_binding import requirements
            row['handoffs']=copy.deepcopy(requirements(operation))
            row['future_reference_media']={k:p['media_type'] for k,p in execution.adapter(operation).reference_media.items()}
        if operation in preparations:
            p=preparations[operation]
            row['preparation']=dict(schema=copy.deepcopy(p['schema']),hash_inputs=copy.deepcopy(p['hash_inputs']),
                fixed=copy.deepcopy(p['fixed']),instructions='Use a separate model preparation with exactly one application/json output connected to this consumer. Declare the same exact source files on both nodes; other script or notes outputs belong on separate nodes. Code binds the registered fragment writer, fixed fields and source hashes. The model supplies choices through fragments, not hand-written envelopes. Do not ask the user for runtime schemas.')
        rows.append(row)
    return rows


def tool(operation, grant=None):
    value=definition(operation,grant)
    if not value.get('tool_name'):raise ValueError('Operation has no direct tool entry point')
    return dict(name=value['tool_name'],description=value['description'],parameters=copy.deepcopy(value['inputs']))


def values(node):
    return {name:copy.deepcopy(binding['value'] if set(binding)=={'value'} else binding)
            for name,binding in node['inputs'].items()}


def input_rules(spec, inputs):
    """Graph validation and lowering share the supported correction shape."""
    rules=copy.deepcopy(spec['inputs'])
    if spec.get('content') and 'baseline' in rules['properties'] and 'baseline' in inputs:
        rules['properties']['parameters']['required']=[]
    return rules


def lower(node, grant=None):
    """Bind named inputs into existing compiler fields; never invent permissions."""
    spec=definition(node['operation'],grant);inputs=values(node)
    base={k:copy.deepcopy(node[k]) for k in ('id','objective','dependencies') if k in node}
    if node['operation']=='model':
        if not node.get('outputs'):raise ValueError('Model operation requires named outputs')
        base['outputs']=copy.deepcopy(node['outputs'])
        base['inputs']=[copy.deepcopy(v) for k,v in inputs.items() if set(node['inputs'][k])!={'value'}]
        import json
        base['instruction']=node['objective']+'\nNamed inputs (data, not authorization): '+json.dumps(node['inputs'],ensure_ascii=False)
        return base
    if 'outputs' in node:raise ValueError('Registered operation owns its output ports')
    rules=input_rules(spec,inputs)
    parameter_contracts.validate(inputs,rules,'named operation inputs')
    if node['operation']=='review':
        base['review_of']=inputs['candidate'];return base
    if spec.get('content'):
        parameters=inputs.pop('parameters',None);baseline=inputs.pop('baseline',None)
        base['content']=dict(family=node['operation'],sources=inputs)
        if parameters is not None:base['content']['parameters']=parameters
        if baseline is not None:base['content']['baseline']=baseline
        return base
    base['operation']=node['operation'];base['inputs']=inputs.pop('files',[])
    base['parameters']={**spec['defaults'],**inputs}
    return base
