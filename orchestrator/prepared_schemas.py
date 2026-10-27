"""Trusted preparation schemas. Content workers never choose document envelopes.

Wire schemas describe fragments; existing operation validators remain authoritative
for relationships between fields. No renderer, host or provider runs here.
"""
import copy
import importlib
from .spatial_contract import SCHEMA as SPATIAL


def obj(fields, optional=()):
    return dict(type='object',properties=fields,required=[k for k in fields if k not in optional],additionalProperties=False)

def text(n=4000, minimum=0):return dict(type='string',minLength=minimum,maxLength=n)
def integer(lo,hi):return dict(type='integer',minimum=lo,maximum=hi)
def number(lo,hi):return dict(type='number',minimum=lo,maximum=hi)
def array(item,lo=0,hi=100):return dict(type='array',items=item,minItems=lo,maxItems=hi)
def enum(*values):return dict(type='string',enum=list(values))
def nullable(rule):return dict(anyOf=[rule,dict(type='null')])
def mapping(rule):return dict(type='object',additionalProperties=rule)
def vector(lo=-10000,hi=10000):return array(number(lo,hi),3,3)

BOOL=dict(type='boolean')
HASH=dict(type='string',pattern='^[a-f0-9]{64}$')
NAME=text(200,1)
PATH=text(500,1)
UNITS=enum('Meters','Millimeters','Centimeters','Feet','Inches')
RES=array(integer(64,1024),2,2)
PREVIEW=obj(dict(camera=NAME,resolution=RES,samples=integer(1,16)))
REGISTRY={}


def register(name,fields,validator,*,fixed=None,hash_inputs=None,optional=(),assets=False):
    constants=fixed if fixed is not None else dict(version=1)
    REGISTRY[name]=dict(schema=obj(fields,optional),fixed=constants,validator=validator,
                        hash_inputs=hash_inputs or {},assets=assets)


register('web.sources.prepared',dict(targets=array(obj(dict(id=dict(type='string',pattern='^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$'),
    queries=array(text(250,1),1,20),required_options=integer(1,10))),1,20)), 'orchestrator.web_sources:validate_prepared')
REGISTRY['web.sources.prepared']['schema']['description']='Across all target mappings, use at most 20 distinct literal queries total, each at most 250 characters. The limit is shared across targets, not 20 per target. Reuse exact query strings when one query supports several target mappings.'

shape=dict(shape=enum('cube','cylinder'),position=vector(),size=vector(.001,10000),rotation=vector(-100,100),color=vector(0,1))
camera=obj(dict(position=vector(),target=vector(),scale=number(.1,10000)))
scene=dict(spatial=SPATIAL,objects=array(obj(shape),1,500),camera=camera,resolution=array(integer(64,1600),2,2),samples=integer(1,32))
register('blender.scene',scene,'orchestrator.blender_host:scene')
mesh=obj({**shape,'shape':enum('mesh'),'vertices':array(vector(),3,100000),'faces':array(array(integer(0,99999),3,4),1,200000)})
register('blender.mesh_scene',{**scene,'objects':array(dict(anyOf=[obj(shape),mesh]),1,500)},
         'orchestrator.prepared_schemas:validate_mesh',fixed=dict(version=2))

edit_base=dict(slide=integer(1,500),shape_id=integer(1,1000000))
edits=[obj(dict(**edit_base,kind=enum('replace_text'),old=text(4000,1),new=text(4000,1))),
       obj(dict(**edit_base,kind=enum('replace_text'),row=integer(0,100),column=integer(0,100),old=text(4000,1),new=text(4000,1))),
       obj(dict(**edit_base,kind=enum('replace_image'),old_sha256=HASH,path=PATH,new_sha256=HASH,fit=enum('stretch','contain')),('fit',)),
       obj(dict(**edit_base,kind=enum('remove_shape'),old_xml_sha256=HASH)),
       obj(dict(**edit_base,kind=enum('remove_table_row'),row=integer(1,100),old_runs=array(text(4000,1),1,100)))]
for kind in ('replace_notes_text','remove_notes_run'):
    edits.append(obj(dict(kind=enum(kind),slide=integer(1,500),index=integer(0,1000),old=text(4000,1),
                          **({'new':text(4000,1)} if kind=='replace_notes_text' else {}))))
register('pptx.edit',dict(edits=array(dict(anyOf=edits),1,100)), 'orchestrator.pptx_edit:validate',
    hash_inputs=dict(source_sha256='application/vnd.openxmlformats-officedocument.presentationml.presentation'))

register('media.compose',dict(width=integer(320,1920),height=integer(320,1920),fps=dict(type='integer',enum=[15,24,30]),
    background=dict(type='string',pattern='^#[0-9a-fA-F]{6}$'),foreground=dict(type='string',pattern='^#[0-9a-fA-F]{6}$'),
    accent=dict(type='string',pattern='^#[0-9a-fA-F]{6}$'),audio=nullable(PATH),
    scenes=array(obj(dict(duration=number(.5,30),title=text(90,1),body=text(300),image=nullable(PATH),
                          entrance=enum('left','right','up','down','fade'),narration=text(1000))),1,20)),
    'orchestrator.reel_contract:validate',assets=True)
register('hyperframes.preview',dict(width=integer(320,1920),height=integer(320,1920),fps=dict(type='integer',enum=[15,24,30]),
    duration=number(.5,120),audio=BOOL,samples=array(number(0,120),1,20),files=mapping(text(15000,1)),assets=mapping(PATH)),
    'orchestrator.hyperframes_contract:validate',assets=True)

base=dict(name=text(100,1),layer=text(100,1))
point=vector(-10000000,10000000)
geometry=[obj(dict(**base,type=enum('point'),point=point)),
          obj(dict(**base,type=enum('polyline'),points=array(point,2,200000))),
          obj(dict(**base,type=enum('mesh'),vertices=array(point,3,200000),faces=array(array(integer(0,199999),3,4),1,400000)))]
register('rhino3dm.create',dict(units=UNITS,tolerance=number(1e-9,1),
    layers=array(obj(dict(name=text(100,1),color=array(integer(0,255),3,3))),1,100),objects=array(dict(anyOf=geometry),1,10000)),
    'orchestrator.rhino3dm_contract:validate')
register('blender.run_python',dict(changed_objects=array(NAME,0,100),expected_dimensions=mapping(vector(0,100000)),preview=PREVIEW,
    mode=enum('create'),objects=array(NAME,1,500),units=enum('Meters')),
    'orchestrator.blender_edit:validate_checks',fixed=dict(preserve_other_objects=True,preserve_cameras=True,preserve_materials=True),optional=('mode','objects','units'))
register('rhino.run_python',dict(mode=enum('create','edit'),units=UNITS,changed_objects=array(NAME,0,100),allow_additions=BOOL,
    expected_object_count=integer(1,5000),expected_dimensions=mapping(vector(0,1000000)),
    preview=obj(dict(resolution=RES,named_view=NAME),('named_view',)),expected_named_views=array(NAME,1,10)),
    'orchestrator.rhino_contract:validate_checks',fixed={},optional=('expected_named_views',))
native_object=dict(name=NAME)
native_geometry=[obj(dict(**native_object,type=enum('box'),min=point,max=point)),
    obj(dict(**native_object,type=enum('polyline'),points=array(point,2,2000))),
    obj(dict(**native_object,type=enum('text'),text=text(2000,1),position=point,height=number(.000001,10000))),
    obj(dict(**native_object,type=enum('dimension'),start=point,end=point,offset=dict(point,description='Absolute XYZ point on the dimension line, in document units. This is not a displacement vector from either endpoint.'),height=number(.000001,10000)))]
register('rhino.document',dict(units=UNITS,objects=array(dict(anyOf=native_geometry),1,500),
    views=array(obj(dict(name=NAME,projection=enum('Top','Front','Right','Perspective'))),1,10),
    preview=obj(dict(resolution=RES,named_view=NAME)),spatial=SPATIAL), 'orchestrator.rhino_document:validate')

register('rhino3dm.run_python',dict(mode=enum('create','edit'),file_version=integer(2,8),expected_units=nullable(NAME),
    expected_object_count=nullable(integer(0,100000)),required_objects=array(NAME,0,10000),preserve_objects=array(NAME,0,10000),
    expected_dimensions=mapping(vector(0,1e15))), 'orchestrator.rhino3dm_script_contract:validate_checks')
register('rhino.grasshopper',dict(expected_object_count=integer(1,1000),
    expected_outputs=array(obj(dict(object=NAME,output=integer(0,99),count=integer(0,100000))),1,100)),
    'orchestrator.grasshopper_contract:validate_checks',fixed=dict(version=1,mode='create'))
register('sketchup.run_ruby',dict(mode=enum('create','edit'),changed_entities=array(NAME,0,100),allow_additions=BOOL,
    expected_entity_count=integer(1,5000),expected_dimensions_mm=mapping(vector(0,1e9)),preview=obj(dict(resolution=RES))),
    'orchestrator.sketchup_contract:validate_checks')
register('rhino.render',dict(named_view=NAME,resolution=RES),'orchestrator.rhino_contract:validate_render',fixed=dict(version=1,engine='rhino_render'))
register('blender.animate',dict(mode=enum('preview','final'),frame_start=integer(1,100000),frame_end=integer(1,100000),
    fps=integer(1,60),camera=NAME,resolution=RES,samples=integer(1,16),
    tracks=array(obj(dict(object=NAME,property=enum('location','rotation_euler','scale'),
        keys=array(obj(dict(frame=integer(1,100000),value=vector())),1,20))),0,20)),
    'orchestrator.blender_animation:validate',hash_inputs=dict(scene_sha256='application/x-blender'))
REGISTRY['blender.animate']['schema']['description']='Render 1–120 contiguous frames. Preview: even 64–512 dimensions, 1–4 samples. Final: even 64–1024 dimensions, 1–16 samples. Empty tracks render the existing saved timeline. Code binds scene_sha256 from the exact connected Blender scene; do not invent hashes. No drivers, Geometry Nodes, external caches or simulation modifiers; bake procedural growth into ordinary keyframes during approved scene creation.'
register('blender.import_asset',dict(scene=PATH,
    files=array(obj(dict(path=PATH,sha256=HASH,kind=enum('scene','library','image'),
        provenance=obj(dict(source=text(2000,1),license=nullable(text(2000)))))),1,30),
    imports=array(dict(anyOf=[obj(dict(type=enum('append_objects'),library=PATH,names=array(NAME,1,100),collection=NAME)),
        obj(dict(type=enum('image_texture'),file=PATH,material=NAME,node=NAME,image_name=NAME))]),0,30),preview=PREVIEW),
    'orchestrator.blender_assets:validate')

# Registered hash fields bind exact files; fragment schemas omit them. Native
# preconditions such as old text/XML still describe the requested change and
# are checked against the actual baseline by the operation.
REGISTRY['blender.import_asset']['item_hashes']=[dict(field='files',path='path',hash='sha256')]
REGISTRY['pptx.edit']['item_hashes']=[dict(field='edits',path='path',hash='new_sha256')]


def validate_mesh(doc):
    from .blender_host import scene
    return scene(doc,allow_mesh=True)


def document_schema(name):
    spec=REGISTRY[name]
    # Validate the complete envelope too, including compiler-owned fields.
    fields={**spec['schema']['properties'],**{k:dict(type='boolean' if type(v) is bool else 'integer' if type(v) is int else 'string',enum=[v]) for k,v in spec['fixed'].items()},
            **{k:HASH for k in spec['hash_inputs']}}
    return obj(fields,set(spec['schema']['properties'])-set(spec['schema']['required']))


def validate(name,doc,assets=None):
    from .parameter_contracts import validate as check
    spec=REGISTRY[name]
    check(doc,document_schema(name))
    module,method=spec['validator'].split(':');hook=getattr(importlib.import_module(module),method)
    return hook(doc,assets) if spec['assets'] else hook(doc)


def support_modules():
    return tuple(sorted({v['validator'].split(':')[0] for v in REGISTRY.values()}|{'orchestrator.parameter_contracts'}))
