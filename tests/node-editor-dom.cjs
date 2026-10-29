// Composed UI navigation over small saved records. No runtime or provider execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.dataset={};this.style={};this.hidden=false;this.value='';this._text='';this.clientWidth=1000;this.clientHeight=700;this.offsetHeight=27;this.offsetTop=80;this.isConnected=true;const c=new Set();this.classList={add:(...v)=>v.forEach(x=>c.add(x)),remove:(...v)=>v.forEach(x=>c.delete(x)),contains:x=>c.has(x),toggle(x,on){on?c.add(x):c.delete(x);}};}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join(' ');}
 set textContent(v){this._text=String(v);this.children=[];}
 append(...nodes){for(const n of nodes){n.remove();n.parentElement=this;this.children.push(n);}}
 insertBefore(n,b){n.remove();n.parentElement=this;this.children.splice(this.children.indexOf(b),0,n);}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 replaceChildren(...nodes){this.children.forEach(n=>n.parentElement=null);this.children=[];this._text='';this.append(...nodes);}
 setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}addEventListener(k,v){this['on'+k]=v;}
 querySelectorAll(selector){const names=selector.split(',');return walk(this).slice(1).filter(e=>names.includes(e.tagName));}
 querySelector(selector){const names=selector.split(',');return walk(this).slice(1).find(e=>names.includes(e.tagName) || names.some(s=>s.startsWith('.')&&(e.className || '').split(' ').includes(s.slice(1)))) || null;}
 getBoundingClientRect(){return {left:0,top:0,width:1000,height:700};}
 setPointerCapture(id){this.capture=id;}hasPointerCapture(id){return this.capture===id;}releasePointerCapture(){this.capture=null;}
 focus(){}scrollIntoView(){}
}
const walk=e=>[e,...e.children.flatMap(walk)],ids=new Map(),el=id=>{if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);};
const document={body:new Element('body'),hidden:false,getElementById:el,querySelectorAll:()=>[],createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)};

const cp=require('node:child_process'),os=require('node:os'),path=require('node:path');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'relay-node-editor-'));
const python=process.env.RELAY_TEST_PYTHON || 'python3';
const calls=[],frames=[],submissions=[];let savedConnection=null,sharedText=null;
function backend(action,value={}){
 if(action==='node-files')return {files:[]};
 if(action==='node-setup')return {text:[{provider:'codex',models:['gpt-6.1-sol','gpt-6-sol']},{provider:'gemini',models:['fixture']}],capabilities:[{capability:'text',...(sharedText || {}),options:[{provider:'gemini',models:['fixture'],connected:!!savedConnection}]}],operations:{model:{worker:true},'web.fetch':{worker:false},'gemini.image':{worker:false,provider:'gemini'}},credential_file:'/private/fixture/.env'};
 if(action==='node-connect'){savedConnection={...value};return {message:'Saved locally'};}
 if(action==='node-run-preview')return {fingerprint:'fixture-hash',blockers:[],paid_nodes:['model'],plan:{tasks:[{id:'model',worker:{backend:{model:'fixture'}},limits:{seconds:600,provider_requests:24},max_attempts:2}],concurrency:3}};
 if(action==='node-run-start'){submissions.push(JSON.parse(JSON.stringify(value)));if(submissions.length===1)throw Error('Unknown response');return {run:'fixture-run'};}

 const script="import sys,json;from pathlib import Path;from types import SimpleNamespace;from task_relay import desktop_node_drafts as drafts;from orchestrator import node_spec,operation_definition;drafts.PATHS=SimpleNamespace(data=Path(sys.argv[1]));a,v=json.load(sys.stdin);print(json.dumps({'operations':operation_definition.catalog()} if a=='node-catalog' else {'validation':node_spec.resolve_workflow(v['workflow'])} if a=='node-validate' else drafts.dispatch(a,v)))";
 const r=cp.spawnSync(python,['-B','-X','pycache_prefix=/dev/null','-c',script,tmp],{input:JSON.stringify([action,value]),encoding:'utf8'});
 if(r.status)throw Error(r.stderr);return JSON.parse(r.stdout);
}
const storage=new Map();const localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
const window={addEventListener(k,f){this["on"+k]=f;},removeEventListener(k,f){if(this["on"+k]===f)delete this["on"+k];}};const ctx=vm.createContext({window,document,console,localStorage,setTimeout,clearTimeout,crypto:require("node:crypto"),ResizeObserver:class{observe(){}disconnect(){}},requestAnimationFrame:f=>frames.push(f)});
for(const file of ['companion-workflow.js','companion-node-editor.js'])vm.runInContext(fs.readFileSync('task_relay/assets/'+file,'utf8'),ctx);
const node=(t,text,cls)=>{const e=new Element(t);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const button=(t,fn,cls)=>{const e=node('button',t,cls);e.onclick=fn;return e;};
const saved=(t,v)=>{const e=node('details');e.append(node('summary',t),node('pre',JSON.stringify(v)));return e;};
const cls=(e,k)=>walk(e).filter(n=>(n.className || '').split(' ').includes(k)||n.classList.contains(k));
const btn=(e,t)=>walk(e).find(n=>n.tagName==='button' && n.textContent.trim()===t);
const field=(e,t)=>walk(e).find(n=>n.attributes['aria-label']===t);
const flush=async()=>{await new Promise(r=>setImmediate(r));frames.splice(0).forEach(f=>f());};
const opts={node,button,saved,stateLabel:s=>s,leave(){},request:async(a,v={})=>{calls.push(a);return backend(a,v);}};
(async()=>{
 const root=new Element('div');let dispose=window.RelayNodeEditor.mount(root,opts);await flush();
 field(root,'Job title').value='Named empty canvas';field(root,'Job title').oninput();
 await btn(root,'Save').onclick();await flush();
 const emptyListing=backend('node-drafts');assert.equal(emptyListing.items.length,1);assert.equal(emptyListing.items[0].title,'Named empty canvas');
 const emptySaved=backend('node-draft',{id:emptyListing.items[0].id});assert.equal(emptySaved.workflow.tasks.length,0);
 dispose();dispose=window.RelayNodeEditor.mount(root,{...opts,record:emptySaved});await flush();
 assert.equal(field(root,'Job title').value,'Named empty canvas');assert.match(root.textContent,/Named empty canvas|Save/);
 assert(btn(root,'Chat'));assert.equal(cls(root,'job-chat-panel')[0].hidden,false);assert(field(root,'Describe your workflow'));assert.equal(field(root,'Describe your workflow').parentElement,cls(root,'workflow-chat-composer')[0],'composer is separate from scrolling transcript');assert.equal(btn(root,'Send').parentElement,cls(root,'workflow-chat-composer')[0]);
 btn(root,'+ Step').onclick();await flush();
 const categoryNames=['AI & text','Web & research','Images','Video & audio','3D & CAD','Documents & presentations','Data'];
 assert.deepEqual(cls(root,'node-picker-group').map(g=>g.attributes['aria-label']),categoryNames);
 const catalog=backend('node-catalog').operations;
 assert.equal(cls(root,'node-choice').length,catalog.length,'every visible operation appears once');
 assert.equal(cls(root,'operation-icon').length,catalog.length,'platform icons remain');
 const search=field(root,'Search nodes');
 search.value='higgsfield';search.oninput();
 assert.deepEqual(cls(root,'node-picker-group').map(g=>g.attributes['aria-label']),['Images','Video & audio']);
 assert.equal(cls(root,'node-choice').length,2);
 search.value='3D & CAD';search.oninput();
 assert.deepEqual(cls(root,'node-picker-group').map(g=>g.attributes['aria-label']),['3D & CAD']);
 search.value='web.fetch';search.oninput();
 assert.equal(cls(root,'node-choice').length,1);
 search.value='no-node-matches-this';search.oninput();
 assert.equal(cls(root,'node-picker-group').length,0);assert.match(root.textContent,/No matching nodes/);
 search.value='';search.oninput();
 for(const group of cls(root,'node-picker-group')){
   const titles=cls(group,'node-choice').map(b=>b.querySelector('strong').textContent);
   assert.deepEqual(titles,[...titles].sort((a,b)=>a.localeCompare(b)));
 }
 async function add(id){btn(root,'+ Step').onclick();await flush();const title=backend('node-catalog').operations.find(r=>r.id===id).title;const choice=cls(root,'node-choice').find(n=>n.querySelector('strong')?.textContent===title);assert(choice);choice.onclick();await flush();}
 await add('web.fetch');let url=field(root,'Url source');assert(url);url.value='value';const input=field(root,'Url');input.value='https://example.com/article';input.onchange();await flush();
 await add('model');
 assert.equal(btn(root,'Add input').disabled,true);
 const callsBeforeBlank=calls.length;btn(root,'Add input').onclick();await flush();
 assert.equal(calls.length,callsBeforeBlank,'blank name never reaches schema validation');
 assert.match(root.textContent,/Enter an input name/);
 field(root,'Input name').value=' ';field(root,'Input name').oninput();assert.equal(btn(root,'Add input').disabled,true);
 field(root,'Input type').value='artifact';field(root,'Input type').onchange();field(root,'Input name').value='article';field(root,'Input name').oninput();assert.equal(btn(root,'Add input').disabled,false);btn(root,'Add input').onclick();await flush();
 const output=field(root,'article from step');output.value=JSON.stringify({task:'web-fetch',output:'page'});output.onchange();await flush();
 assert.equal(cls(root,'workflow-node').length,2);assert.equal(cls(root,'workflow-lines')[0].children.length,1,'actual named output reference is a wire');assert.notEqual(cls(root,'workflow-node')[0].style.left,cls(root,'workflow-node')[1].style.left,'connecting nodes lays out the new dependency');
 assert.equal(walk(root).filter(e=>e.tagName==='button' && String(e.attributes['aria-label']).startsWith('Run ')).length,2,'draft nodes have Run buttons');
 await btn(root,'Save').onclick();await flush();const listing=backend('node-drafts');assert.equal(listing.items.length,1);const stored=backend('node-draft',{id:listing.items[0].id});
 assert.deepEqual(stored.workflow.tasks[1].inputs.article,{task:'web-fetch',output:'page'});assert.equal(stored.workflow.tasks[0].inputs.url.value,'https://example.com/article');
 dispose();dispose=window.RelayNodeEditor.mount(root,{...opts,record:stored});await flush();assert.equal(cls(root,'workflow-node').length,2);assert.equal(cls(root,'workflow-lines')[0].children.length,1);cls(root,'workflow-step')[1].onclick();const restored=field(root,'article from step');assert(restored.children.some(option=>option.value===restored.value),'saved key order must still select the matching source output');assert.notEqual(restored.value,'');await flush();
 let provider=field(root,'Provider');provider.value='codex';provider.onchange();await flush();assert(field(root,'Model').children.some(o=>o.value==='gpt-6.1-sol'));assert.equal(field(root,'Model ID').attributes.autocorrect,'off');provider=field(root,'Provider');provider.value='gemini';provider.onchange();await flush();field(root,'Model ID').value='fixture';field(root,'Model ID').onchange();await flush();
 let password=field(root,'API key');assert.equal(btn(root,'Save connection').disabled,true);
 await btn(root,'Save connection').onclick();assert.equal(savedConnection,null,'empty click cannot overwrite an existing credential');
 password.value='fixture-secret';password.oninput();assert.equal(btn(root,'Save connection').disabled,false);
 await btn(root,'Save connection').onclick();await flush();assert.equal(password.value,'');assert.equal(savedConnection.key,'fixture-secret');
 assert.match(root.textContent,/do not need to enter it again/);
 assert(btn(root,'Replace saved API key'));btn(root,'Replace saved API key').onclick();
 assert.equal(field(root,'API key').value,'','saved secret never reaches the UI');
 field(root,'Tools').value='python';field(root,'Tools').onchange();await flush();
 field(root,'Model ID').value='fixture-python';field(root,'Model ID').onchange();await flush();
 await btn(root,'Save').onclick();await flush();
 assert.deepEqual(backend('node-draft',{id:stored.id}).workflow.tasks[1].model,{provider:'gemini',id:'fixture-python',tools:'python'},'explicit tools survive model edits and save');
 field(root,'Tools').value='files';field(root,'Tools').onchange();await flush();
 field(root,'Model ID').value='fixture';field(root,'Model ID').onchange();await flush();
 await btn(root,'Save').onclick();await flush();const updated=backend('node-draft',{id:stored.id});assert.deepEqual(updated.workflow.tasks[1].model,{provider:'gemini',id:'fixture'});assert(!JSON.stringify(updated).includes('fixture-secret'));
 await btn(root,'Run').onclick();await flush();assert.equal(btn(root,'Check run'),undefined);assert.equal(walk(root).find(n=>n.type==='checkbox'),undefined);assert.equal(submissions.length,0,'preview does not authorize payment');
 await btn(root,'Run · paid').onclick();await flush();await btn(root,'Check same submission').onclick();assert.deepEqual(submissions[0],submissions[1]);assert.equal(submissions.length,2);assert.equal(submissions[0].allow_paid,true);dispose();
 // Direct output connection supplies the existing model schema and binding atomically.
 const quickWorkflow={schema_version:1,kind:'workflow',inputs:{},tasks:[
   {schema_version:3,id:'read',operation:'web.fetch',objective:'Read a web page',inputs:{url:{value:'https://example.com/article'}}},
   {schema_version:3,id:'summary',operation:'model',objective:'Summarise the supplied page',input_definitions:{'input-page':{type:'string',label:'Existing input',required:false}},inputs:{},outputs:[{name:'summary',media_type:'text/markdown',purpose:'Summary'}]}
 ]};
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{title:'Quick connection',workflow:quickWorkflow}});await flush();
 cls(root,'workflow-step')[1].onclick();await flush();
 const quick=field(root,'Connect node output');assert.equal(quick.children.length,2,'self output is excluded');
 quick.value=JSON.stringify({task:'read',output:'page'});quick.onchange();await flush();
 assert.equal(cls(root,'workflow-lines')[0].children.length,1);
 assert.equal(field(root,'Connect node output'),undefined,'already connected output is excluded');
 await btn(root,'Save').onclick();await flush();
 const quickRecord=backend('node-drafts').items.map(r=>backend('node-draft',{id:r.id})).find(r=>r.title==='Quick connection');
 assert.deepEqual(quickRecord.workflow.tasks[1].inputs['input-page-2'],{task:'read',output:'page'});
 assert.deepEqual(quickRecord.workflow.tasks[1].input_definitions['input-page-2'],{type:'artifact',label:'Page',media_type:'application/json',required:true});
 assert.deepEqual(quickRecord.workflow.tasks[0],quickWorkflow.tasks[0]);
 dispose();dispose=window.RelayNodeEditor.mount(root,{...opts,record:quickRecord});await flush();
 assert.equal(cls(root,'workflow-lines')[0].children.length,1,'automatic connection survives reload');dispose();
 // Native prompt needs no producer node or prompt file; settings come from the actual schema.
 dispose=window.RelayNodeEditor.mount(root,opts);await flush();await add('gemini.image');await flush();
 assert(field(root,'Prompt'));assert.equal(field(root,'Prompt source').parentElement.parentElement.tagName,'details','reusable-input controls are collapsed');assert(field(root,'Model'));assert.equal(field(root,'Model ID').parentElement.parentElement.tagName,'details','custom model field is secondary');field(root,'Prompt').value='A red chair on white';field(root,'Prompt').onchange();await flush();
 assert.equal(field(root,'Aspect ratio').tagName,'select');assert.equal(field(root,'Aspect ratio').value,JSON.stringify('1:1'));
 field(root,'Model ID').value='fixture-image';field(root,'Model ID').onchange();await flush();await btn(root,'Save').onclick();await flush();
 const imageRecord=backend('node-drafts').items.map(r=>backend('node-draft',{id:r.id})).find(r=>r.workflow.tasks[0].operation==='gemini.image');
 assert.equal(imageRecord.title,'A red chair on white','unnamed canvas is named from its prompt on save');
 assert.equal(imageRecord.workflow.tasks.length,1);assert.equal(imageRecord.workflow.tasks[0].inputs.prompt.value,'A red chair on white');assert(!imageRecord.workflow.tasks[0].inputs.files);
 dispose();
 // Ordered multi-file bindings use actual shared graph validation, without executing a worker.
 const producer=id=>({schema_version:3,id,operation:'model',objective:id,input_definitions:{},inputs:{},outputs:[{name:'bundle',media_type:'application/zip',purpose:'Bundle'}]});
 const multi={schema_version:1,kind:'workflow',inputs:{},tasks:[producer('first'),producer('second'),{schema_version:3,id:'merge',operation:'images.merge',objective:'Merge',inputs:{}}]};
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{workflow:multi,title:'Multiple files'}});await flush();cls(root,'workflow-step')[2].onclick();await flush();
 let pick=field(root,'File bundle from step') || walk(root).find(e=>e.attributes['aria-label']?.endsWith('from step'));
 for(const id of ['first','second']){pick=walk(root).find(e=>e.attributes['aria-label']?.endsWith('from step'));pick.value=JSON.stringify({task:id,output:'bundle'});pick.onchange();await flush();}
 assert.equal(btn(root,'Apply files'),undefined);await btn(root,'Connect files').onclick();await flush();await btn(root,'Save').onclick();await flush();
 const multirecord=backend('node-drafts').items.map(r=>backend('node-draft',{id:r.id})).find(r=>r.title==='Multiple files');
 assert.deepEqual(multirecord.workflow.tasks[2].inputs.files.value,[{task:'first',output:'bundle'},{task:'second',output:'bundle'}]);
 dispose();dispose=window.RelayNodeEditor.mount(root,{...opts,record:multirecord});await flush();cls(root,'workflow-step')[2].onclick();await flush();
 btn(root,'Move up second → Bundle').onclick();await btn(root,'Connect files').onclick();await flush();await btn(root,'Save').onclick();await flush();
 assert.deepEqual(backend('node-draft',{id:multirecord.id}).workflow.tasks[2].inputs.files.value,[{task:'second',output:'bundle'},{task:'first',output:'bundle'}]);dispose();
 // Changing provider or clearing Model ID removes the old executable choice.
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:updated});await flush();cls(root,'workflow-step')[1].onclick();await flush();
 provider=field(root,'Provider');provider.value='codex';provider.onchange();await flush();await btn(root,'Save').onclick();await flush();assert(!backend('node-draft',{id:updated.id}).workflow.tasks[1].model);
 field(root,'Model ID').value='gpt-6.1-sol';field(root,'Model ID').onchange();await flush();field(root,'Model ID').value='';field(root,'Model ID').onchange();await flush();await btn(root,'Save').onclick();await flush();assert(!backend('node-draft',{id:updated.id}).workflow.tasks[1].model);dispose();
 // A saved producer is real read-only context, not an executable copied task.
 const continuation=JSON.parse(JSON.stringify(imageRecord));
 continuation.origin={mode:'input',source_run:'original'};
 continuation.workflow.tasks[0].inputs.files={value:[{artifact:'cup-image'}]};
 continuation.completed_sources=[{node:{id:'saved-original',run:'original',operation:'gemini.image',objective:'Original red cup',status:'completed',reused_source:true,prompt:'A red cup',planned_inputs:[],planned_outputs:[{path:'outputs/result.png',media_type:'image/png'}]},file:{id:'cup-image',task:'saved-original',path:'outputs/result.png',sha256:'exact-pixels'}}];
 let thumbnail;
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:continuation,outputThumbnail:f=>{thumbnail=f;return new Element('img');}});
 await flush();
 assert.equal(cls(root,'workflow-node').length,2);assert.equal(cls(root,'workflow-lines')[0].children.length,1);
 assert.equal(thumbnail.id,'cup-image');
 assert.match(root.textContent,/Saved result · will not rerun/);
 cls(root,'workflow-step')[0].onclick();await flush();
 assert.match(root.textContent,/Completed source · exact saved result/);
 assert.equal(btn(root,'Remove step'),undefined,'saved producer cannot be edited or removed as a runnable task');
 cls(root,'workflow-step')[1].onclick();await flush();
 assert(field(root,'Prompt'));assert.match(root.textContent,/Original red cup → result.png \(saved file\)/);
 assert.equal(continuation.workflow.tasks.length,1,'read-only producer never becomes an executable task');
 dispose();
 assert(calls.every(a=>['node-files','node-catalog','node-validate','node-draft-save','node-setup','node-connect','node-run-preview','node-run-start'].includes(a)));
 // An executed canvas uses the SAME editor/document; both nodes stay editable.
 let canvasRecord={canvas:'owning-canvas',revision:'v1',title:'Two images',values:{},workflow:JSON.parse(JSON.stringify(imageRecord.workflow))},opened,openedScope;
 canvasRecord.workflow.tasks[0].id='red';
 const blue=JSON.parse(JSON.stringify(canvasRecord.workflow.tasks[0]));blue.id='blue';blue.inputs.files={value:[{task:'red',output:'result'}]};canvasRecord.workflow.tasks.push(blue);
 const commands=[];
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,onRun:(r,scope)=>{opened=r;openedScope=scope;},request:async(a,v={})=>{
   commands.push({a,v:JSON.parse(JSON.stringify(v))});
   if(a==='node-canvas-save'){assert.equal(v.run,'owning-canvas');canvasRecord={...canvasRecord,...v,revision:'v2',missing_inputs:[]};return canvasRecord;}
   if(a==='node-run-start')return {run:'execution-version',canvas_run:'owning-canvas'};
   return backend(a,v);
 }});await flush();
 assert.equal(cls(root,'workflow-node').length,2);assert(!root.textContent.includes('will not rerun'));
 cls(root,'workflow-step')[0].onclick();await flush();assert(field(root,'Prompt'));assert.equal(btn(cls(root,'workflow-inspector')[0],'Run this node'),undefined);assert.equal(cls(root,'canvas-node-run').length,2);
 field(root,'Prompt').value='New first image';field(root,'Prompt').onchange();await flush();
 await btn(root,'Save').onclick();assert.equal(canvasRecord.workflow.tasks[0].inputs.prompt.value,'New first image');
 await cls(root,'canvas-node-run')[0].onclick();await flush();assert.equal(btn(root,'Check run'),undefined);
 assert.equal(commands.filter(c=>c.a==='node-run-preview').at(-1).v.scope,'red');
 assert(btn(cls(root,'workflow-node')[0],'Run · paid'),'paid confirmation is on its node');
 assert.equal(cls(root,'node-library')[0].hidden,true,'node Run never opens the library panel');
 assert.equal(commands.filter(c=>c.a==='node-run-preview').at(-1).v.canvas,'owning-canvas');
 await btn(root,'Run · paid').onclick();assert.equal(openedScope,'red');assert.equal(opened,'owning-canvas','execution returns to the same canvas, not its execution record');
 await btn(root,'Run').onclick();await flush();assert.equal(btn(root,'Check run'),undefined);
 assert.equal(commands.filter(c=>c.a==='node-run-preview').at(-1).v.scope,'all');
 assert(!commands.some(c=>c.a==='node-draft-save'),'editing an existing canvas cannot create a separate draft');
 dispose();
 const third=JSON.parse(JSON.stringify(blue));third.id='third';third.objective='Edit blue cup';delete third.inputs.files;
 canvasRecord.workflow.tasks[1].objective='Make cup blue';canvasRecord.workflow.tasks.push(third);
 const reviewRequest=async(a,v={})=>{
   if(a==='node-canvas-save'){canvasRecord={...canvasRecord,...v,revision:'v3',missing_inputs:[]};return canvasRecord;}
   return backend(a,v);
 };
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,request:reviewRequest,selection:'third'});await flush();
 let refsPicker=field(root,'Reference files from step');assert(refsPicker,'reference input is visible for an empty image node');
 assert(!refsPicker.parentElement.parentElement.parentElement.tagName.includes('details'));
 assert(refsPicker.children.some(c=>c.textContent==='Make cup blue → Generated image'));
 refsPicker.value=JSON.stringify({task:'blue',output:'result'});refsPicker.onchange();await flush();
 assert.equal(cls(root,'workflow-lines')[0].children.length,2,'third-node wire appears without Apply');
 assert.match(root.textContent,/Make cup blue → Generated image/);assert(!root.textContent.includes('blue / result'));
 refsPicker=field(root,'Reference files from step');refsPicker.value=JSON.stringify({task:'blue',output:'result'});refsPicker.onchange();await flush();
 assert.match(root.textContent,/already connected/);
 field(root,'Prompt').value='Add a white stripe';field(root,'Prompt').onchange();await flush();
 await btn(root,'Save').onclick();await flush();
 assert.deepEqual(JSON.parse(JSON.stringify(canvasRecord.workflow.tasks[2].inputs.files.value)),[{task:'blue',output:'result'}],'connection survives another field edit with no duplicates');
 dispose();dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,request:reviewRequest,selection:'third'});await flush();
 assert.match(root.textContent,/Make cup blue → Generated image/);
 btn(root,'Remove Make cup blue → Generated image').onclick();await flush();await btn(root,'Save').onclick();
 assert(!canvasRecord.workflow.tasks[2].inputs.files,'Remove persists without Apply');dispose();
 // Node Run checks automatically in the card. Cancel suppresses late previews;
 // unpaid starts once; blockers never dispatch; requested inputs remain fillable.
 let resolvePreview,started=0,checkedCount=0;
 const controlRequest=async(a,v={})=>{
   if(a==='node-run-preview'){checkedCount++;return new Promise(r=>resolvePreview=r);}
   if(a==='node-run-start'){started++;return {canvas_run:'owning-canvas'};}
   return reviewRequest(a,v);
 };
 const paidPreview={fingerprint:'fixture',paid_nodes:['red'],blockers:[],plan:{tasks:[{id:'red'}]}};
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,request:controlRequest});await flush();
 cls(root,'workflow-step')[0].onclick();field(root,'Close inspector').onclick();
 const runningClick=cls(root,'canvas-node-run')[0].onclick();await flush();
 assert.match(cls(root,'workflow-node')[0].textContent,/Checking/);
 assert.equal(cls(root,'workflow-inspector')[0].hidden,true,'Run leaves the closed inspector closed');
 assert.equal(cls(root,'canvas-node-run')[0].disabled,true);
 await cls(root,'canvas-node-run')[0].onclick();assert.equal(checkedCount,1,'double click cannot make another preview');
 btn(cls(root,'workflow-node')[0],'Cancel').onclick();assert.equal(cls(root,'canvas-node-run')[0].disabled,false);
 resolvePreview(paidPreview);await runningClick;assert.equal(btn(root,'Run · paid'),undefined);assert.equal(started,0);
 dispose();
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,request:async(a,v)=>{
   if(a==='node-run-preview')return {...paidPreview,paid_nodes:[]};
   if(a==='node-run-start'){assert.equal(v.allow_paid,false);started++;return {canvas_run:'owning-canvas'};}
   return reviewRequest(a,v);
 }});await flush();await cls(root,'canvas-node-run')[0].onclick();assert.equal(started,1,'unpaid node runs after automatic validation');dispose();
 // Host scripts use exact native approval even when no paid provider is involved.
 let nativeSubmission;
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,request:async(a,v)=>{
   if(a==='node-run-preview')return {...paidPreview,paid_nodes:[],host_reviews:[{node:'red',operation:'blender.run_python',digest:'exact-binding',documents:[{path:'inputs/script.py',sha256:'exact-sha',text:'print("saved code")'}]}]};
   if(a==='node-run-start'){nativeSubmission=v;return {canvas_run:'owning-canvas'};}
   return reviewRequest(a,v);
 }});await flush();await cls(root,'canvas-node-run')[0].onclick();
 assert.equal(nativeSubmission,undefined,'host scripts cannot auto-start after checks');
 assert.match(root.textContent,/not sandboxed/);assert.match(root.textContent,/print\("saved code"\)/);
 await btn(root,'Approve script & run').onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(nativeSubmission.approve_host_code)),[{node:'red',digest:'exact-binding'}]);
 assert.equal(nativeSubmission.allow_paid,false);dispose();
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,request:async(a,v)=>{
   if(a==='node-run-preview')return {...paidPreview,blockers:[{node:'red',message:'Missing source'}]};
   if(a==='node-run-start')throw Error('A blocked preview must never dispatch');
   return reviewRequest(a,v);
 }});await flush();await cls(root,'canvas-node-run')[0].onclick();
 assert.match(cls(root,'workflow-node')[0].textContent,/Missing source/);assert.equal(btn(root,'Run · paid'),undefined);dispose();
 const requested=JSON.parse(JSON.stringify(canvasRecord));requested.workflow.inputs={caption:{type:'string',required:true,label:'Caption'}};
 let provided,formStarts=0;
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:requested,request:async(a,v)=>{
   if(a==='node-run-preview'){provided=v.values;return {...paidPreview,blockers:v.values.caption?[]:[{node:'red',message:'Enter caption'}]};}
   if(a==='node-run-start'){formStarts++;return {canvas_run:'owning-canvas'};}
   return reviewRequest(a,v);
 }});await flush();await cls(root,'canvas-node-run')[0].onclick();
 assert.match(cls(root,'workflow-node')[0].textContent,/Enter caption/);
 let caption=field(cls(root,'workflow-node')[0],'Caption');caption.value='Saved value';caption.onchange();
 await btn(cls(root,'workflow-node')[0],'Continue').onclick();assert.equal(provided.caption,'Saved value');
 const oldConsent=btn(root,'Run · paid');caption.value='Changed value';caption.onchange();
 await oldConsent.onclick();assert.equal(formStarts,0,'changing run inputs invalidates old paid consent');
 await btn(cls(root,'workflow-node')[0],'Continue').onclick();await btn(root,'Run · paid').onclick();assert.equal(formStarts,1);dispose();
 // Execution updates the mounted editor, preserving panels and selection.
 let tracked=0,resultRenders=0;
 const liveView={name:'owning-canvas',canvas_run:true,status:'completed',canvas_document:{...canvasRecord},executing_runs:[],tasks:canvasRecord.workflow.tasks.map(t=>({id:t.id,status:'completed'})),latest_outputs:[{id:'saved-image',task:'red',path:'cup.png',sha256:'exact-image'}]};
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:canvasRecord,selection:'red',onRun:()=>{throw Error('Run must not navigate');},
   renderResults:(task,panel)=>{resultRenders++;panel.append(node('p','Saved cup output'));},
   trackRun:async(run,paint)=>{tracked++;assert.equal(run,'owning-canvas');paint({...liveView,status:'active',executing_runs:['execution'],tasks:liveView.tasks.map(t=>({...t,status:'running'}))});assert.equal(cls(root,'workflow-node')[0].attributes['aria-busy'],'true');return liveView;},
   request:async(a,v)=>{if(a==='node-run-preview')return {...paidPreview,paid_nodes:[]};if(a==='node-run-start')return {canvas_run:'owning-canvas'};return reviewRequest(a,v);}
 });await flush();
 btn(root,'Chat').onclick();const chatPanel=cls(root,'job-chat-panel')[0];assert.equal(chatPanel.hidden,false);
 walk(chatPanel).find(e=>e.attributes['aria-label']==='Expand Chat to full width').onclick();assert(chatPanel.classList.contains('panel-expanded'));
 walk(chatPanel).find(e=>e.attributes['aria-label']==='Restore Chat width').onclick();assert(!chatPanel.classList.contains('panel-expanded'));
 await cls(root,'canvas-node-run')[0].onclick();await flush();
 assert.equal(tracked,1);assert.equal(cls(root,'job-chat-panel')[0],chatPanel);assert.equal(chatPanel.hidden,false);
 assert.equal(cls(root,'workflow-inspector')[0].hidden,false);assert.equal(cls(root,'workflow-step')[0].attributes['aria-pressed'],'true');
 assert(btn(root,'Run'));assert.equal(btn(root,'Run workflow'),undefined);assert.equal(btn(root,'History'),undefined);
 assert(resultRenders>0);assert.equal(btn(root,'Results').attributes['aria-pressed'],'true','completion opens Results');assert(root.textContent.includes('Saved cup output'));dispose();
 // Reopening a finished workflow selects its final output without a click.
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{...canvasRecord,display:liveView},renderResults:(task,panel)=>panel.append(node('p','Finished output'))});await flush();
 assert.equal(cls(root,'workflow-inspector')[0].hidden,false);assert.equal(btn(root,'Results').attributes['aria-pressed'],'true');
 const widthControl=walk(root).find(e=>e.attributes['aria-label']==='Expand Results to full width');widthControl.onclick();
 assert(cls(root,'workflow-inspector')[0].classList.contains('panel-expanded'));
 btn(root,'Inputs').onclick();assert.equal(btn(root,'Inputs').attributes['aria-pressed'],'true');dispose();
 // Canvas Chat inherits the existing conversation default, never a past turn model.
 sharedText={selected:{provider:'gemini',model:'shared-gemini'},selected_available:true};
 let sharedCommand,sharedStarts=0,openedModelSettings=0;
 dispose=window.RelayNodeEditor.mount(root,{...opts,newJob:true,modelSettings:()=>openedModelSettings++,request:async(a,v)=>{
   if(a==='node-compose-preview'){sharedCommand=JSON.parse(JSON.stringify(v));return {command:{id:'shared',request_id:v.request_id},fingerprint:'shared',blockers:[],paid_nodes:['compose']};}
   if(a==='node-run-start'){sharedStarts++;throw Error('No paid call allowed');}
   return opts.request(a,v);
 }});await flush();
 assert(!btn(root,'Send').disabled);assert.match(root.textContent,/gemini · shared-gemini · Shared/);
 const chip=walk(root).find(e=>e.attributes['aria-label']==='Conversation model settings · shared with Telegram and Messages');chip.onclick();assert.equal(openedModelSettings,1);
 window.RelayNodeEditor.updateChatDefaults({capabilities:[{capability:'text',selected:{provider:'gemini',model:'unavailable'},selected_available:false}]});assert(btn(root,'Send').disabled,'unavailable shared choice never falls back');
 sharedText={selected:{provider:'gemini',model:'fresh-shared'},selected_available:true};
 window.RelayNodeEditor.updateChatDefaults({capabilities:[{capability:'text',...sharedText}]});
 field(root,'Describe your workflow').value='Use shared settings';await btn(root,'Send').onclick();await flush();
 assert.equal(sharedCommand.model.id,'fresh-shared');assert.equal(sharedStarts,0,'shared paid default still needs approval');
 window.RelayNodeEditor.updateChatDefaults({capabilities:[{capability:'text',selected:{provider:'gemini',model:'newer'},selected_available:true}]});
 assert.equal(sharedCommand.model.id,'fresh-shared');assert.match(root.textContent,/gemini · fresh-shared/,'pending request retains frozen model');
 await btn(root,'Cancel').onclick();
 const override=field(root,'Chat provider');override.value='codex';override.onchange();await flush();
 field(root,'Chat model').value='gpt-6-sol';field(root,'Chat model').onchange();assert.match(root.textContent,/Codex · gpt-6-sol · This chat/);
 window.RelayNodeEditor.updateChatDefaults({capabilities:[{capability:'text',...sharedText}]});assert.match(root.textContent,/Codex · gpt-6-sol · This chat/);
 dispose();dispose=window.RelayNodeEditor.mount(root,opts);await flush();assert.match(root.textContent,/Codex · gpt-6-sol · This chat/,'explicit chat override survives reopening');
 await btn(root,'Use shared model').onclick();assert.match(root.textContent,/gemini · fresh-shared · Shared/);dispose();
 // Historical model labels are evidence, not implicit preferences for the next request.
 const sharedHistoryKey='relay:workflow-composition:shared-history';storage.set(sharedHistoryKey+':history',JSON.stringify([{id:'old',question:'Before',message:'Saved reply',model:{provider:'codex',id:'gpt-6-sol'}}]));
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{id:'shared-history',workflow:quickWorkflow}});await flush();assert.match(root.textContent,/gemini · fresh-shared · Shared/);dispose();sharedText=null;
 // A new canvas can request a proposal, but it cannot run proposed nodes implicitly.
 const composeCalls=[];let composeCommand,chatSaved;
 dispose=window.RelayNodeEditor.mount(root,{...opts,onSaved:r=>{chatSaved=r;},request:async(a,v)=>{
   composeCalls.push(a);
   if(a==='node-compose-preview'){composeCommand=v;return {command:{id:'proposal',request_id:v.request_id},fingerprint:'exact',blockers:[],paid_nodes:v.model.provider==='gemini'?['compose']:[]};}
   if(a==='node-run-start')return {run:'composition-run'};
   if(a==='node-compose-result')return {status:'completed',run:'composition-run',workflow:quickWorkflow};
   if(a==='node-run-advance')throw Error('No workflow execution during proposal/apply');
   return opts.request(a,v);
 }});await flush();
 assert.equal(cls(root,'job-chat-panel')[0].hidden,false);
 assert(btn(root,'Send').disabled,'chat requires an explicit model choice');
 let chatProvider=field(root,'Chat provider');chatProvider.value='gemini';chatProvider.onchange();await flush();
 let chatModel=field(root,'Chat model');chatModel.value='fixture';chatModel.onchange();
 field(root,'Describe your workflow').value='Read the article and summarise it';
 await btn(root,'Send').onclick();await flush();
 assert.equal(composeCommand.model.provider,'gemini');assert.equal(composeCommand.model.id,'fixture');
 assert(!composeCalls.includes('node-run-start'),'no API start before consent');
 assert(btn(root,'Send · paid'));await btn(root,'Cancel').onclick();
 chatProvider=field(root,'Chat provider');chatProvider.value='codex';chatProvider.onchange();await flush();
 chatModel=field(root,'Chat model');chatModel.value='gpt-6-sol';chatModel.onchange();
 field(root,'Describe your workflow').value='Read the article and summarise it';
 await btn(root,'Send').onclick();await flush();
 assert.equal(composeCommand.question,'Read the article and summarise it');
 assert.equal(cls(root,'workflow-node').length,2,'validated proposal appears directly on the unchanged canvas');
 assert.equal(btn(root,'Apply to canvas'),undefined);assert.match(root.textContent,/Added to canvas/);
 assert.equal(cls(root,'workflow-node').length,2);assert.equal(cls(root,'canvas-node-run').length,2);
 assert.equal(composeCalls.filter(a=>a==='node-run-start').length,1,'only the proposal node starts');assert.equal(composeCommand.model.id,'gpt-6-sol');assert(!storage.has('relay:workflow-composition'));
 await btn(root,'Save').onclick();await flush();assert.equal(cls(root,'canvas-node-run').length,2,'Save keeps node Run controls');dispose();
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:chatSaved});await flush();
 assert(cls(root,'workflow-chat-transcript')[0].textContent.includes('Read the article and summarise it'),'Save and reopen retain this job conversation');dispose();
 // Committed partial graphs appear while Chat is active; reopen reads without resubmission.
 let progressiveStage=1,progressiveStarts=0,progressiveCommand;
 const firstGraph=JSON.parse(JSON.stringify(quickWorkflow));firstGraph.tasks=firstGraph.tasks.slice(0,1);
 const progressiveRequest=async(a,v)=>{
   if(a==='node-compose-preview'){progressiveCommand=JSON.parse(JSON.stringify(v));return {command:{id:'progressive',request_id:v.request_id},fingerprint:'progressive',blockers:[],paid_nodes:[]};}
   if(a==='node-run-start'){progressiveStarts++;return {run:'progressive'};}
   if(a==='node-run-advance')return {};
   if(a==='node-compose-result')return {status:progressiveStage===3?'completed':'active',run:'progressive',workflow:progressiveStage===1?firstGraph:quickWorkflow,message:'Nodes ready',...(progressiveStage===3?{}:{preview:{attempt:'compose-1',revision:progressiveStage,sha256:'rev-'+progressiveStage}})};
   return opts.request(a,v);
 };
 dispose=window.RelayNodeEditor.mount(root,{...opts,newJob:true,request:progressiveRequest});await flush();
 chatProvider=field(root,'Chat provider');chatProvider.value='codex';chatProvider.onchange();await flush();
 chatModel=field(root,'Chat model');chatModel.value='gpt-6.1-sol';chatModel.onchange();
 field(root,'Describe your workflow').value='Build progressively';await btn(root,'Send').onclick();await flush();
 assert.equal(cls(root,'workflow-node').length,1);assert.match(root.textContent,/Building workflow/);
 assert.equal(progressiveCommand.workflow.tasks.length,0,'submitted graph remains the original empty graph');dispose();
 progressiveStage=2;dispose=window.RelayNodeEditor.mount(root,{...opts,request:progressiveRequest});await flush();
 assert.equal(cls(root,'workflow-node').length,2);assert.equal(progressiveStarts,1,'reopen only observes the saved composition');dispose();
 progressiveStage=3;dispose=window.RelayNodeEditor.mount(root,{...opts,request:progressiveRequest});await flush();
 assert.equal(cls(root,'workflow-node').length,2);assert.match(root.textContent,/Added to canvas/);assert.equal(progressiveStarts,1);dispose();
 // A late proposal must never overwrite a graph edited while the reply was pending.
 let replyLater;
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{id:'changed-during-chat',revision:'1',workflow:quickWorkflow},request:async(a,v)=>{
   if(a==='node-compose-preview')return {command:{id:'late',request_id:v.request_id},fingerprint:'late',blockers:[],paid_nodes:[]};
   if(a==='node-run-start')return {run:'late'};
   if(a==='node-compose-result')return new Promise(resolve=>{replyLater=resolve;});
   return opts.request(a,v);
 }});await flush();
 chatProvider=field(root,'Chat provider');chatProvider.value='codex';chatProvider.onchange();await flush();
 chatModel=field(root,'Chat model');chatModel.value='gpt-6.1-sol';chatModel.onchange();
 field(root,'Describe your workflow').value='Update this';const pendingReply=btn(root,'Send').onclick();await flush();
 cls(root,'workflow-step')[1].onclick();await flush();field(root,'Prompt').value='Keep my newer edit';field(root,'Prompt').onchange();await flush();
 replyLater({status:'completed',workflow:quickWorkflow,message:'Proposed update'});await pendingReply;
 assert.equal(field(root,'Prompt').value,'Keep my newer edit');assert.match(root.textContent,/kept your edits/);dispose();
 // Paid confirmation and reload retain the exact selected provider/submission after an uncertain response.
 let paidCommands=[],previewCount=0;
 const chatRequest=async(a,v)=>{
   if(a==='node-compose-preview'){previewCount++;return {command:{id:'gemini-proposal',request_id:v.request_id},fingerprint:'gemini-exact',blockers:[],paid_nodes:['compose']};}
   if(a==='node-run-start'){paidCommands.push(JSON.parse(JSON.stringify(v)));if(paidCommands.length===1)throw Error('Lost response');return {run:'saved-proposal'};}
   if(a==='node-compose-result')return {status:'completed',run:'saved-proposal',workflow:quickWorkflow};
   return opts.request(a,v);
 };
 dispose=window.RelayNodeEditor.mount(root,{...opts,request:chatRequest});await flush();
 chatProvider=field(root,'Chat provider');chatProvider.value='gemini';chatProvider.onchange();await flush();
 chatModel=field(root,'Chat model');chatModel.value='fixture';chatModel.onchange();
 field(root,'Describe your workflow').value='Make a graph';await btn(root,'Send').onclick();
 assert.equal(paidCommands.length,0);await btn(root,'Send · paid').onclick();assert.equal(paidCommands.length,1);dispose();
 dispose=window.RelayNodeEditor.mount(root,{...opts,request:chatRequest});await flush();
 assert.equal(field(root,'Chat provider').value,'gemini');
 await flush();assert.equal(previewCount,1);assert.equal(paidCommands.length,1,'reload observes the saved outcome without resubmitting');assert.equal(paidCommands[0].allow_paid,true);
 assert(cls(root,'workflow-chat-transcript')[0].textContent.includes('Make a graph'));assert(!field(root,'Chat provider').disabled);assert(!storage.has('relay:workflow-composition'));dispose();
 // New job gets an isolated scope, including when an older request is uncertain.
 const previousScope=storage.get('relay:workflow-composition:current-unsaved');
 const previousHistory=storage.get(previousScope+':history');
 storage.set(previousScope,JSON.stringify({request_id:'uncertain-old',question:'Old pending request',model:{provider:'gemini',id:'fixture'}}));
 const oldPending=storage.get(previousScope);let unexpectedReads=0;
 const isolatedRequest=async(a,v)=>{if(a==='node-compose-result' || a==='node-run-start'){unexpectedReads++;throw Error('New job must not observe or submit another job request');}return opts.request(a,v);};
 dispose=window.RelayNodeEditor.mount(root,{...opts,newJob:true,request:isolatedRequest});await flush();
 assert.match(cls(root,'workflow-chat-transcript')[0].textContent,/What would you like to do/);
 assert(!root.textContent.includes('Make a graph'));assert(!root.textContent.includes('Old pending request'));
 assert.equal(unexpectedReads,0);assert.equal(storage.get(previousScope),oldPending);assert.equal(storage.get(previousScope+':history'),previousHistory);
 const freshScope=storage.get('relay:workflow-composition:current-unsaved');assert.notEqual(freshScope,previousScope);dispose();
 dispose=window.RelayNodeEditor.mount(root,{...opts,request:isolatedRequest});await flush();
 assert.equal(storage.get('relay:workflow-composition:current-unsaved'),freshScope,'reload keeps the current unsaved scope');
 assert.match(cls(root,'workflow-chat-transcript')[0].textContent,/What would you like to do/);dispose();
 storage.set('relay:workflow-composition:saved-chat:history',JSON.stringify([{id:'saved-message',question:'Saved job question',message:'Saved job answer',model:{provider:'codex',id:'gpt-6-sol'}}]));
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{id:'saved-chat',workflow:quickWorkflow},request:isolatedRequest});await flush();
 assert(root.textContent.includes('Saved job question'));assert(root.textContent.includes('Saved job answer'));
 assert(!root.textContent.includes('Make a graph'));assert.equal(unexpectedReads,0);dispose();
 // A legacy global transcript must not return after a fresh scope was saved/cleared.
 storage.set('relay:workflow-composition:history',previousHistory);
 storage.delete('relay:workflow-composition:current-unsaved');
 dispose=window.RelayNodeEditor.mount(root,{...opts,request:isolatedRequest});await flush();
 assert.match(cls(root,'workflow-chat-transcript')[0].textContent,/What would you like to do/);
 assert(!root.textContent.includes('Make a graph'));assert.equal(unexpectedReads,0);dispose();

 // Workflow-bound Gemini prompts stay editable without dispatching uncertain work.
 const promptGraph={schema_version:1,kind:'workflow',inputs:{image_prompt:{type:'string',label:'Prompt',required:true}},tasks:[{schema_version:3,id:'image',objective:'Gemini image',operation:'gemini.image',inputs:{prompt:{workflow:'image_prompt'},model:{value:'gemini-3.1-flash-image'}}}]};
 const promptRecord={id:'prompt-fixture',workflow:promptGraph,values:{image_prompt:'Original saved image prompt'},display:{tasks:[{id:'image',status:'uncertain',error:'Gemini request failed (connection-or-response)'}]}},promptBefore=JSON.stringify(promptRecord),callsBefore=submissions.length;
 let editedPrompt;
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:promptRecord,selection:'image',request:async(a,v)=>{if(a==='node-validate')editedPrompt=JSON.parse(JSON.stringify(v.workflow));return opts.request(a,v);}});await flush();
 assert.equal(field(root,'Prompt').value,'Original saved image prompt');
 assert.match(root.textContent,/Editing does not retry/);
 assert.match(root.textContent,/Gemini request failed/);
 assert(cls(root,'canvas-node-run')[0].disabled);
 field(root,'Prompt').value='Updated image prompt';field(root,'Prompt').onchange();await flush();
 assert.equal(field(root,'Prompt').value,'Updated image prompt');
 assert.equal(editedPrompt.tasks[0].inputs.prompt.value,'Updated image prompt');
 assert(!editedPrompt.inputs.image_prompt,'orphan workflow input no longer asks again');
 assert.equal(JSON.stringify(promptRecord),promptBefore,'original execution inputs are not edited');
 assert.equal(submissions.length,callsBefore,'editing never sends an API request');
 dispose();

 // Explicit new attempt: warning and paid confirmation stay on the same node.
 const unknowns=[{attempt:'old-attempt',run:'old-run',task:'image',sha256:'exact-old-receipt'}],newCommands=[];
 let newRecord={canvas:'uncertain-canvas',revision:'u1',title:'Image',workflow:JSON.parse(JSON.stringify(promptGraph)),values:{image_prompt:'Original saved image prompt'},display:{tasks:[{id:'image',status:'uncertain',can_start_new_attempt:true,error:'Connection failed',versions:[{status:'uncertain',prompt:'Original saved image prompt',files:[]}]}]}};
 let newOpened;
 const newRequest=async(a,v={})=>{
   if(a==='node-canvas-save'){newRecord={...newRecord,...v,canvas:v.run,revision:'u2',missing_inputs:[]};return newRecord;}
   if(a==='node-run-preview')return {...backend(a,v),uncertain_attempts:unknowns};
   if(a==='node-run-start'){newCommands.push(JSON.parse(JSON.stringify(v)));if(newCommands.length===1)throw Error('Response lost');return {run:'new-version',canvas_run:'uncertain-canvas'};}
   return opts.request(a,v);
 };
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:newRecord,selection:'image',request:newRequest,onRun:r=>{newOpened=r;}});await flush();
 assert(!cls(root,'canvas-node-run')[0].disabled);
 field(root,'Prompt').value='New blue image';field(root,'Prompt').onchange();await flush();
 await cls(root,'canvas-node-run')[0].onclick();await flush();
 assert.match(root.textContent,/previous request may have completed or incurred a charge/);
 assert.equal(newCommands.length,0,'Run only previews before confirmation');
 assert(btn(cls(root,'workflow-node')[0],'Confirm new paid attempt'));
 await btn(root,'Cancel').onclick();assert.equal(newCommands.length,0);
 await cls(root,'canvas-node-run')[0].onclick();await flush();
 await btn(root,'Confirm new paid attempt').onclick();assert.equal(newCommands.length,1);
 assert.deepEqual(newCommands[0].acknowledge_uncertain,unknowns);
 assert.equal(newCommands[0].allow_paid,true);assert.equal(newCommands[0].scope,'image');
 assert.equal(newRecord.workflow.tasks[0].inputs.prompt.value,'New blue image');
 await btn(root,'Check same submission').onclick();assert.deepEqual(newCommands[0],newCommands[1]);
 assert.equal(newOpened,'uncertain-canvas');dispose();

 // Browser node uses the existing account controls, with no model key or search.
 let browserState={available:true,enabled:false,manual_sign_in:false,error:null},browserActions=[];
 const browserRequest=async(a,v)=>{
   if(a==='node-setup')return {...backend(a,v),operations:{'perplexity.search':{worker:false,connection:'managed_browser'}},browser:{...browserState}};
   if(a.startsWith('browser-')){browserActions.push([a,v]);if(a==='browser-configure')browserState={...browserState,enabled:true,manual_sign_in:true};if(a==='browser-sign-in-done')browserState.manual_sign_in=false;return {message:'Fixture setup changed'};}
   return opts.request(a,v);
 };
 const browserGraph={schema_version:1,kind:'workflow',inputs:{},tasks:[{schema_version:3,id:'research',objective:'Research with Perplexity',operation:'perplexity.search',inputs:{query:{value:'Plants along the western Colorado River'}}}]};
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:{workflow:browserGraph},request:browserRequest,selection:'research'});await flush();
 assert(field(root,'Research question'));assert(root.textContent.includes('Answer'));assert(root.textContent.includes('Sources'));
 assert(!field(root,'API key'));assert(!field(root,'Provider'));assert.equal(browserActions.length,0);
 await btn(root,'Enable browser & sign in').onclick();await flush();
 assert.equal(browserActions[0][0],'browser-configure');assert.equal(browserActions[0][1].enabled,true);
 await btn(root,'Done signing in').onclick();await flush();
 assert.match(root.textContent,/Sign-in is checked when this node runs/);
 assert(btn(root,'Open browser / sign in'));assert.equal(browserActions.length,2);
 assert(root.textContent.includes('not Research mode'));dispose();
 // Canvas history restores whole validated edits, never execution or saved attempts.
 let undoSaved=null,rejectUndoEdit=false,historyCalls=[];
 const undoRequest=async(a,v)=>{
   historyCalls.push(a);
   if(a==='node-validate' && rejectUndoEdit)throw Error('Rejected test edit');
   if(a==='node-draft-save'){undoSaved=JSON.parse(JSON.stringify({...v,revision:'undo-fixture',missing_inputs:[]}));return undoSaved;}
   return opts.request(a,v);
 };
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:stored,selection:'model',request:undoRequest});await flush();
 assert(btn(root,'Undo').disabled);assert(btn(root,'Redo').disabled);
 const key=async(target,shift=false,ctrl=false)=>{let prevented=false;window.onkeydown({target,key:'z',metaKey:!ctrl,ctrlKey:ctrl,shiftKey:shift,preventDefault(){prevented=true;},stopPropagation(){}});await flush();return prevented;};
 const originalPrompt=field(root,'Prompt').value;
 field(root,'Prompt').value='Changed summary prompt';field(root,'Prompt').onchange();await flush();
 assert(!btn(root,'Undo').disabled);
 assert.equal(await key(field(root,'Prompt')),false,'focused text keeps native undo');
 assert.equal(field(root,'Prompt').value,'Changed summary prompt');
 assert.equal(await key(root),true);assert.equal(field(root,'Prompt').value,originalPrompt);
 assert.equal(await key(root,true),true);assert.equal(field(root,'Prompt').value,'Changed summary prompt');
 await btn(root,'Save').onclick();await flush();
 assert(!btn(root,'Undo').disabled,'Save retains session history');
 await window.RelayNodeEditor.history('undo');await flush();assert.equal(field(root,'Prompt').value,originalPrompt);
 assert(root.textContent.includes('Unsaved'));
 await btn(root,'Redo').onclick();await flush();assert.equal(field(root,'Prompt').value,'Changed summary prompt');
 const removeWire=walk(root).find(e=>e.tagName==='button' && e.textContent.startsWith('Remove Read a web page'));
 assert(removeWire);await removeWire.onclick();await flush();assert.equal(cls(root,'workflow-lines')[0].children.length,0);
 await key(root,false,true);assert.equal(cls(root,'workflow-lines')[0].children.length,1,'Ctrl+Z restores wire');
 await btn(root,'Remove step').onclick();await flush();assert.equal(cls(root,'workflow-node').length,1);
 await key(root);assert.equal(cls(root,'workflow-node').length,2);assert.equal(cls(root,'workflow-lines')[0].children.length,1,'restored deleted node includes its exact input connection');
 await key(root,true);assert.equal(cls(root,'workflow-node').length,1);
 await key(root);assert.equal(cls(root,'workflow-node').length,2);
 rejectUndoEdit=true;field(root,'Prompt').value='Rejected';field(root,'Prompt').onchange();await flush();rejectUndoEdit=false;
 assert.equal(field(root,'Prompt').value,'Changed summary prompt');assert(!btn(root,'Redo').disabled,'failed edit preserves redo');
 field(root,'Prompt').value='New branch';field(root,'Prompt').onchange();await flush();assert(btn(root,'Redo').disabled,'new edit clears redo branch');
 const oldHandler=window.onkeydown;dispose();assert.notEqual(window.onkeydown,oldHandler,'disposed job loses shortcut handler');
 dispose=window.RelayNodeEditor.mount(root,{...opts,record:stored,request:undoRequest});await flush();
 assert(btn(root,'Undo').disabled);assert(btn(root,'Redo').disabled,'history never crosses jobs or reopening');dispose();
 assert(!historyCalls.some(a=>/node-run|node-compose|node-connect/.test(a)),'history only validates/saves; never executes or restores credentials');
 console.log('Node editor passed: composition/save/reload; New job chat isolation; saved history and uncertain request preservation; inline Run and paid consent. Fixture executions only.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>fs.rmSync(tmp,{recursive:true,force:true}));
