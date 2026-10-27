"""Small offline graph, procedural-scene and paid browser boundary checks."""
import copy,hashlib,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from orchestrator import node_spec,execution,executors,host_code
from orchestrator.runtime import Runtime
from orchestrator.blender_edit import validate_checks
from orchestrator import browser_render
from orchestrator.agent_loop import Files
from task_relay.general_browser import Session
from task_relay.browser_journal import UncertainAction
from task_relay.desktop_node_runs import compile_plan
from tests.test_browser_screenshots import png
from tests.test_general_browser import Driver


def creation_checks():
 return dict(mode='create',units='Meters',objects=['Pavilion','Camera','Light'],changed_objects=[],preserve_other_objects=True,preserve_cameras=True,preserve_materials=True,
    expected_dimensions={'Pavilion':[3,3,2]},preview=dict(camera='Camera',resolution=[64,64],samples=1))

class RenderDriver(Driver):
 def __init__(self):
  super().__init__();self.prompt='';self.ready=False;self.generated=0;self.output='';self.fail=False;self.ambiguous=False;self.change=False
 def snapshot(self,tab):
  controls=[dict(tag='INPUT',type='file',label='Image',render_role='upload'),dict(tag='TEXTAREA',type='',label='Prompt',render_role='prompt',value_present=bool(self.prompt)),
    dict(tag='BUTTON',type='',label='Generate',render_role='generate'),dict(tag='BUTTON',type='',label='Download',render_role='download')]
  if self.ambiguous:controls.append(dict(controls[2]))
  return dict(url='https://app.xfigura.ai/designer?nodeId=fixture',title='Fixture',text='',controls=controls,images=[],
    image_render=dict(node='fixture',prompt=self.prompt,input_ready=self.ready,output=self.output,busy=False,error='')),list(range(len(controls)))
 def act(self,tab,el,op,args,files):
  if op=='upload':self.ready=True
  elif op=='fill':self.prompt=args['text']
  elif op=='click':
   self.generated+=1
   if self.fail:raise TimeoutError('Unknown generation outcome')
   self.output='https://app.xfigura.ai/result/fresh.png'
  elif op=='download':
   if self.change:self.output='different'
   return png()

class Pavilion(unittest.TestCase):
 def test_graph_compiles_without_hidden_nodes_and_paid_render_is_explicit(self):
  from orchestrator.operation_definition import catalog
  entries={r['id']:r for r in catalog()}
  self.assertIn('blender.geometry',entries);self.assertIn('xfigura.render',entries)
  w=json.loads(Path('examples/cellular-pavilion.workflow.json').read_text())
  self.assertIn('workflow.xfigura_url',node_spec.resolve_workflow(w)['missing_inputs'])
  with tempfile.TemporaryDirectory() as d:
   rt=Runtime(Path(d))
   try:
    with patch.object(execution,'available'),patch.object(executors,'available'):
     p=compile_plan(rt,w,{'xfigura_url':'https://app.xfigura.ai/designer?nodeId=fixture'},'pavilion','Pavilion')
   finally:rt.close()
  self.assertEqual([n['id'] for n in p['plan']['tasks']],[n['id'] for n in w['tasks']]);self.assertEqual(p['paid_nodes'],['render'])
  checks=p['plan']['tasks'][1];self.assertEqual(checks['operation_contract']['parameters']['target'],'blender.run_python')
  b=p['plan']['tasks'][2];self.assertEqual(b['execution']['parameters']['scene_sha256'],None)
  self.assertTrue(any(i['media_type']=='text/x-python' and i['from_task']=='script' for i in b['inputs']))
  self.assertEqual(p['plan']['tasks'][5]['operation_contract']['parameters']['target'],'rhino.document')
 def test_future_script_is_bound_to_exact_completed_bytes_at_approval(self):
  from tests.test_blender_operations import operation
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();artifacts={};items=[]
   for ident,raw,media in [('code',b'import bpy\n','text/x-python'),('checks',json.dumps(creation_checks()).encode(),'application/json')]:
    path=root/ident;path.write_bytes(raw);artifacts[ident]=dict(id=ident,blob=str(path),sha256=hashlib.sha256(raw).hexdigest())
    items.append(dict(from_task=ident,output=ident,path=ident,purpose='Generated input',authority='Exact completed bytes',media_type=media))
   spec=operation('blender.run_python',items);spec['dependencies']=['code','checks']
   spec['execution']['parameters']=dict(scene_sha256=None,script_sha256='code',checks_sha256='checks',permissions='unrestricted_host')
   rt=SimpleNamespace(output=lambda run,task,output:artifacts[task])
   with patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender')),patch('task_relay.host_evidence.application_signature',return_value={'fixture':True}):
    bound=host_code.binding(rt,spec,'fixture')
    self.assertEqual([i['sha256'] for i in bound['inputs']],[a['sha256'] for a in artifacts.values()])
    frozen=dict(bound['assignment'],host_code_authorization={'binding':bound},authorized_assignment_digest=bound['assignment_digest'])
    frozen['inputs']=[dict(i,artifact=a['id'],sha256=a['sha256']) for i,a in zip(frozen['inputs'],artifacts.values())]
    host_code.verify_frozen(frozen)
    (root/'code').write_text('changed')
    with self.assertRaisesRegex(ValueError,'changed'):host_code.binding(rt,spec,'fixture')
 def test_legacy_edit_definition_does_not_grant_creation(self):
  from orchestrator.operation_definition import definition,matches_capture
  from orchestrator.contracts import digest
  prior=definition('blender.run_python')
  prior['inputs']['properties']['scene_sha256']=prior['inputs']['properties']['scene_sha256']['anyOf'][0]
  self.assertTrue(matches_capture('blender.run_python',digest(prior),{'inputs':{'scene_sha256':{'artifact':'prior'}}}))
  self.assertFalse(matches_capture('blender.run_python',digest(prior),{'inputs':{'scene_sha256':{'value':None}}}))
 def test_creation_checks_preserve_legacy_and_fail_closed(self):
  from tests.test_blender_edit import checks
  validate_checks(checks());validate_checks(creation_checks())
  for field,value in [('objects',['Pavilion','Pavilion']),('changed_objects',['Original']),('units','Feet'),('mode','edit')]:
   c=creation_checks();c[field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):validate_checks(c)
  c=checks();c['objects']=['New']
  with self.assertRaises(ValueError):validate_checks(c)
 def test_prepared_create_contract_keeps_code_owned_flags(self):
  from orchestrator import prepared_schemas
  prepared_schemas.validate('blender.run_python',creation_checks(),{})
  self.assertTrue(prepared_schemas.REGISTRY['blender.run_python']['fixed']['preserve_cameras'])
 def session(self,root,driver):
  root=root.resolve();raw=png();(root/'input.png').write_bytes(raw)
  f=dict(assignment_id='fixture',workspace=str(root),backend={'type':'gemini-browser','model':'fixture'},tools=['files','browser'],browser=browser_render.policy('https://app.xfigura.ai/designer?nodeId=fixture','input.png'),
    inputs=[dict(path='input.png',media_type='image/png',sha256=hashlib.sha256(raw).hexdigest())],outputs=[dict(path=k,media_type=v) for k,v in browser_render.OUTPUTS.items()],limits=dict(output_bytes=11000000))
  db=sqlite3.connect(':memory:');self.addCleanup(db.close)
  return Session(db,'fixture',f['browser'],driver,Files(f))
 def transfer(self,s):return browser_render.transfer(s,'https://app.xfigura.ai/designer?nodeId=fixture','Wood pavilion','input.png',time.monotonic()+5)
 def test_browser_uses_existing_journal_exact_inputs_and_original_png(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);driver=RenderDriver();s=self.session(root,driver);r=self.transfer(s)
   self.assertEqual(driver.generated,1);self.assertEqual(r['node'],'fixture')
   self.assertEqual((root/'delivery/render.png').read_bytes(),png())
   self.assertEqual(s.journal.pending('managed'),[])
   requests=[json.loads(r[0]) for r in s.journal.db.execute('SELECT request FROM general_browser_actions')]
   self.assertEqual(sum(r['name']=='browser_click' for r in requests),1)
 def test_ambiguous_existing_or_changed_output_never_claims_success(self):
  for scenario in ('ambiguous','existing','change'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d:
    driver=RenderDriver()
    if scenario=='existing':driver.output='old'
    else:setattr(driver,scenario,True)
    s=self.session(Path(d),driver)
    with self.assertRaises((ValueError,browser_render.UncertainOperation)):self.transfer(s)
    self.assertEqual(driver.generated,int(scenario=='change'))
 def test_uncertain_generate_retains_pending_and_cannot_repeat(self):
  with tempfile.TemporaryDirectory() as d:
   driver=RenderDriver();driver.fail=True;s=self.session(Path(d),driver)
   with self.assertRaises((TimeoutError,UncertainAction)):self.transfer(s)
   self.assertEqual(driver.generated,1);self.assertTrue(s.journal.pending('managed'))
   with self.assertRaises((ValueError,UncertainAction)):self.transfer(s)
   self.assertEqual(driver.generated,1)
 def test_wrong_service_and_missing_selected_node_are_rejected(self):
  for url in ('https://other.test/designer?nodeId=x','https://app.xfigura.ai/designer','https://app.xfigura.ai/designer?nodeId=x&nodeId=y'):
   with self.assertRaises(ValueError):browser_render.selected(url)

if __name__=='__main__':unittest.main()
