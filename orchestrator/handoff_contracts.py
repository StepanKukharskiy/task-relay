"""Deterministic workflow ports and capacity checks; no provider or host calls."""
import copy
import re

VERSION = 1
PPTX_SLIDES = 50
PPTX_ELEMENTS = 1000
MANAGED_IMAGE_REFERENCES = 6
PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
TEXT = {'text/plain','text/markdown','application/json','text/csv','text/x-python'}
MEDIA_ALIASES = {'application/x-rhino-3dm':'application/vnd.rhino',
                 'application/x-3dm':'application/vnd.rhino', 'image/jpg':'image/jpeg'}


class ContractError(ValueError):
    def __init__(self, code, message, **detail):
        self.code=code;self.detail=detail
        super().__init__(message)

    def receipt(self):
        return dict(code=self.code,reason=str(self),**self.detail)


def operation(capability, frozen=None):
    """A saved contract can narrow, never enlarge, installed capacity."""
    from .execution import REGISTRY
    if capability not in REGISTRY:raise ContractError('unknown_capability','Unknown capability: '+str(capability))
    result=copy.deepcopy(REGISTRY[capability])
    if frozen is not None:
        if 'version' in frozen and frozen['version']!=result['version']:
            raise ContractError('version_mismatch','Capability version changed: '+capability)
        for field in ('input_bytes','output_bytes','seconds','max_inputs'):
            if field in frozen:result[field]=min(result[field],frozen[field])
        result['input_types']=[m for m in result['input_types'] if m in frozen.get('input_types',result['input_types'])]
    return result


def descriptor(value):
    if (not isinstance(value,dict) or 'media_type' not in value or
        set(value)-{'media_type','max_bytes','slides','companions'} or
        not isinstance(value['media_type'],str) or not re.fullmatch(r'[\w.+-]+/[\w.+-]+',value['media_type'])):
        raise ContractError('invalid_port','Each output needs a media_type and optional max_bytes, slides and companions.')
    if value['media_type'] in MEDIA_ALIASES:
        raise ContractError('noncanonical_media_type','Use the registered media type '+MEDIA_ALIASES[value['media_type']]+' instead of '+value['media_type']+'.')
    for key in ('max_bytes','slides'):
        if key in value and value[key] is not None and (type(value[key]) is not int or value[key]<1):
            raise ContractError('invalid_capacity','Use a positive '+key+' value, or null when unknown.')
    if value.get('slides') is not None:
        if value['media_type']!=PPTX_MIME:raise ContractError('invalid_capacity','slides applies only to a PPTX output.')
        if value['slides']>PPTX_SLIDES:
            raise ContractError('unsupported_scale',f"Requested {value['slides']} slides in one deck; the current PPTX builder supports at most {PPTX_SLIDES}. Automatic large-deck assembly is unavailable. Keep the request and agree a supported scope before starting.",requested=value['slides'],maximum=PPTX_SLIDES)
    companions=value.get('companions',[])
    if not isinstance(companions,list) or len(companions)>8 or any(not isinstance(x,str) for x in companions) or len(set(companions))!=len(companions):
        raise ContractError('invalid_companions','Companions must name distinct outputs in the same stage.')
    return value


def compile_workflow(stages, catalog=(), required=False):
    """Validate every declared edge before the first stage. Unknown sizes stay explicit."""
    saved={x['id']:x for x in catalog};seen={};edges=[];unknown=[]
    for stage in stages:
        handoff=stage.get('handoff')
        if handoff is None:
            if required:raise ContractError('missing_contract','Stage '+stage['id']+' needs declared handoff inputs and outputs.')
            unknown.append(stage['id']+': legacy handoffs not declared');seen[stage['id']]=stage;continue
        if not isinstance(handoff,dict) or set(handoff)!={'inputs','outputs'} or not isinstance(handoff['outputs'],dict) or set(handoff['outputs'])!=set(stage['deliverables']):
            raise ContractError('invalid_ports','Stage '+stage['id']+' must describe every deliverable exactly once.')
        if not isinstance(handoff['inputs'],list) or len(handoff['inputs'])>64:raise ContractError('invalid_edges','Use at most 64 explicit handoff edges.')
        if stage['route']=='image' and len(handoff['outputs'])!=1:
            raise ContractError('unsupported_outputs','A managed image stage produces one selected image; use separate stages for separate deliverables.')
        if stage['route']=='image' and sum(e.get('media_type','').startswith('image/') for e in handoff['inputs'] if isinstance(e,dict) and isinstance(e.get('media_type'),str))>MANAGED_IMAGE_REFERENCES:
            raise ContractError('input_capacity',f'Managed image generation accepts at most {MANAGED_IMAGE_REFERENCES} image references.')
        available=[]
        for cap in stage['capabilities']:
            if required and saved.get(cap,{}).get('available') is False:
                raise ContractError('capability_unavailable','Capability is unavailable before workflow start: '+cap)
            spec=operation(cap,saved.get(cap));available.extend(spec.get('outputs',{}).values())
            if spec.get('output_type'):available.append(spec['output_type'])
        for ident,out in handoff['outputs'].items():
            descriptor(out)
            if set(out.get('companions',[]))-set(handoff['outputs']) or ident in out.get('companions',[]):
                raise ContractError('invalid_companions','Output companions must exist and cannot refer to themselves.')
            media=out['media_type']
            if stage['route'] in ('conversation','browser_research') and media not in TEXT:
                raise ContractError('incompatible_output','A conversation/research stage cannot promise a native or image file.')
            if stage['route']=='image' and media!='image/png':raise ContractError('incompatible_output','Managed image stages produce image/png.')
            if stage['route']=='production' and media in ('application/vnd.rhino','application/x-blender',PPTX_MIME) and media not in available:
                raise ContractError('missing_producer','No selected native/document capability produces '+media+' for '+stage['id'])
            if out.get('max_bytes') is None:unknown.append(stage['id']+'/'+ident+': byte size unknown; checked when produced')
            if media==PPTX_MIME and out.get('slides') is None:unknown.append(stage['id']+'/'+ident+': slide count unspecified')
            producer_caps=stage['capabilities'] if stage['route']!='image' else ['gemini.image']
            producers=[]
            for cap in producer_caps:
                spec=operation(cap,saved.get(cap))
                if media in [spec.get('output_type'),*spec.get('outputs',{}).values()]:producers.append(spec)
            if producers and out.get('max_bytes') and out['max_bytes']>max(x['output_bytes'] for x in producers):
                raise ContractError('output_capacity','Declared output exceeds the selected producer capacity: '+stage['id']+'/'+ident)
        seen_edges=set();totals={};counts={}
        for edge in handoff['inputs']:
            if not isinstance(edge,dict) or set(edge)!={'stage','deliverable','media_type','consumer'}:
                raise ContractError('invalid_edge','Each edge needs stage, deliverable, media_type and consumer (context or a selected capability).')
            if any(not isinstance(edge[k],str) for k in edge):raise ContractError('invalid_edge','Edge fields must be strings.')
            key=(edge['stage'],edge['deliverable'],edge['consumer'])
            if key in seen_edges:raise ContractError('duplicate_edge','Duplicate handoff edge.')
            seen_edges.add(key)
            prior=seen.get(edge['stage'],{}).get('handoff',{}).get('outputs',{})
            source=prior.get(edge['deliverable'])
            if source is None:raise ContractError('missing_source','Handoffs must name an existing earlier-stage deliverable.')
            if source['media_type']!=edge['media_type']:raise ContractError('type_mismatch','Handoff media types disagree for '+edge['stage']+'/'+edge['deliverable'])
            consumer=edge['consumer']
            if stage['route']=='image' and edge['media_type'] not in operation('gemini.image')['input_types']:
                raise ContractError('incompatible_input','Image generation needs image/text references, not native model files.')
            if consumer!='context':
                if consumer not in stage['capabilities'] and not (stage['route']=='image' and consumer=='gemini.image'):
                    raise ContractError('missing_consumer','Handoff consumer is outside the selected stage capabilities.')
                target=operation(consumer,saved.get(consumer))
                if edge['media_type'] not in target['input_types']:
                    raise ContractError('incompatible_input',consumer+' cannot consume '+edge['media_type']+'. Declare a compatible derived output or conversion stage.')
                if seen[edge['stage']]['route'] in ('conversation','browser_research'):
                    raise ContractError('context_requires_file','Conversation/research results are context. Use consumer=context and prepare a file before a direct operation.')
                totals[consumer]=totals.get(consumer,0)+(source.get('max_bytes') or 0)
                counts[consumer]=counts.get(consumer,0)+1
                if counts[consumer]>target['max_inputs']:
                    raise ContractError('input_capacity',consumer+' declared input count exceeds its capacity.')
                if totals[consumer]>target['input_bytes']:
                    raise ContractError('input_capacity',consumer+' declared input bounds exceed its capacity; prepare a bounded derivative before this stage.')
            edges.append(dict(destination=stage['id'],**edge))
        for edge in handoff['inputs']:
            source=seen[edge['stage']]['handoff']['outputs'][edge['deliverable']]
            for companion in source.get('companions',[]):
                if not any(e['stage']==edge['stage'] and e['deliverable']==companion for e in handoff['inputs']):
                    raise ContractError('missing_companion','Required companion missing: '+edge['stage']+'/'+companion)
        seen[stage['id']]=stage
    return dict(version=VERSION,status='compatible_with_runtime_checks' if not unknown else 'compatible_with_unknowns',edges=edges,unknowns=unknown,
                limitations=['Content accuracy and image/model fidelity require independent review.','Unknown file sizes and future schemas are checked at their actual handoff; this is not a live provider qualification.'])


def image_references(stage, bindings):
    """Only the declared selected image versions may reach managed generation."""
    result=set()
    for edge in stage['handoff']['inputs']:
        if not edge['media_type'].startswith('image/'):continue
        binding=next((b for b in bindings if all(b.get(k)==edge[k] for k in ('stage','deliverable','consumer'))),None)
        if not binding or binding.get('kind')!='artifact':
            raise ContractError('missing_binding','Image stage is missing its exact frozen reference binding.')
        result.add(binding['source']['artifact'])
    return result


def bind_stage(stage, plan, bindings=(), sources=()):
    """Bind logical promises to exact plan outputs before approval, never by filename guess."""
    if not stage or not stage.get('handoff') or plan.get('deferred_operations'):return
    for ident,expected in stage['handoff']['outputs'].items():
        binding=plan.get('deliverables',{}).get(ident,{})
        task=next((t for t in plan['tasks'] if t['id']==binding.get('task')),None)
        output=next((o for o in task['outputs'] if o['path']==binding.get('output')),None) if task else None
        if output is None:raise ContractError('missing_output','No concrete output bound to workflow deliverable '+ident)
        if output.setdefault('media_type',expected['media_type'])!=expected['media_type']:
            raise ContractError('type_mismatch','Concrete output type differs from workflow deliverable '+ident)
        output['handoff']=copy.deepcopy(expected)
    known={s['artifact']:s for s in sources}
    for edge in stage['handoff']['inputs']:
        binding=next((b for b in bindings if all(b.get(k)==edge[k] for k in ('stage','deliverable','consumer'))),None)
        if binding is None:raise ContractError('missing_binding','Missing frozen workflow handoff for '+edge['stage']+'/'+edge['deliverable'])
        if binding['kind']=='context':continue
        artifact=binding['source']['artifact']
        candidates=[t for t in plan['tasks'] if not t.get('review_of') and (edge['consumer']=='context' or t.get('execution',{}).get('capability')==edge['consumer'])]
        if not any(known.get(i.get('artifact'),{}).get('workflow_artifact',i.get('artifact'))==artifact for t in candidates for i in t['inputs']):
            raise ContractError('missing_binding','The selected consumer omitted the exact upstream artifact for '+edge['stage']+'/'+edge['deliverable'])


def check_file(path, expected):
    """Structural delivery checks; semantic acceptance is never inferred."""
    descriptor(expected)
    if expected.get('max_bytes') is not None and path.stat().st_size>expected['max_bytes']:
        raise ContractError('output_capacity','Delivered file exceeds its declared handoff byte bound.')
    if expected['media_type'] in TEXT:
        try:path.read_bytes().decode('utf-8')
        except UnicodeError:raise ContractError('invalid_encoding','Delivered text is not UTF-8.') from None
    if expected.get('slides') is not None:
        import zipfile
        from xml.etree import ElementTree as ET
        try:
            with zipfile.ZipFile(path) as archive:
                info=archive.getinfo('ppt/presentation.xml')
                if info.file_size>2000000:raise ContractError('invalid_document','Presentation manifest exceeds its bound.')
                root=ET.fromstring(archive.read(info))
                count=len(root.findall('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst/{http://schemas.openxmlformats.org/presentationml/2006/main}sldId'))
        except (zipfile.BadZipFile,KeyError,ET.ParseError) as exc:
            raise ContractError('invalid_document','Invalid PPTX manifest: '+str(exc)) from exc
        if count!=expected['slides']:raise ContractError('quantity_mismatch',f"Requested {expected['slides']} slides; delivered {count}.")
