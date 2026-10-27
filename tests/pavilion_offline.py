"""Small deterministic native Blender → geometry → drawing contract → PPTX fixture.

No model or website calls. Rhino host and xFigura transport are tested separately
with controlled fixtures; this script does not claim a native Rhino render.
"""
import hashlib,json,subprocess,tempfile
from pathlib import Path
from orchestrator.blender_edit import validate_checks
from orchestrator.rhino_document import validate as validate_drawing
from orchestrator.pptx_document import create
from tests.test_pavilion_graph import creation_checks
ROOT=Path(__file__).resolve().parents[1]
SCRIPT='''import bpy
from mathutils import Vector
# Deterministic 1D cellular automaton, rule 90; three rows become canopy modules.
row=[0,0,1,0,0];cells=[]
for generation in range(3):
    cells.extend((x,generation) for x,v in enumerate(row) if v)
    row=[(row[(x-1)%5]^row[(x+1)%5]) for x in range(5)]
parts=[]
for x,y in cells:
    bpy.ops.mesh.primitive_cube_add(size=2,location=(x,y,2))
    bpy.context.object.scale=(.45,.45,.15);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);parts.append(bpy.context.object)
for x,y in ((0,0),(4,0),(0,2),(4,2)):
    bpy.ops.mesh.primitive_cube_add(size=2,location=(x,y,.9))
    bpy.context.object.scale=(.12,.12,.9);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);parts.append(bpy.context.object)
bpy.ops.object.select_all(action='DESELECT')
for o in parts:o.select_set(True)
bpy.context.view_layer.objects.active=parts[0];bpy.ops.object.join()
bpy.context.object.name='Pavilion'
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
bpy.ops.object.camera_add(location=(8,-8,7));cam=bpy.context.object;cam.name='Camera'
cam.rotation_euler=(Vector((2,1,1))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=8
bpy.context.scene.camera=cam
bpy.ops.object.light_add(type='AREA',location=(2,-2,7));bpy.context.object.name='Light';bpy.context.object.data.energy=700;bpy.context.object.data.size=5
'''

def main():
 with tempfile.TemporaryDirectory(prefix='relay-pavilion-offline-') as folder:
  root=Path(folder).resolve();out=root/'delivery';out.mkdir()
  script=root/'pavilion.py';script.write_text(SCRIPT)
  checks=creation_checks();checks['expected_dimensions']={'Pavilion':[4.9,2.9,2.15]}
  contract=root/'checks.json';contract.write_text(json.dumps(validate_checks(checks)))
  exe='/Applications/Blender.app/Contents/MacOS/Blender'
  for mode in ('before','edit','verify'):
   r=subprocess.run([exe,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(ROOT/'orchestrator/blender_edit_worker.py'),'--',mode,'-',str(script),str(contract),str(out)],capture_output=True,timeout=90)
   if r.returncode:raise RuntimeError(mode+': '+r.stdout.decode()[-4000:]+r.stderr.decode()[-2000:])
  r=subprocess.run([exe,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(ROOT/'orchestrator/blender_inspect.py'),'--',str(out/'candidate.blend'),str(out/'inspection.json'),str(out/'geometry.json')],capture_output=True,timeout=60)
  if r.returncode:raise RuntimeError(r.stdout.decode()[-3000:]+r.stderr.decode()[-2000:])
  mesh=json.loads((out/'geometry.json').read_text());assert mesh['units']=='Meters'
  assert mesh['source_sha256']==hashlib.sha256((out/'candidate.blend').read_bytes()).hexdigest()
  # Controlled model substitute: project exact edges to plan/front; intersect
  # each face with the z=1 plane for section lines. All coordinates are measured.
  objects=[]
  def line(name,a,b):
   if a!=b:objects.append(dict(type='polyline',name=name,points=[a,b]))
  for obj in mesh['objects']:
   vs=obj['vertices'];edges=set()
   for face in obj['faces']:
    for a,b in zip(face,face[1:]+face[:1]):edges.add(tuple(sorted((a,b))))
   for i,(a,b) in enumerate(sorted(edges)):
    p,q=vs[a],vs[b];line('Plan '+str(i),[p[0],p[1],0],[q[0],q[1],0]);line('Elevation '+str(i),[p[0],p[2]+4,0],[q[0],q[2]+4,0])
   for i,face in enumerate(obj['faces']):
    hits=[]
    for a,b in zip(face,face[1:]+face[:1]):
     p,q=vs[a],vs[b]
     if (p[2]<1<q[2]) or (q[2]<1<p[2]):
      t=(1-p[2])/(q[2]-p[2]);hits.append([p[0]+t*(q[0]-p[0])+7,p[1]+t*(q[1]-p[1]),0])
    if len(hits)==2:line('Section '+str(i),*hits)
  drawing=dict(version=1,units='Meters',objects=objects,views=[dict(name='Drawings',projection='Top')],preview=dict(named_view='Drawings',resolution=[512,512]))
  validate_drawing(drawing)
  from PIL import Image,ImageDraw
  import io
  im=Image.new('RGB',(512,512),'white');pen=ImageDraw.Draw(im)
  for obj in objects:
   a,b=obj['points'];pen.line([(20+a[0]*35,480-a[1]*55),(20+b[0]*35,480-b[1]*55)],fill='black')
  buf=io.BytesIO();im.save(buf,format='PNG')
  deck=dict(version=2,title='Offline cellular pavilion fixture',slides=[dict(layout='image_grid',content=dict(title=label,per_page=1,fit='contain',items=[dict(image=key,label=label,caption='Controlled offline fixture; not a live xFigura or Rhino result.',credit='Local test')])) for label,key in [('Blender pavilion','pavilion.png'),('Projected drawing fixture','drawing.png')]])
  raw,evidence=create(deck,{'pavilion.png':(out/'after.png').read_bytes(),'drawing.png':buf.getvalue()})
  print(json.dumps(dict(blender='created and reopened',meshes=len(mesh['objects']),vertices=sum(len(o['vertices']) for o in mesh['objects']),drawing_entities=len(objects),pptx_bytes=len(raw),pptx=evidence,checks=json.loads((out/'checks.json').read_text()).get('warnings'),limitations=['Deterministic source script, no unscripted model','Drawing geometry contract and local raster fixture, not native Rhino','Browser operation separately tested with simulated selected-node DOM, no xFigura generation']),indent=2))
if __name__=='__main__':main()
