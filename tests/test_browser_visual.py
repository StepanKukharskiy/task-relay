"""Offline Chromium fixtures: generic visual fallback, authority and lost effects."""
import base64,copy,hashlib,json,sqlite3,tempfile,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from orchestrator import contracts as c,executors
from orchestrator.browser_contract import definitions,validate
from orchestrator.browser_visual import pixel_parts
from orchestrator.gemini_worker import Files
from orchestrator.browser_worker import run
from orchestrator.workers import atomic
from task_relay.general_browser import Session,PlaywrightDriver
from task_relay.browser_journal import UncertainAction
from tests.test_browser_screenshots import capture_graph,CaptureClient
from tests.test_gemini_executor import CONFIG,report
from tests.test_general_browser import policy

URL='https://example.test/canvas'
HTML='''<html><style>body{margin:0;height:1800px;background:white}canvas{position:absolute;top:20px;left:20px}#custom{position:absolute;left:400px;top:20px;background:#ccc;padding:40px}</style>
<canvas width=300 height=200></canvas><div id=custom>Custom action</div>
<script>window.count=0;window.moves=0;const c=document.querySelector('canvas');let g=c.getContext('2d');function draw(){g.fillStyle=count%2?'blue':'red';g.fillRect(0,0,300,200);}draw();c.onclick=()=>{count++;draw()};document.querySelector('#custom').onclick=()=>{count++;draw()};c.onpointermove=e=>{if(e.buttons)moves++};</script></html>'''

class Browser(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from playwright.sync_api import sync_playwright
  cls.pw=sync_playwright().start();cls.chromium=cls.pw.chromium.launch(headless=True)
 @classmethod
 def tearDownClass(cls):cls.chromium.close();cls.pw.stop()
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.addCleanup(self.temp.cleanup)
  self.context=self.chromium.new_context(viewport=dict(width=900,height=700),device_scale_factor=2);self.addCleanup(self.context.close)
  self.scope=policy(screenshots=['before.png','after.png'],visual_actions=['click','scroll','drag'])
  self.driver=PlaywrightDriver(self.context,self.scope)
  self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML))
  self.frozen=dict(assignment_id='visual',workspace=str(self.root),backend={'type':'gemini-browser'},inputs=[],outputs=[dict(path=p+s,media_type=m,purpose='Fixture pixels') for p in ('before','after') for s,m in [('.png','image/png'),('.png.json','application/json')]],tools=['files','browser'],browser=self.scope,limits={'output_bytes':10000000,'tool_calls':20})
  self.files=Files(self.frozen);self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
  self.s=Session(self.db,'visual',self.scope,self.driver,self.files);self.page=self.s.call('open','browser_open',dict(url=URL));self.tab=self.page['tab']
 def capture(self,path='before.png'):
  self.page=self.s.call('read-'+path,'browser_read',dict(tab=self.tab))
  self.image=self.s.call('capture-'+path,'browser_screenshot',dict(tab=self.tab,observation=self.page['observation'],path=path,purpose='Inspect synthetic pixels'))
  return self.image
 def args(self,**extra):return dict(tab=self.tab,observation=self.image['observation'],capture=self.image['visual']['capture'],x=80,y=80,purpose='Synthetic fixture only',**extra)
 def page_object(self):return self.driver.page(self.tab)
 def test_canvas_and_unregistered_custom_control_click_and_exact_duplicate(self):
  for x in (80,440):
   path='before.png' if x==80 else 'after.png';self.capture(path)
   args={**self.args(),'x':x}
   def committed(*a,**k):self.assertFalse(self.db.in_transaction);self.assertEqual(self.s.journal.pending('fixture')[0]['status'],'intent')
   original=self.driver.act
   with patch.object(self.driver,'act',side_effect=lambda *a,**k:(committed(),original(*a,**k))[1]):
    result=self.s.call('click-'+path,'browser_visual_click',args)
   self.assertEqual(self.s.call('click-'+path,'browser_visual_click',args),result)
  self.assertEqual(self.page_object().evaluate('count'),2)
 def test_canvas_only_change_and_viewport_change_refuse_before_dispatch(self):
  self.capture();self.page_object().evaluate('g.fillStyle="green";g.fillRect(1,1,10,10)')
  with self.assertRaisesRegex(ValueError,'pixels changed'):self.s.call('stale','browser_visual_click',self.args())
  self.assertEqual(self.page_object().evaluate('count'),0);self.assertFalse(self.s.journal.pending('fixture'))
  self.capture('after.png');self.page_object().evaluate('scrollTo(0,50)')
  with self.assertRaisesRegex(ValueError,'Viewport changed'):self.s.call('scrolled','browser_visual_click',self.args())
 def test_scroll_drag_and_coordinate_css_scaling(self):
  image=self.capture();self.assertEqual((image['visual']['width'],image['visual']['height']),(900,700))
  self.s.call('drag','browser_visual_drag',self.args(to_x=200,to_y=100));self.assertGreater(self.page_object().evaluate('moves'),0)
  self.capture('after.png');self.s.call('scroll','browser_visual_scroll',{**self.args(delta_x=0,delta_y=150),'x':800,'y':500})
  self.page_object().wait_for_function('scrollY>0');self.assertGreater(self.page_object().evaluate('scrollY'),0)
 def test_authority_bounds_expiry_consumption_and_tampering(self):
  self.capture();args=self.args()
  for changes in ({'x':-1},{'x':900},{'y':True},{'capture':'other'}):
   with self.assertRaises(ValueError):self.s.call('bad','browser_visual_click',{**args,**changes})
  self.scope['visual_actions']=['scroll']
  with self.assertRaises(ValueError):self.s.call('nogrant','browser_visual_click',args)
  self.scope['visual_actions']=['click','scroll','drag'];self.s.visuals[self.tab]['created']-=61
  with self.assertRaisesRegex(ValueError,'expired'):self.s.call('expired','browser_visual_click',args)
  self.s.visuals[self.tab]['created']+=61;(self.root/'before.png').write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'changed'):self.s.call('tampered','browser_visual_click',args)
  self.assertEqual(self.page_object().evaluate('count'),0)
 def test_lost_effect_cannot_replay(self):
  self.capture();original=self.driver.act
  def lost(*a):original(*a);raise OSError('Lost response after click')
  with patch.object(self.driver,'act',side_effect=lost):
   with self.assertRaises(UncertainAction):self.s.call('lost','browser_visual_click',self.args())
  self.assertEqual(self.page_object().evaluate('count'),1)
  self.page=self.s.call('observe','browser_read',dict(tab=self.tab))
  with self.assertRaises(UncertainAction):self.s.call('new-capture','browser_screenshot',dict(tab=self.tab,observation=self.page['observation'],path='after.png',purpose='No replay'))
  self.assertTrue(self.s.journal.pending('fixture'))
 def test_credentials_and_frames_cannot_be_bypassed(self):
  page=self.page_object();page.set_content('<input type=password style="position:absolute;left:20px;top:20px;width:200px;height:100px">')
  self.capture()
  with self.assertRaisesRegex(ValueError,'credentials'):self.s.call('password','browser_visual_click',self.args())
  page.set_content('<iframe style="position:absolute;left:20px;top:20px;width:200px;height:100px" srcdoc="safe"></iframe>')
  self.capture('after.png')
  with self.assertRaisesRegex(ValueError,'embedded'):self.s.call('frame','browser_visual_click',self.args())
 def test_custom_observe_mode_and_unauthorized_links_remain_blocked(self):
  self.scope['origins'].append('https://app.xfigura.ai');self.scope['custom_actions']=[dict(name='xFigura actions',mode='observe')]
  self.s.call('node','browser_navigate',dict(tab=self.tab,url='https://app.xfigura.ai/designer?nodeId=fixture'))
  self.page_object().set_content('<div class="cursor-pointer pointer-events-auto bg-brand" style="position:absolute;left:20px;top:20px;width:200px;height:100px"><div><div><p>Generate</p></div></div></div>')
  self.capture()
  with self.assertRaisesRegex(ValueError,'observation-only'):self.s.call('denied','browser_visual_click',self.args())
  self.page_object().set_content('<a href="https://outside.test" style="display:block;position:absolute;left:20px;top:20px;width:200px;height:100px">Other site</a>')
  self.capture('after.png')
  with self.assertRaisesRegex(ValueError,'outside'):self.s.call('outside','browser_visual_click',self.args())
  self.assertFalse(self.s.journal.pending('fixture'))
 def test_successful_click_with_failed_observation_retains_receipt_and_consumes_capture(self):
  self.capture();args=self.args();original=self.driver.snapshot
  def after(tab):
   if self.page_object().evaluate('count')>0:raise OSError('Post-click observation lost')
   return original(tab)
  with patch.object(self.driver,'snapshot',side_effect=after):result=self.s.call('click','browser_visual_click',args)
  self.assertTrue(result['driver_action_returned']);self.assertTrue(result['observation_unavailable'])
  self.assertEqual(self.s.call('click','browser_visual_click',args),result)
  self.assertEqual(self.page_object().evaluate('count'),1);self.assertNotIn(self.tab,self.s.visuals)
  with self.assertRaises(ValueError):self.s.call('new-click','browser_visual_click',args)
  self.assertFalse(self.s.journal.pending('fixture'))
 def test_capture_pixels_only_with_explicit_grant_and_exact_hash(self):
  result=self.capture()
  for provider in ('gemini','openai','qwen'):
   parts,native=pixel_parts(self.files,self.scope,result,provider)
   self.assertEqual(base64.b64decode(parts[1]['inlineData']['data']),(self.root/'before.png').read_bytes())
   self.assertIn('image',native[1]['type'])
  self.assertEqual(pixel_parts(self.files,{},result,'gemini'),([],[]))
  (self.root/'before.png').write_bytes(b'changed')
  with self.assertRaises(ValueError):pixel_parts(self.files,self.scope,result,'gemini')
 def test_live_tools_unexposed_for_old_contract_and_planner_grant_roundtrip(self):
  from task_relay import planning_contract
  self.assertFalse(any('visual_' in x['name'] for x in definitions(policy())))
  schema=planning_contract.contract({})['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']['browser']
  planning_contract.validate(self.scope,schema);validate(self.scope)
  for actions in (['click','click'],['shell'],None):
   with self.assertRaises(ValueError):validate({**self.scope,'visual_actions':actions})
  with self.assertRaises(ValueError):validate({**self.scope,'interaction_scope':''})
  with self.assertRaises(ValueError):validate({**self.scope,'screenshots':[]})
 def test_three_provider_loops_receive_pixels_then_use_visual_control(self):
  for provider in ('gemini','openai','qwen'):
   with self.subTest(provider=provider):
    ws=self.root/provider;ws.mkdir();(ws/'.relay').mkdir();control=ws/'control';control.mkdir()
    f=c.assignment(capture_graph()['tasks'][0]);f.update(assignment_id=provider,workspace=str(ws),backend=dict(type=provider+'-browser',model='fixture-model'))
    f['browser'].update(interaction_scope='Click the synthetic canvas once',visual_actions=['click'])
    config=CONFIG if provider=='gemini' else {'api_key':'fixture-only','model':'fixture-model'}
    atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,f['backend'])))
    context=self.chromium.new_context(viewport=dict(width=900,height=700))
    driver=PlaywrightDriver(context,f['browser']);context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML));client=VisualClient(f,provider)
    try:
     with sqlite3.connect(':memory:') as db:result=run(f,control,db,self.root,client=client,config_reader=lambda:(config,f['backend']),driver_context=nullcontext(driver))
     self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.calls),4)
     self.assertEqual(next(iter(driver.pages.values())).evaluate('count'),1)
     self.assertTrue(client.saw_pixels)
    finally:context.close()

class VisualClient(CaptureClient):
 saw_pixels=False
 def request(self,endpoint,payload,**kwargs):
  if len(self.calls)<2:return super().request(endpoint,payload,**kwargs)
  self.calls.append(copy.deepcopy(payload))
  if len(self.calls)==3:
   if self.provider=='gemini':
    parts=payload['contents'][-1]['parts'];capture=parts[0]['functionResponse']['response'];self.saw_pixels=any('inlineData' in p for p in parts)
   else:
    history=payload['input'] if self.provider=='openai' else payload['messages'];self.saw_pixels=any('image' in p.get('type','') for p in history[-1]['content'])
    tool=next(x for x in reversed(history) if x.get('type')=='function_call_output' or x.get('role')=='tool');capture=json.loads(tool['output'] if self.provider=='openai' else tool['content'])
   v=capture['visual'];name='browser_visual_click';args=dict(tab=v['tab'],observation=v['observation'],capture=v['capture'],x=80,y=80,purpose='Click synthetic canvas once')
  else:name,args='finish',report(self.frozen)
  if self.provider=='gemini':return dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(functionCall=dict(name=name,args=args))]))])
  call=dict(name=name,arguments=json.dumps(args))
  if self.provider=='openai':return dict(id=str(len(self.calls)),status='completed',output=[dict(type='function_call',call_id=str(len(self.calls)),**call)])
  return dict(choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content=None,tool_calls=[dict(id=str(len(self.calls)),type='function',function=call)]))])
