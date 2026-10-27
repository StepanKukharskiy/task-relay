"""Registered admission interfaces over the existing operation registry.

An adapter owns parameter shapes and content-specific checks. The existing
compiler/runtime owns scope, attempts, queue mutations and effect handling.
Adapters also own transport, availability, binding and receipt observation.
"""
import copy
import importlib
from dataclasses import dataclass, field
from . import parameter_contracts
from .operation_validators import VALIDATORS


def object_schema(properties, required=None):
    return dict(type='object', properties=properties,
                required=list(properties) if required is None else required,
                additionalProperties=False)


def resolve(reference):
    """Only trusted registrations reach here; job JSON cannot name callables."""
    if not isinstance(reference,str) or reference.count(':')!=1:
        raise ValueError('Invalid registered adapter hook')
    module,name=reference.split(':')
    value=getattr(importlib.import_module(module),name)
    if not callable(value):raise ValueError('Registered adapter hook is not callable')
    return value


@dataclass(frozen=True)
class Adapter:
    parameters: dict
    validators: tuple = ()
    max_attempts: int = 1
    correction_kinds: tuple = ()
    version: int = 1
    handler: str = None
    availability: tuple = ()
    descriptions: tuple = ()
    freeze_hooks: tuple = ()
    inspections: tuple = ()
    preflight: tuple = ()
    content_ports: tuple = ()
    handoffs: dict = None
    references: dict = field(default_factory=dict)
    reference_media: dict = field(default_factory=dict)
    backend_binding: dict = field(default_factory=dict)
    reconcile: str = None
    worker_tool: bool = False
    evidence_views: str = None
    review_evidence: str = None
    evidence_extension: str = None
    asset_binding: str = 'path'

    def schema(self, spec):
        value=copy.deepcopy(self.parameters)
        parameter_contracts.check(value)
        if (value.get('type')!='object' or set(value.get('properties',{}))!=set(spec['parameters'])
                or set(value.get('required',[]))!=set(spec['parameters'])-set(spec.get('optional_parameters',[]))
                or value.get('additionalProperties') is not False):
            raise ValueError('Adapter parameter fields differ from the operation declaration')
        for key, description in spec['parameters'].items():
            value['properties'][key].setdefault('description',description)
        return value

    def manifest(self):
        if self.asset_binding not in ('path','sha256'):raise ValueError('Invalid registered asset binding')
        for name,kind in self.references.items():
            if name not in self.parameters.get('properties',{}) or kind not in ('path','paths','sha256'):
                raise ValueError('Invalid registered parameter reference')
        for name,policy in self.reference_media.items():
            if (self.references.get(name) not in ('sha256','path') or not isinstance(policy,dict)
                    or set(policy)!={'media_type','accepts'} or not isinstance(policy['accepts'],list)
                    or not policy['accepts'] or any(not isinstance(m,str) or not m for m in policy['accepts'])
                    or policy['media_type'] not in policy['accepts']):
                raise ValueError('Invalid registered reference media policy')
        handoffs=copy.deepcopy(self.handoffs)
        if self.handoffs is not None:
            policy=self.handoffs
            if not isinstance(policy,dict) or policy.get('version')!=1 or not isinstance(policy.get('ports'),list):
                raise ValueError('Invalid registered producer binding policy')
            selectors=set()
            for port in policy['ports']:
                selector=port.get('selector')
                if (not isinstance(selector,str) or selector in selectors or
                        selector!='json' and (not selector.startswith('parameter:') or selector.split(':',1)[1] not in self.parameters.get('properties',{}))):
                    raise ValueError('Invalid registered handoff selector')
                selectors.add(selector)
                if port.get('kind') not in ('records','preparation','evidence'):raise ValueError('Invalid registered handoff kind')
                if port['kind']=='preparation':
                    from .prepared_schemas import REGISTRY
                    if port.get('target') not in REGISTRY:raise ValueError('Unregistered producer preparation schema')
                elif not isinstance(port.get('families' if port['kind']=='records' else 'native'),list):
                    raise ValueError('Missing registered producer choices')
            import hashlib,json
            for port in handoffs['ports']:
                if port['kind']=='preparation':
                    # A saved connector also pins its input document/fragment
                    # schema, not merely the registered adapter's name.
                    port['schema_sha256']=hashlib.sha256(json.dumps(REGISTRY[port['target']],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if any(p not in self.parameters.get('properties',{}) or not roles or
               any(not isinstance(role,str) or not role for role in roles) for p,roles in self.content_ports):
            raise ValueError('Invalid registered content port')
        if type(self.version) is not int or self.version<1 or type(self.max_attempts) is not int or self.max_attempts not in (1,2):
            raise ValueError('Invalid adapter admission policy')
        if any(not callable(v) for v in self.validators) or any(not isinstance(k,str) or not k for k in self.correction_kinds):
            raise ValueError('Invalid adapter validation hooks')
        if any(not isinstance(h,str) or h.count(':')!=1 for h in (*self.availability,*self.descriptions,*self.freeze_hooks,*self.inspections,*self.preflight,*((self.handler,) if self.handler is not None else ()),*((self.reconcile,) if self.reconcile is not None else ()),*((self.review_evidence,) if self.review_evidence is not None else ()),*((self.evidence_extension,) if self.evidence_extension is not None else ()))):
            raise ValueError('Invalid registered adapter hook')
        return dict(version=self.version, max_attempts=self.max_attempts,
                    **({'asset_binding':self.asset_binding} if self.asset_binding!='path' else {}),
                    correction_kinds=list(self.correction_kinds),
                    handler=self.handler,
                    **(dict(review_evidence=self.review_evidence) if self.review_evidence else {}),
                    **(dict(evidence_extension=self.evidence_extension) if self.evidence_extension else {}),
                    **(dict(reconcile=self.reconcile) if self.reconcile else {}),
                    availability=list(self.availability),
                    descriptions=list(self.descriptions),freeze_hooks=list(self.freeze_hooks),inspections=list(self.inspections),preflight=list(self.preflight),
                    **({'content_ports':[dict(parameter=p,roles=list(roles)) for p,roles in self.content_ports]} if self.content_ports else {}),
                    **({'handoffs':handoffs} if handoffs is not None else {}),
                    **({'references':copy.deepcopy(self.references)} if self.references else {}),
                    **({'reference_media':copy.deepcopy(self.reference_media)} if self.reference_media else {}),
                    validators=[v.__module__+':'+v.__qualname__ for v in self.validators])

    def bind_reference_media(self,parameter,item):
        """Code-owned role on an explicitly selected, hash-bound input only.

        This changes neither source bytes nor the producing artifact descriptor.
        The host's syntax, exact-byte authorization and content checks still run.
        """
        policy=self.reference_media.get(parameter)
        if policy:
            if item.get('media_type') not in policy['accepts']:
                raise ValueError(parameter+' requires '+', '.join(policy['accepts']))
            item['media_type']=policy['media_type']

    def modules(self, spec):
        references=(self.handler,self.reconcile,*self.freeze_hooks,*self.inspections,*self.availability,*self.preflight)
        return set(spec.get('support_modules',[]))|{h.split(':')[0] for h in references if h}|{v.__module__ for v in self.validators}|({'orchestrator.operation_inputs'} if self.content_ports else set())|({'orchestrator.producer_binding','orchestrator.prepared_schemas'} if self.handoffs is not None else set())

    def verify_implementation(self, frozen, spec):
        from .runtime import file_hash
        from pathlib import Path
        for name in self.modules(spec):
            module=importlib.import_module(name)
            key=Path(module.__file__).name if name.startswith('orchestrator.') else name.replace('.','/')+'.py'
            if frozen.get('runtime_sources',{}).get(key)!=file_hash(Path(module.__file__)):
                raise ValueError('Registered adapter implementation changed after dispatch: '+name)

    def execute(self, context):
        if not self.handler:raise ValueError('No execution handler registered for this operation; no fallback was dispatched.')
        self.verify_implementation(context.frozen,context.spec)
        if self.backend_binding and context.frozen.get('backend'):
            from .model_binding import verify
            verify(context.frozen['execution']['capability'],context.frozen['execution']['parameters'],context.frozen['backend'])
        return resolve(self.handler)(context)

    def bind_inputs(self, runtime, spec, run=None):
        # Preflight sees collected identities, not unresolved graph references.
        # The saved assignment remains unchanged; normal freezing binds again.
        if self.preflight and any('from_task' in i for i in spec['inputs']):
            spec=copy.deepcopy(spec)
            for item in spec['inputs']:
                if 'artifact' in item:continue
                if run is None or runtime.task(run,item['from_task'])['status']!='completed':
                    raise ValueError('Operation input producer has not completed')
                artifact=runtime.output(run,item['from_task'],item['output'])
                item.pop('from_task');item.pop('output');item['artifact']=artifact['id']
        for hook in self.preflight:resolve(hook)(runtime,spec)

    def validate_content(self, assignment, read):
        from .operation_inputs import validate
        validate(assignment,self.content_ports,read)
        if assignment.get('producer_binding_version')==1:
            from .producer_binding import validate_content
            validate_content(assignment,read)

    def inspect(self, control, result, details):
        for hook in self.inspections:resolve(hook)(control,result,details)
        if result.get('status')=='finished' and details.get('outcome')=='rejected':
            if result.get('external_outcome')!='not_submitted':
                result['external_outcome']='rejected'
            if details.get('reason') and not result.get('reason'):result['reason']=details['reason']

    def check_available(self, assignment, spec):
        for hook in self.availability:resolve(hook)(assignment,spec)

    def describe(self, entry, context):
        for hook in self.descriptions:resolve(hook)(entry,context)

    def freeze(self, frozen, spec):
        from pathlib import Path
        from .runtime import file_hash
        if self.backend_binding and frozen.get('backend'):
            from .model_binding import verify
            verify(frozen['execution']['capability'],frozen['execution']['parameters'],frozen['backend'])
        for hook in self.freeze_hooks:resolve(hook)(frozen)
        for name in self.modules(spec):
            module=importlib.import_module(name)
            key=Path(module.__file__).name if name.startswith('orchestrator.') else name.replace('.','/')+'.py'
            frozen['runtime_sources'][key]=file_hash(Path(module.__file__))

    def validate(self, assignment, spec):
        # Preserve the precise existing semantic error messages where possible.
        # Malformed wire values must be rejected before hooks inspect them.
        parameter_contracts.validate(assignment['execution']['parameters'],self.schema(spec))
        for name in self.reference_media:
            if self.references[name]!='path':continue
            path=assignment['execution']['parameters'].get(name)
            if path is None:continue  # Nullable registered schema was validated above.
            matches=[i for i in assignment['inputs'] if i['path']==path]
            if not matches and assignment['execution']['capability'] in ('blender.run_python','blender.animate'):
                import re
                if isinstance(path,str) and re.fullmatch('[a-f0-9]{64}',path):continue
            if len(matches)!=1:raise ValueError('Named input must bind one declared file: '+name)
            self.bind_reference_media(name,copy.deepcopy(matches[0]))
        if 'prompt' in spec.get('optional_parameters',[]) and not assignment.get('inputs') and not assignment['execution']['parameters'].get('prompt','').strip():
            raise ValueError('Enter a prompt or select a source document')
        for validator in self.validators: validator(assignment,spec)


STRING=dict(type='string')
NONEMPTY=dict(type='string',minLength=1)
HASH=dict(type='string',pattern='^[a-f0-9]{64}$')
NULL=dict(type='null')
DOMAINS=dict(type='array',items=STRING,maxItems=8)
COUNT_POLICY=dict(type='string',enum=['target','required'])
GEMINI_MODEL=dict(type='string',pattern='^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$')
TOKENS=dict(type='integer',minimum=1,maximum=4096)
RATIO=dict(type='string',enum=['1:1','16:9','9:16'])


def nullable(rule): return dict(anyOf=[rule,NULL])


HANDLERS = {
    'image_export': ('images.pptx','images.gallery'),
    'crop_image': ('images.crop',),
    'text_bundle': ('text.bundle',),
    'model': ('gemini.text','gemini.image','openai.image','openrouter.image'),
    'cloud': ('runway.image','runway.video','higgsfield.image','higgsfield.video','meshy.mesh'),
    'sources': ('web.sources','web.sources.prepared','web.sources.coverage'),
    'rendered_sources': ('web.sources.rendered','web.sources.native'),
    'photos': ('images.collect','images.fetch'),
    'merge_photos': ('images.merge',),
    'catalog_photos': ('images.products','images.catalog'),
    'record_merge': ('sourcing.merge','records.merge'),
    'slides': ('sourcing.slides','collection.slides'),
    'presentation_create': ('pptx.create',), 'presentation_edit': ('pptx.edit',),
    'presentation_preview': ('pptx.render',),
    'hyperframes': ('hyperframes.preview','hyperframes.render'),
    'compose': ('media.compose',), 'geometry': ('rhino3dm.create',),
    'native': ('blender.startup','blender.scene','blender.mesh_scene','blender.inspect','blender.geometry',
               'blender.run_python','blender.import_asset','blender.animate','rhino.startup',
               'rhino.inspect','rhino.run_python','rhino.document','rhino.render','rhino.grasshopper',
               'rhino3dm.run_python','sketchup.startup','sketchup.inspect','sketchup.run_ruby'),
}


def builtins(operations):
    """Explicit parameter definitions; no guessed types from prose or field names."""
    from .producer_binding import manifest as handoff_manifest
    # Explicit binding metadata, never inferred from suffixes or model prose.
    references={
        'document.compose':dict(document_paths='paths',image_paths='paths'),
        'web.sources.coverage':dict(catalog_path='path',source_pack_path='path'),
        'hyperframes.render':dict(project_sha256='sha256',preview_sha256='sha256'),
    }
    for cap in ('sourcing.merge','records.merge'):
        references[cap]=dict(inventory_path='path',source_pack_path='path',catalog_paths='paths',review_paths='paths')
    for cap in ('sourcing.slides','collection.slides'):
        references[cap]=dict(inventory_path='path',catalog_path='path',source_pack_path='path',image_path='path',photos_path='path')
    for cap in ('images.products','images.catalog'):
        references[cap]=dict(inventory_path='path',catalog_path='path',source_pack_path='path')
    for cap in ('blender.import_asset','blender.animate','rhino.render'):
        references[cap]=dict(manifest_sha256='sha256')
    references['blender.animate']=dict(manifest_sha256='path',scene_sha256='path')
    from .native_apps import SCRIPT_OPERATIONS,profile
    reference_media={'blender.animate':dict(manifest_sha256=dict(media_type='application/json',accepts=['application/json']),
        scene_sha256=dict(media_type='application/x-blender',accepts=['application/x-blender']))}
    for cap in HANDLERS['image_export']:
        references[cap]=dict(photos='path',recommendations='path')
        reference_media[cap]=dict(photos=dict(media_type='application/zip',accepts=['application/zip']),
            recommendations=dict(media_type='text/markdown',accepts=['text/plain','text/markdown']))
    for cap in SCRIPT_OPERATIONS:
        references[cap]=dict(scene_sha256='path',script_sha256='path',checks_sha256='path') if cap=='blender.run_python' else dict(scene_sha256='sha256',script_sha256='sha256',checks_sha256='sha256')
        media=profile(cap).script_media
        reference_media[cap]=dict(script_sha256=dict(media_type=media,accepts=[media,'text/plain']))
    properties={
        'images.pptx':dict(photos=STRING,recommendations=STRING),
        'images.gallery':dict(photos=STRING,recommendations={'anyOf':[STRING,{'type':'null'}]}),
        'document.compose':dict(document_paths=dict(type='array',items=STRING,maxItems=30),image_paths=dict(type='array',items=STRING,maxItems=20),image_titles=dict(type='array',items=dict(type='string',minLength=1,maxLength=255),maxItems=20),title=dict(type='string',minLength=1,maxLength=255)),
        'gemini.text':dict(model=GEMINI_MODEL,max_output_tokens=TOKENS,prompt=dict(type='string',maxLength=16000)),
        'gemini.image':dict(model=GEMINI_MODEL,max_output_tokens=TOKENS,aspect_ratio=RATIO,prompt=dict(type='string',maxLength=16000)),
        'openai.image':dict(model=dict(type='string',pattern='^gpt-image-[A-Za-z0-9._-]{1,100}$'),
                            size=dict(type='string',enum=['auto','1024x1024','1536x1024','1024x1536']),
                            quality=dict(type='string',enum=['auto','low','medium','high']),prompt=dict(type='string',maxLength=16000)),
        'openrouter.image':dict(model=NONEMPTY,aspect_ratio=RATIO,prompt=dict(type='string',maxLength=16000)),
        'web.sources':dict(queries=dict(type='array',minItems=1,maxItems=20,uniqueItems=True,items=NONEMPTY),
                           domains=DOMAINS,model=NONEMPTY),
        'web.sources.prepared':dict(domains=DOMAINS,model=NONEMPTY),
        'web.sources.coverage':dict(catalog_path=NONEMPTY,source_pack_path=NONEMPTY,domains=DOMAINS,model=NONEMPTY),
        'web.sources.rendered':dict(domains=DOMAINS,max_pages=dict(type='integer',minimum=1,maximum=12)),
        'web.sources.native':dict(domains=DOMAINS,max_pages=dict(type='integer',minimum=1,maximum=3),
            browser=dict(type='string',enum=['safari-visual']),max_observations=dict(type='integer',minimum=2,maximum=8)),
        'hyperframes.render':dict(project_sha256=HASH,preview_sha256=HASH),
    }
    subject=object_schema(dict(id=dict(type='string',pattern='^[a-z0-9][a-z0-9-]{0,63}$'),
        label=dict(type='string',minLength=1,maxLength=200),query=dict(type='string',minLength=1,maxLength=200),
        identity=dict(type='string',minLength=1,maxLength=200),
        exclude_titles=dict(type='array',maxItems=20,items=dict(type='string',pattern='^File:',maxLength=500))),
        required=['id','label','query'])
    properties['images.collect']=dict(subjects=dict(type='array',minItems=1,maxItems=40,items=subject))
    properties['images.crop']=dict(region=dict(type='array',minItems=4,maxItems=4,items=dict(type='integer',minimum=0)))
    merge=dict(inventory_path=STRING,source_pack_path=STRING,max_records=dict(type='integer'),
        options_per_item=dict(type='integer'),count_policy=COUNT_POLICY,
        catalog_paths=dict(type='array',items=STRING,minItems=1,maxItems=20),
        review_paths=dict(type='array',items=STRING,minItems=1,maxItems=20))
    properties['sourcing.merge']=merge
    properties['records.merge']=dict(**merge,
        field_definitions=dict(type='object',additionalProperties=dict(type='string',enum=['text','price'])),
        identity_field=STRING)
    slides=dict(inventory_path=STRING,catalog_path=STRING,source_pack_path=STRING,image_path=STRING,
        photos_path=nullable(STRING),title=STRING,layout=dict(type='string',enum=['standard','readable']))
    properties['sourcing.slides']=slides
    properties['collection.slides']={**slides,'image_path':nullable(STRING)}
    photos=dict(inventory_path=STRING,catalog_path=nullable(STRING),source_pack_path=STRING,count_policy=COUNT_POLICY)
    properties['images.products']=photos
    properties['images.catalog']=dict(**photos,
        source_adapters=dict(type='array',minItems=1,maxItems=2,items=dict(type='string',enum=['observed-pages','commons'])),
        image_identity=dict(type='string',enum=['page','subject']))
    for capability in ('blender.import_asset','blender.animate','rhino.render'):
        properties[capability]=dict(manifest_sha256=HASH)
    properties['blender.animate']=dict(manifest_sha256=NONEMPTY,scene_sha256=NONEMPTY)
    for capability in ('blender.run_python','rhino.run_python','rhino3dm.run_python','rhino.grasshopper','sketchup.run_ruby'):
        scene=(NULL if capability=='rhino.grasshopper' else nullable(HASH))
        if capability=='blender.run_python':scene=nullable(NONEMPTY)
        properties[capability]=dict(scene_sha256=scene,script_sha256=NONEMPTY if capability=='blender.run_python' else HASH,checks_sha256=NONEMPTY if capability=='blender.run_python' else HASH,
                                    permissions=dict(type='string',enum=['unrestricted_host']))
    # Provider-specific model support still belongs to the media adapter check.
    for capability in ('runway.image','runway.video','higgsfield.image','higgsfield.video','meshy.mesh'):
        kind=capability.split('.')[1]
        value=dict(model=NONEMPTY,prompt=dict(type='string',minLength=1,maxLength=800 if kind=='mesh' else 1000))
        if kind!='mesh':value['aspect_ratio']=dict(type='string',enum=['16:9','9:16'])
        if kind=='video':value['duration']=dict(type='integer',minimum=2,maximum=10)
        properties[capability]=value
    handlers={cap:'orchestrator.operation_execution:'+name for name,caps in HANDLERS.items() for cap in caps}
    handlers['document.compose']='orchestrator.document_compose:execute'
    result={}
    for capability,spec in operations.items():
        if spec['parameters'] and capability not in properties:
            raise ValueError('Missing registered parameter schema: '+capability)
        available=[]
        for name,caps in {
            'search':('web.sources','web.sources.prepared','web.sources.coverage'),
            'hyperframes':HANDLERS['hyperframes'],'compose':HANDLERS['compose'],'geometry':HANDLERS['geometry'],
            'photos':(*HANDLERS['photos'],*HANDLERS['merge_photos'],*HANDLERS['catalog_photos'],*HANDLERS['crop_image']),
            'presentation_create':(*HANDLERS['presentation_create'],'images.pptx'),'presentation_edit':HANDLERS['presentation_edit'],
            'presentation_preview':HANDLERS['presentation_preview'],
            'image_conversion':('gemini.image','openai.image','openrouter.image','runway.image','higgsfield.image'),
            'native':HANDLERS['native'],
            'provider':('gemini.text','gemini.image','openai.image','openrouter.image',*HANDLERS['cloud'],'web.sources','web.sources.prepared'),
        }.items():
            if capability in caps:available.append('orchestrator.operation_availability:'+name)
        descriptions=[]
        for name,caps in {
            'gemini_model':('gemini.text','gemini.image'),
            'search':('web.sources','web.sources.prepared','web.sources.coverage'),
            'prepared':('web.sources.prepared',),'rendered':HANDLERS['rendered_sources'],
            'rhino_library_script':('rhino3dm.run_python',),'rhino_library':('rhino3dm.create',),
            'sketchup':('sketchup.startup','sketchup.inspect','sketchup.run_ruby'),
            'photos':('images.collect',),'merge_photos':HANDLERS['merge_photos'],'fetch_photos':('images.fetch',),
            'catalog_photos':HANDLERS['catalog_photos'],'presentation_preview':HANDLERS['presentation_preview'],
            'cloud':HANDLERS['cloud'],'hyperframes':HANDLERS['hyperframes'],'compose':HANDLERS['compose'],
            'presentation_create':HANDLERS['presentation_create'],'presentation_edit':HANDLERS['presentation_edit'],
            'image_provider':('openai.image','openrouter.image'),
            'image_dependency':('gemini.image','openai.image','openrouter.image','runway.image','higgsfield.image'),
            'native':HANDLERS['native'],
        }.items():
            if capability in caps:descriptions.append('orchestrator.operation_catalog:'+name)
        bindings=[]
        for name,caps in {
            'presentation':HANDLERS['presentation_preview'],
            'media':(*HANDLERS['hyperframes'],*HANDLERS['compose']),
            'sketchup':('sketchup.startup','sketchup.inspect','sketchup.run_ruby'),
            'rendered':HANDLERS['rendered_sources'],'cloud':HANDLERS['cloud'],
            'rhino':('rhino.startup','rhino.inspect','rhino.run_python','rhino.document','rhino.render','rhino.grasshopper'),
        }.items():
            if capability in caps:bindings.append('orchestrator.operation_bindings:'+name)
        inspections=[]
        for name,caps in {
            'search':HANDLERS['sources'],'rendered':HANDLERS['rendered_sources'],
            'native_effect':(*HANDLERS['native'],*HANDLERS['hyperframes'],*HANDLERS['compose'],*HANDLERS['presentation_preview']),
            'local_render':(*HANDLERS['hyperframes'],*HANDLERS['compose']),
            'library_script':('rhino3dm.run_python',),
            'sketchup':('sketchup.startup','sketchup.inspect','sketchup.run_ruby'),
        }.items():
            if capability in caps:inspections.append('orchestrator.operation_inspection:'+name)
        if spec['kind']=='api':inspections.append('orchestrator.operation_inspection:api')
        result[capability]=Adapter(object_schema(copy.deepcopy(properties.get(capability,{})),required=[k for k in properties.get(capability,{}) if k not in spec.get('optional_parameters',[])]),
            asset_binding='sha256' if capability=='document.compose' else 'path',
            references=references.get(capability,{}),
            reference_media=reference_media.get(capability,{}),
            handoffs=handoff_manifest(capability),
            validators=tuple(VALIDATORS.get(capability,())),
            max_attempts=2 if capability in ('sourcing.slides','collection.slides','pptx.render') else 1,
            handler=handlers.get(capability),
            review_evidence='orchestrator.source_fallback:review_evidence' if capability in HANDLERS['rendered_sources'] else None,
            evidence_extension='orchestrator.source_fallback:extends' if capability in HANDLERS['rendered_sources'] else None,
            preflight={'rhino.render':('orchestrator.rhino_render:bind_registered',),'blender.animate':('orchestrator.blender_animation:bind_registered',)}.get(capability,()),
            content_ports=(('catalog_path',('options',)),)
                if capability in (*HANDLERS['catalog_photos'],'sourcing.slides','collection.slides') else
                (('catalog_paths',('options',)),('review_paths',('review',)))
                if capability in HANDLERS['record_merge'] else (),
            worker_tool=capability in ('text.bundle','pptx.create','pptx.render'),
            evidence_views='orchestrator.pptx_render:evidence_views' if capability=='pptx.render' else None,
            availability=tuple(available),
            descriptions=tuple(descriptions),freeze_hooks=tuple(bindings),inspections=tuple(inspections),
            correction_kinds=('sourcing_layout',) if capability=='pptx.create' else ())
        result[capability].schema(spec)
        result[capability].manifest()
    return result
