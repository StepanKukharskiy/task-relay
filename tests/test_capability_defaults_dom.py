"""Companion settings with a local bridge fixture; no real providers or accounts."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOCAL_BROWSER_FIXTURE') == '1', 'Requires local browser fixture')
class Tests(unittest.TestCase):
    def test_save_switch_reload_and_dirty_selection(self):
        from playwright.sync_api import sync_playwright, expect
        assets = Path(__file__).resolve().parents[1]/'task_relay/assets'
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width':480,'height':800})
                errors=[];page.on('pageerror', lambda error:errors.append(str(error)))
                page.add_init_script('''
                window.fixture={setup:{version:'fixture',providers:{gemini:true,openai:true},telegram:{configured:true,paired:true},doctor:{}},
                  service:{healthy:true,loaded:true},conversation:{},browser:{enabled:false,available:true},channels:{},messages:{},decisions:{},folders:[],
                  rhino:{preference:'auto',managed:false,selected:{version:'8.35'},versions:[{major:7,version:'7.32',interpreter:'IronPython 2.7'},{major:8,version:'8.35',interpreter:'CPython 3'}]},
                  model_defaults:{revision:0,choices:{},limitation:'Account access is checked when used.',capabilities:[
                    {capability:'text',available:true,selected_available:true,options:[{provider:'gemini',models:['gemini-text']}]},
                    {capability:'image',available:true,selected_available:true,options:[{provider:'gemini',models:['gemini-image']},{provider:'openai',models:['gpt-image-fixture']},{provider:'openrouter',connected:true,models:[]}]},
                    {capability:'video',available:true,selected_available:true,options:[{provider:'gemini',models:['veo-fixture']},{provider:'runway',connected:false,models:['fixture-video']},{provider:'higgsfield',connected:false,models:['fixture-video']}]},
                    {capability:'mesh',available:true,selected_available:true,options:[{provider:'meshy',models:['meshy-6']}]}]}};
                window.calls=[];
                window.__TAURI__={core:{invoke:async(command,{path,value})=>{
                  if(path==='companion-status')return structuredClone(window.fixture);
                  window.calls.push({path,value});
                  if(path==='image-model-refresh') window.fixture.model_defaults.capabilities.find(x=>x.capability==='image').options.find(x=>x.provider===value.provider).models=['vendor/image'];
                  if(path==='rhino-preference') window.fixture.rhino.preference=value.major;
                  if(path==='model-default'){
                    if(value.revision!==window.fixture.model_defaults.revision)throw new Error('Model defaults changed. Refresh before saving again.');
                    const selected={provider:value.provider,model:value.model};
                    window.fixture.model_defaults.choices[value.capability]=selected;
                    window.fixture.model_defaults.capabilities.find(x=>x.capability===value.capability).selected=selected;
                    window.fixture.model_defaults.revision++;
                  }
                  return {message:'Default saved'};
                }},event:{listen:async()=>{}},opener:{openUrl:async()=>{}}};
                ''')
                def asset(route):
                    from urllib.parse import urlsplit
                    name = Path(urlsplit(route.request.url).path).name or 'companion.html'
                    if name not in ('companion.html','companion.js','companion-setup.js','companion.css','messages-icon.png'):
                        return route.fulfill(status=404,body='')
                    route.fulfill(path=assets/name)
                page.route('http://127.0.0.1:33222/**',asset)
                page.goto('http://127.0.0.1:33222/')
                page.locator('#settings > summary').click()
                page.locator('#model-settings > summary').click()
                image=page.get_by_role('combobox',name='Images provider',exact=True)
                image.select_option('openai')
                page.evaluate('render(structuredClone(window.fixture))')
                self.assertEqual(image.input_value(),'openai')
                self.assertEqual(page.get_by_role('combobox',name='Images model',exact=True).input_value(),'gpt-image-fixture')
                page.get_by_role('button',name='Save images default',exact=True).click()
                page.wait_for_function('window.fixture.model_defaults.revision===1 && !modelDefaultsDirty')
                self.assertEqual(page.evaluate('window.calls[0]'), {'path':'model-default','value':{'revision':0,'capability':'image','provider':'openai','model':'gpt-image-fixture'}})
                page.get_by_role('combobox',name='Video clips provider',exact=True).select_option('gemini')
                page.evaluate('window.fixture.model_defaults.revision++; render(structuredClone(window.fixture))')
                page.get_by_role('button',name='Save video clips default',exact=True).click()
                expect(page.locator('#feedback')).to_contain_text('Model defaults changed')
                page.get_by_role('button',name='Reload saved choices',exact=True).click()
                page.wait_for_function('!modelDefaultsDirty')
                self.assertEqual(image.input_value(),'openai')
                self.assertEqual(page.get_by_role('combobox',name='Video clips provider',exact=True).input_value(),'')
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), True)
                page.locator('#model-settings').screenshot(path='outputs/capability-defaults-settings.png')
                page.locator('#model-settings > details > summary').click()
                page.locator('#media-provider-name').select_option('higgsfield')
                expect(page.locator('#media-provider-key-label')).to_have_text('API key ID:secret')
                page.locator('#media-provider-key').fill('fixture:secret')
                page.get_by_role('button',name='Save media connection',exact=True).click()
                expect(page.locator('#media-provider-key')).to_have_value('')
                self.assertEqual(page.evaluate('window.calls.at(-1)'),{'path':'media-provider','value':{'provider':'higgsfield','key':'fixture:secret'}})
                page.locator('#model-settings').screenshot(path='outputs/cloud-media-settings.png')
                page.locator('#browser-settings > summary').click()
                page.evaluate("window.fixture.browser.enabled=true; render(structuredClone(window.fixture)); document.getElementById('channel-telegram').setAttribute('aria-checked','true')")
                styles=page.evaluate("['browser-toggle','channel-telegram','channel-messages'].map(id=>{const e=document.getElementById(id);e.setAttribute('aria-checked','true');const s=getComputedStyle(e);return [s.borderRadius,s.minWidth,s.backgroundColor,s.color]})")
                self.assertEqual(styles[0],styles[1]);self.assertEqual(styles[0],styles[2])
                page.locator('#browser-settings').screenshot(path='outputs/cloud-media-browser-switch.png')
                page.get_by_role('combobox',name='Video clips provider',exact=True).select_option('runway')
                expect(page.get_by_role('button',name='Save video clips default',exact=True)).to_be_disabled()
                page.locator('#model-video-provider').locator('..').get_by_role('button',name='Connect provider',exact=True).click()
                expect(page.locator('#media-provider-name')).to_have_value('runway')
                page.get_by_role('combobox',name='Images provider',exact=True).select_option('openrouter')
                expect(page.get_by_role('button',name='Save images default',exact=True)).to_be_disabled()
                page.get_by_role('button',name='Refresh image models',exact=True).click()
                page.wait_for_function('!modelDefaultsDirty')
                page.get_by_role('combobox',name='Images provider',exact=True).select_option('openrouter')
                expect(page.get_by_role('combobox',name='Images model',exact=True)).to_have_value('vendor/image')
                page.locator('#rhino-preference').select_option('7')
                page.evaluate('render(structuredClone(window.fixture))')
                expect(page.locator('#rhino-preference')).to_have_value('7')
                page.get_by_role('button',name='Save Rhino preference',exact=True).click()
                page.wait_for_function("window.fixture.rhino.preference==='7' && !rhinoPreferenceDirty")
                self.assertEqual(errors,[])
            finally: browser.close()
