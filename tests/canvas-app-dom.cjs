// Composed UI navigation over small saved records. No runtime or provider execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let fixtureScrollHeight=2000;const replacementTexts=[];
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.dataset={};this.style={};this.hidden=false;this.value='';this._text='';this.clientWidth=1000;this.clientHeight=700;this.scrollHeight=fixtureScrollHeight;this.scrollTop=0;this.offsetHeight=27;this.offsetTop=80;this.isConnected=true;const c=new Set();this.classList={add:(...v)=>v.forEach(x=>c.add(x)),remove:(...v)=>v.forEach(x=>c.delete(x)),contains:x=>c.has(x),toggle(x,on){on?c.add(x):c.delete(x);}};}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join(' ');}
 set textContent(v){this._text=String(v);this.children=[];}
 append(...nodes){for(const n of nodes){n.remove();n.parent=this;this.children.push(n);}}
 insertBefore(n,b){n.remove();n.parent=this;this.children.splice(this.children.indexOf(b),0,n);}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
 replaceChildren(...nodes){replacementTexts.push(nodes.map(n=>n.textContent).join(' '));this.children.forEach(n=>n.parent=null);this.children=[];this._text='';this.append(...nodes);}
 setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}addEventListener(k,v){this['on'+k]=v;}
 querySelector(selector){const names=selector.split(',');return walk(this).slice(1).find(e=>names.includes(e.tagName) || names.some(s=>s.startsWith('.')&&(e.className || '').split(' ').includes(s.slice(1)))) || null;}
 getBoundingClientRect(){return {left:0,top:0,width:1000,height:700};}
 setPointerCapture(id){this.capture=id;}hasPointerCapture(id){return this.capture===id;}releasePointerCapture(){this.capture=null;}
 focus(){}scrollIntoView(){}
 showModal(){this.open=true;}close(){this.open=false;}
}
const walk=e=>[e,...e.children.flatMap(walk)],ids=new Map(),el=id=>{if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);};
const document={body:new Element('body'),hidden:false,getElementById:el,querySelectorAll:()=>[],createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)};
let savedLinkFailure=true;const calls=[],frames=[],timers=[],storage=new Map();let deleteApproval=false;let deleteWarning="";let editorOptions,advanceHeld=null;let paidPreview=true;let held=null,previewHash='pixel-hash',edited=null,chatLost=true;let draftItems=[];let savedMessage=null;
const items=[{id:'parent',kind:'pipeline',title:'Saved room workflow',status:'blocked',channel:'desktop'}, {id:'proposal',kind:'plan',title:'Saved proposal',status:'ready',channel:'desktop'}, {id:'chat',kind:'chat',title:'Saved conversation',status:'answered',channel:'desktop'}];
const stages=[{id:'source',status:'completed',run:'source-run',tasks:[{id:'fetch',status:'completed'}]}, {id:'export',status:'uncertain',run:'export-run',tasks:[{id:'render',status:'uncertain'}]}, {id:'deliver',status:'pending',tasks:[]}];
const pipeline={id:'parent',title:'Saved room workflow',status:'blocked',channel:'desktop',request:'Keep everything',stages,stats:{stages:3,stages_completed:1,tasks:2,tasks_completed:1,workers_created:2,reviewers_created:0,operations_started:1,running:0,uncertain:1,runs:3},usage:{},outputs:[{id:'file',path:'exact.pptx',sha256:'abc',stage:'export'}],attempts:[{id:'old',task:'render',state:'blocked',run:'old-run',current:false}],runs:[],plans:[]};
const run={name:'export-run',brief:'Export room',status:'uncertain',channel:'desktop',tasks:[{id:'render',objective:'Render deck',status:'uncertain',latest_attempt:'exact',planned_outputs:[{path:'exact.pptx'}]}],latest_outputs:[],controls:[],messages:[]};
const proposal={id:'proposal',request:'Read and summarise',status:'blocked',channel:'desktop',plan:{tasks:[{id:'read',objective:'Read',inputs:[],outputs:[{path:'article.md'}]},{id:'summary',objective:'Summarise',dependencies:[{task:'read'}],inputs:[{path:'article.md',from_task:'read',output:'article.md'}],outputs:[{path:'summary.md'}]}]}};
const chat={id:'chat',prompt:'Read source',answer:'Saved answer',channel:'desktop',flow:{name:'conversation:chat',tasks:[{id:'conversation:chat',objective:'Saved answer',status:'completed',dependencies:[]}],stages:[{request_id:'root',mode:'research',status:'completed',conversation:{id:'root',answer:'Saved research',prompt:'Read source'}}]}};
stages[0].execution={name:'source-run',tasks:[{id:'fetch',objective:'Fetch source',status:'completed',planned_outputs:[{path:'page.md'}]}],latest_outputs:[{id:'page',task:'fetch',path:'page.md',sha256:'source-hash'}]};
stages[1].execution={...run,tasks:[{...run.tasks[0],planned_inputs:[{path:'source.md'}],recorded_inputs:[{path:'source.md',artifact:'page',sha256:'source-hash'}]}]};
const before=JSON.stringify({pipeline,run,proposal});
const window={scrollTo(){},__TAURI__:{core:{invoke:async(_,r)=>{calls.push(_==='workspace_open_artifact_link'?{path:_,value:r}:r);
 if(_==='workspace_open_artifact_link'){assert.deepEqual(JSON.parse(JSON.stringify(r)),{artifact:'page',sha256:'source-hash',url:'https://www.perplexity.ai/search/saved-thread'});if(savedLinkFailure)throw Error('Controlled browser opening failure');return;}
 if(r.path==='workflow-export'){assert.equal(r.value.include_files,false);assert.deepEqual(JSON.parse(JSON.stringify(r.value.source)),{kind:'canvas',id:'work-image',revision:'graph-version'});return {path:r.value.path,nodes:2};}
 if(r.path==='workflow-import-preview')return {title:'Imported photos',nodes:2,files:[],missing_files:[],sha256:'package-hash'};
 if(r.path==='workflow-import'){assert.equal(r.value.sha256,'package-hash');return {id:'imported-draft',title:'Imported photos',workflow:{schema_version:1,kind:'workflow',inputs:{},tasks:[]},revision:'new',missing_inputs:[]};}
 if(r.path==='workspace-job-delete-preview' && r.value.id==='stopped')return {id:'canvas:stopped',title:'Stopped image',kind:'canvas',runs:['stopped'],files:1,delete_action:'job-delete',digest:'stopped-digest',blockers:[],stopped_uncertain_attempts:['old']};
 if(r.path==='job-delete'){assert.equal(r.value.acknowledge_uncertain,true);assert.equal(r.value.digest,'stopped-digest');items.splice(items.findIndex(i=>i.id==='stopped'),1);return {status:'complete'};}
 if(r.path==='workspace-job-delete-preview')return {id:r.value.id,title:'Saved conversation',kind:'chat',delete_action:'conversation-delete',digest:'exact-digest',blockers:r.value.id==='parent'?['This job is not finished.']:[]};
 if(r.path==='conversation-delete'){assert.equal(r.value.digest,'exact-digest');items.splice(items.findIndex(i=>i.id===r.value.id),1);return {status:'complete'};}
 if(r.path==='workspace-job-visibility'){if(r.value.id==='parent')throw Error('This job is not finished.');items.find(i=>i.id===r.value.id).archived=r.value.deleted;return {deleted:r.value.deleted};}
 if(r.path==='workspace-jobs')return {items:items.filter(i=>r.value.include_archived || !i.archived),total:items.length,next_offset:null,can_plan:false,scope:'fixture'};
 if(r.path==='workspace-detail'){if(held)return new Promise(resolve=>held.push(resolve));return r.value.pipeline?pipeline:run;}
 if(r.path==='workspace-plan')return proposal;
 if(r.path==='workspace-chat')return chat;
 if(r.path==='conversation-followup'){
  if(r.value.check){
   if(savedMessage){chat.can_message=false;chat.flow={tasks:[],status:'queued',stages:[{request_id:savedMessage.request_id,mode:'message',prompt:savedMessage.message,status:'queued'}]};}
   return {root_id:chat.id,request_id:r.value.request_id,status:savedMessage?'accepted':'not_saved'};
  }
  assert.equal(r.value.id,chat.id);assert.equal(r.value.message,'Please continue with repairability');
  savedMessage=r.value;throw Error('Controlled lost Send response');
 }
 if(r.path==='workspace-artifact' && r.value.location)return {path:'/saved/jobs/Volvo/delivery/gallery.html',folder:'/saved/jobs/Volvo'};
 if(r.path==='workspace-artifact' && r.value.preview){if(r.value.artifact==='page')return {sha256:'source-hash',media_type:'text/markdown',text:'# Saved research'};if(r.value.artifact==='markdown-file')return {sha256:'md-hash',media_type:'text/markdown',text:'# Report\n\n**Clear result**\n\n| Item | Value |\n|---|---|\n| Cup | Blue |'};if(r.value.artifact==='pdf-file')return {sha256:'pdf-hash',media_type:'application/pdf',data_url:'data:image/jpeg;base64,aW1hZ2U=',page:r.value.page,pages:2};if(r.value.artifact==='gallery-file')return {sha256:'gallery-hash',media_type:'text/html',html:'<h1>Saved Volvo gallery</h1>',transformation:'Local preview; original unchanged'};return {sha256:previewHash,data_url:'data:image/png;base64,aW1hZ2U='};}
 if(r.path==='workspace-open-artifact')return {status:'open_requested'};
 if(r.path==='node-catalog')return {operations:[{id:'gemini.image',title:'Gemini image',inputs:{files:{kind:'artifacts',accepts:['image/png']}}}]};
 if(r.path==='node-result-draft')return {id:'new-draft',title:'Edit image',origin:r.value,workflow:{tasks:[]}};
 if(r.path==='node-drafts')return {items:draftItems};
 if(r.path==='node-templates')return {items:[{id:'cellular-aggregation',title:'Cellular aggregation · from Chat',description:'Research, build, animate and present.',requirements:'Configure connections; Run reviews paid and native execution.'}]};
 if(r.path==='node-template'){assert.equal(r.value.id,'cellular-aggregation');return {title:'Cellular aggregation · from Chat',workflow:JSON.parse(fs.readFileSync('task_relay/assets/job-templates/cellular-aggregation.workflow.json','utf8')),execution_authorized:false};}
 if(r.path==='node-draft-save'){assert.equal(r.value.id,null);assert.equal(r.value.revision,null);assert.equal(r.value.workflow.tasks.length,11);return {id:'template-copy',...r.value,id:'template-copy',revision:'new-template',missing_inputs:[]};}

 if(r.path==='node-result-chat'){if(chatLost){chatLost=false;throw Error('Lost response');}return {run:'answer-run'};}
 if(r.path==='node-run-advance')return advanceHeld?new Promise(resolve=>advanceHeld.push(resolve)):{};
 if(r.path==='node-prompt-save')return {...r.value,revision:'saved-prompt'};
 if(r.path==='node-canvas-save'){run.canvas_document={...run.canvas_document,...r.value,revision:'graph-2'};return run.canvas_document;}
 if(r.path==='node-run-preview')return {plan:{tasks:[{id:'render'}]},paid_nodes:paidPreview?['render']:[],blockers:[],fingerprint:'exact'};
 if(r.path==='node-run-start')throw Error('Fixture bridge lost response');
 throw Error('Unexpected operation '+r.path);
}}},RelaySavedWork:{confirm:async(text)=>{deleteWarning=text;return deleteApproval;},open(){throw Error('No management mutation expected');}}};
const observers=new Set();let imagesVisible=true;
const markdown=require('../task_relay/assets/vendor/marked.umd.js');
const ctx=vm.createContext({window,document,presentationMarkdown:text=>text,renderMarkdown(target,text,options){target.classList.add('rich-text');target.textContent=text;target.renderedHTML=markdown.parse(text);target.renderOptions=options;},crypto:require('node:crypto').webcrypto,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setInterval(f){timers.push(f);},console,ResizeObserver:class{observe(){}disconnect(){}},
 IntersectionObserver:class{constructor(fn){this.fn=fn;}observe(){observers.add(this);}disconnect(){observers.delete(this);}},requestAnimationFrame:f=>frames.push(f)});
for(const file of ['companion-workflow.js','companion-workspace.js'])vm.runInContext(fs.readFileSync('task_relay/assets/'+file,'utf8'),ctx);
const flush=async()=>{await new Promise(r=>setImmediate(r));frames.splice(0).forEach(f=>f());if(imagesVisible)for(const o of [...observers])o.fn([{isIntersecting:true}]);await new Promise(r=>setImmediate(r));};
const cls=(e,name)=>walk(e).filter(n=>n.classList.contains(name)||n.className?.split(' ').includes(name));
const button=(e,name)=>walk(e).find(n=>n.tagName==='button'&&n.textContent.trim()===name);
(async()=>{
 await flush();await window.RelayWorkspace.refreshJobs();await flush();
 const list=el('workspace-job-list'),body=el('workspace-detail-body');
 assert.equal(list.children.length,3);assert.equal(cls(list,'workflow-node').length,0,'Jobs is a list, not a graph of jobs');
 list.children[0].querySelector('.job-row').onclick();await flush();
 assert.equal(cls(body,'workflow-node').length,2);assert.equal(button(body,'Canvas'),undefined,'no redundant Canvas menu');
 assert.match(body.textContent,/No saved node graph for stages: deliver/);assert.equal(cls(body,'workflow-lines')[0].children.length,1,'only exact cross-run artifact binding');assert.equal(cls(body,'job-chat-panel').length,1);assert.equal(cls(body,'canvas-host')[0].classList.contains('inspector-hidden'),true);assert.equal(cls(body,'job-chat-panel')[0].hidden,true);button(body,'Chat').onclick();assert.equal(cls(body,'job-chat-panel')[0].hidden,false);assert.match(body.textContent,/Earlier run/);
 assert.equal(cls(body,'canvas-project-menu').length,0,'no overloaded job dropdown');
 const readsBefore=calls.filter(r=>r.path==='workspace-jobs').length;
 button(body,'Jobs').onclick();assert.equal(cls(body,'jobs-drawer').length,1);await flush();
 assert(calls.filter(r=>r.path==='workspace-jobs').length>readsBefore,'opening Jobs loads saved records instead of relying on a warm session cache');
 assert.match(cls(body,'jobs-drawer')[0].textContent,/Saved room workflow/);
 const footer=cls(body,'jobs-drawer-footer')[0];
 assert.equal(cls(body,'jobs-drawer')[0].children.at(-1),footer,'app controls stay below the separately scrolling list');
 assert(button(footer,'Telegram'));assert(button(footer,'Settings'));assert.equal(button(footer,'Nodes'),undefined);
 button(body,'Jobs').onclick();assert.equal(cls(body,'jobs-drawer')[0].hidden,true,'Jobs collapses without shrinking the canvas');
 cls(body,'workflow-step')[1].onclick();assert.equal(cls(body,'canvas-host')[0].classList.contains('inspector-hidden'),false);const inspector=cls(body,'workflow-inspector')[0];assert.match(inspector.textContent,/exact.pptx/);
 button(inspector,'Open saved execution').onclick();await flush();assert.equal(cls(body,'workflow-node').length,1);assert.match(body.textContent,/‹ Saved room workflow/);
 assert.equal(cls(body,'canvas-host')[0].hidden,false);
 button(body,'History').onclick();assert.equal(cls(body,'canvas-history')[0].hidden,false);assert.equal(cls(body,'canvas-host')[0].hidden,false,'history floats over the saved graph');
 assert(button(body,'+ Step'));assert.equal(button(body,'Share'),undefined);assert.equal(button(body,'Run ↗'),undefined,'unimplemented actions are not displayed');
 button(body,'‹ Saved room workflow').onclick();await flush();assert.equal(cls(body,'workflow-node').length,2);
 assert.equal(cls(body,'workflow-node').some(n=>n.dataset.task==='deliver'),false,'pending stage cannot invent a node');
 window.RelayWorkspace.navigate('jobs');await flush();list.children[1].querySelector('.job-row').onclick();await flush();assert.equal(cls(body,'workflow-node').length,2);assert.match(body.textContent,/not executed/);
 window.RelayWorkspace.navigate('jobs');await flush();list.children[2].querySelector('.job-row').onclick();await flush();assert.equal(button(body,'Canvas'),undefined,'no redundant Canvas menu');assert.equal(cls(body,'workflow-node').length,0);assert.match(body.textContent,/No saved workflow graph/);assert.match(cls(body,'job-chat-panel')[0].textContent,/Saved answer/);button(body,'History').onclick();assert.match(cls(body,'canvas-results')[0].textContent,/Saved research/);
 // Output shortcut opens the recorded answer in a modal, without selecting a node.
 window.RelayWorkspace.navigate('jobs');await flush();list.children[0].querySelector('.job-row').onclick();await flush();
 const quick=cls(body,'canvas-output-open');assert.equal(quick.length,1);
 const hiddenBeforeQuick=cls(body,'canvas-host')[0].classList.contains('inspector-hidden');
 const quickStart=calls.length;
 await quick[0].onclick({stopPropagation(){},preventDefault(){}});await flush();
 assert.equal(cls(body,'canvas-host')[0].classList.contains('inspector-hidden'),hiddenBeforeQuick);
 assert.equal(cls(document.body,'canvas-output-dialog').length,1);
 assert.match(cls(document.body,'canvas-output-dialog')[0].textContent,/Saved research/);
 assert(calls.slice(quickStart).some(r=>r.path==='workspace-artifact' && r.value.artifact==='page' && r.value.sha256==='source-hash' && r.value.preview));
 assert(calls.slice(quickStart).every(r=>r.path==='workspace-artifact'),'quick-open never dispatches');
 const quickProse=cls(document.body,'rich-text').find(n=>n.textContent.includes('Saved research'));
 assert.equal(typeof quickProse.renderOptions.openLink,'function','saved research must override generic setup-URL opener');
 await quickProse.renderOptions.openLink('https://www.perplexity.ai/search/saved-thread');await flush();
 const openingError=cls(document.body,'artifact-link-error')[0];assert.equal(openingError.hidden,false);
 assert.match(openingError.textContent,/Controlled browser opening failure/);
 button(openingError,'Dismiss').onclick();assert.equal(openingError.hidden,true);
 await quickProse.renderOptions.openLink('https://www.perplexity.ai/search/saved-thread');assert.equal(openingError.hidden,false);
 savedLinkFailure=false;await quickProse.renderOptions.openLink('https://www.perplexity.ai/search/saved-thread');assert.equal(openingError.hidden,true,'successful manual retry clears local error');
 button(cls(document.body,'canvas-output-dialog')[0],'Close').onclick();
 assert.equal(cls(document.body,'canvas-output-dialog').length,0);
 // A slow read must finish even when multiple eight-second polling ticks occur.
 window.RelayWorkspace.navigate('jobs');await flush();held=[];list.children[0].querySelector('.job-row').onclick();
 const slow=held,detailReads=calls.filter(r=>r.path==='workspace-detail').length;
 for(let tick=0;tick<3;tick++){for(const timer of timers)timer();await flush();}
 assert.equal(calls.filter(r=>r.path==='workspace-detail').length,detailReads,'polling must not supersede an unfinished read');
 held=null;slow[0](pipeline);await flush();assert.equal(cls(body,'workflow-node').length,2,'the original slow response must render');
 // A late detail response cannot resurrect a workflow after leaving it.
 window.RelayWorkspace.navigate('jobs');await flush();held=[];list.children[0].querySelector('.job-row').onclick();const pending=held;held=null;window.RelayWorkspace.navigate('jobs');await flush();const old=body.textContent;pending[0](pipeline);await flush();assert.equal(body.textContent,old);
 assert.equal(JSON.stringify({pipeline,run,proposal}),before,'presentation must preserve all saved records');
 assert(calls.every(r=>['workspace-jobs','workspace-detail','workspace-plan','workspace-chat','workspace-artifact'].includes(r.path) || r.path==='workspace_open_artifact_link'),'navigation never starts services or dispatches');
 // Canvas thumbnails use current saved images only, including native preview PNGs.
 run.latest_outputs=[{id:'pixels',task:'render',attempt:'exact',path:'cup.png',sha256:'pixel-hash',purpose:'Cup'}];
 run.historical_outputs=[{id:'old-image',task:'render',path:'old.png',sha256:'old'}];
 items.push({id:'export-run',kind:'run',run:'export-run',title:'Image result',status:'completed',channel:'desktop'});
 previewHash='other-version';
 imagesVisible=false;
 await window.RelayWorkspace.refreshJobs();await flush();list.children[3].querySelector('.job-row').onclick();await flush();
 assert.equal(cls(body,'canvas-image-button').length,1);
 assert.equal(calls.filter(r=>r.path==='workspace-artifact' && r.value.preview && r.value.artifact!=='page').length,0,'offscreen images are not read');
 imagesVisible=true;await flush();
 assert.match(cls(body,'canvas-image-button')[0].textContent,/Preview unavailable/);
 cls(body,'workflow-step')[0].onclick();const imagePanel=cls(body,'workflow-inspector')[0];
 await flush();previewHash='pixel-hash';await button(imagePanel,'Preview unavailable — Retry').onclick();await flush();
 assert.equal(cls(imagePanel,'canvas-image-button')[0].children[0].src,'data:image/png;base64,aW1hZ2U=');
 const read=calls.filter(r=>r.path==='workspace-artifact' && r.value.preview && r.value.artifact!=='page');assert.equal(read.length,2);
 assert(read.every(r=>r.value.artifact==='pixels' && r.value.sha256==='pixel-hash' && r.value.preview===true));
 await list.children[3].querySelector('.job-row').onclick();await flush();
 let thumb=cls(body,'canvas-image-button')[0];
 assert.equal(thumb.children[0].src,'data:image/png;base64,aW1hZ2U=');
 thumb.onclick();let dialog=cls(body,'canvas-image-dialog')[0];assert.equal(dialog.open,true);
 assert.equal(dialog.querySelector('img').src,thumb.children[0].src);
 dialog.oncancel({preventDefault(){}});assert.equal(cls(body,'canvas-image-dialog').length,0);
 thumb.onclick();dialog=cls(body,'canvas-image-dialog')[0];button(dialog,'Close').onclick();
 assert.equal(calls.filter(r=>r.path==='workspace-artifact' && r.value.preview && r.value.artifact!=='page').length,2,'enlarge and refresh reuse exact cached pixels');
 // A new saved version is read again; native geometry is not pretended to be an image.
 run.latest_outputs=[{id:'native',task:'render',path:'model.3dm',sha256:'model-hash'},{id:'rhino-preview',task:'render',path:'preview.png',sha256:'native-pixels'}];
 previewHash='native-pixels';await list.children[3].querySelector('.job-row').onclick();await flush();
 assert.equal(cls(body,'canvas-image-button').length,2,'canvas and selected inspector share the cached preview');
 assert.equal(calls.filter(r=>r.path==='workspace-artifact' && r.value.preview && r.value.artifact!=='page').at(-1).value.artifact,'rhino-preview');
 assert(!calls.some(r=>r.path==='workspace-artifact' && r.value.preview && ['native','old-image'].includes(r.value.artifact)));
 run.latest_outputs=[{id:'pixels',task:'render',attempt:'exact',path:'cup.png',sha256:'pixel-hash',purpose:'Cup'}];run.historical_outputs=[];
 // Result actions bind an exact completed output; edits never run implicitly.
 run.canvas_run=true;run.status='completed';run.tasks[0].status='completed';run.tasks[0].planned_outputs=[{path:'cup.png',media_type:'image/png'}];
 await list.children[3].querySelector('.job-row').onclick();await flush();cls(body,'workflow-step')[0].onclick();
 let panel=cls(body,'workflow-inspector')[0];
 await button(panel,'Use output…').onclick();await flush();
 window.RelayNodeEditor={mount:(_,o)=>{editorOptions=o;edited=o.record;return ()=>{};}};
 await button(panel,'Gemini image').onclick();await flush();
 editorOptions.modelSettings();assert.equal(el('model-settings').open,true);assert.equal(el('workspace-settings').hidden,false);
 assert.equal(edited.origin.artifact,'pixels');assert.equal(edited.origin.sha256,'pixel-hash');assert.equal(edited.origin.operation,'gemini.image');
 await list.children[3].querySelector('.job-row').onclick();await flush();cls(body,'workflow-step')[0].onclick();panel=cls(body,'workflow-inspector')[0];
 const prompt=walk(panel).find(n=>n.attributes['aria-label']==='Node prompt');assert(prompt);prompt.value='Make it blue';prompt.oninput();
 const previousDrafts=calls.filter(r=>r.path==='node-result-draft').length;
 await button(panel,'Save prompt').onclick();await flush();assert.match(panel.textContent,/Prompt saved on this canvas/);
 await cls(body,'canvas-node-run')[0].onclick();await flush();panel=cls(body,'workflow-inspector')[0];assert.match(cls(body,'canvas-node-confirmation')[0].textContent,/Only this node will run/);assert.equal(button(panel,'Run · paid'),undefined);
 assert.equal(calls.filter(r=>r.path==='node-result-draft').length,previousDrafts,'in-place edit creates no separate draft job');
 assert.equal(walk(panel).find(n=>n.type==='checkbox'),undefined);
 assert.equal(calls.filter(r=>r.path==='node-run-preview').at(-1).value.run,'export-run');
 assert.equal(calls.filter(r=>r.path==='node-run-start').length,0,'draft actions never dispatch');
 await button(cls(body,'canvas-node-confirmation')[0],'Run · paid').onclick();await flush();
 await button(cls(body,'canvas-node-confirmation')[0],'Check same submission').onclick();await flush();
 const executions=calls.filter(r=>r.path==='node-run-start');assert.equal(executions.length,2);assert.deepEqual(executions[0].value,executions[1].value);assert.equal(executions[0].value.allow_paid,true);
 await list.children[3].querySelector('.job-row').onclick();await flush();cls(body,'workflow-step')[0].onclick();panel=cls(body,'workflow-inspector')[0];
 button(panel,'Chat about result').onclick();let chatPanel=cls(body,'job-chat-panel')[0];
 assert.equal(chatPanel.hidden,false);
 const question=walk(chatPanel).find(n=>n.tagName==='textarea');question.value='What color is the cup?';question.oninput();
 await button(chatPanel,'Send · Codex').onclick();await flush();
 assert.match(chatPanel.textContent,/Lost response/);
 await button(chatPanel,'Check saved submission').onclick();await flush();
 const sends=calls.filter(r=>r.path==='node-result-chat');assert.equal(sends.length,2);assert.deepEqual(sends[0].value,sends[1].value);
 assert.equal(sends[0].value.artifact,'pixels');assert.equal(sends[0].value.attempt,'exact');assert.equal(storage.size,0);
 assert(calls.filter(r=>r.value.allow_paid).every(r=>r.path==='node-run-start'),'only the explicit paid Run authorizes execution');
 run.tasks[0].prompt='Current graph prompt';
 run.canvas_document={canvas:run.name,title:'Canvas',revision:'graph-1',values:{},workflow:{schema_version:1,kind:'workflow',inputs:{},tasks:[{schema_version:3,id:'render',operation:'gemini.image',objective:'Image',inputs:{prompt:{value:'Current graph prompt'}}}]}};
 await list.children[3].querySelector('.job-row').onclick();await flush();
 assert.equal(edited.workflow.tasks[0].inputs.prompt.value,'Current graph prompt','reopening uses the canonical editable canvas');
 assert.equal(edited.display.name,run.name);assert.equal(typeof editorOptions.trackRun,'function');assert.equal(typeof editorOptions.renderResults,'function');
 // Editor-owned canvases must not enter the legacy automatic reopen loop.
 editorOptions.onSaved({canvas:run.name,title:'Saved canvas'});
 const beforePoll=calls.filter(r=>['workspace-detail','node-draft'].includes(r.path)).length;
 for(const timer of timers)timer();await flush();
 assert.equal(calls.filter(r=>['workspace-detail','node-draft'].includes(r.path)).length,beforePoll,'saving must not remount the editor on poll');
 const authoredDocument=run.canvas_document;delete run.canvas_document;
 // A held advance must not hide recorded progress or allow duplicate advancement.
 run.status='active';run.tasks[0].status='running';run.executing_runs=['export-run'];advanceHeld=[];
 const loading=list.children[3].querySelector('.job-row').onclick();await flush();
 assert.match(cls(body,'canvas-node-state')[0].textContent,/Running/);
 assert.equal(cls(body,'canvas-node-run')[0].disabled,true);
 assert.equal(advanceHeld.length,1);const again=list.children[3].querySelector('.job-row').onclick();await flush();assert.equal(advanceHeld.length,1);
 const complete=advanceHeld[0];advanceHeld=null;complete({});await loading;await again;
 run.status='completed';run.tasks[0].status='completed';run.executing_runs=[];await list.children[3].querySelector('.job-row').onclick();await flush();
 assert.match(cls(body,'canvas-node-state')[0].textContent,/Completed/);assert.equal(cls(body,'canvas-node-run')[0].disabled,false);
 run.tasks[0].operation='blender.mesh_scene';delete run.tasks[0].prompt;delete run.tasks[0].prompt_draft;
 authoredDocument.workflow.tasks[0]={schema_version:3,id:'render',operation:'blender.mesh_scene',objective:'Cup mesh',inputs:{}};
 await list.children[3].querySelector('.job-row').onclick();await flush();cls(body,'workflow-step')[0].onclick();
 assert.equal(walk(cls(body,'workflow-inspector')[0]).find(n=>n.attributes['aria-label']==='Node prompt'),undefined,'native mesh builder must not invent a prompt input');
 assert.equal(button(body,'Edit inputs & setup'),undefined,'legacy records without a canonical graph do not invent an editor');
 // One public output list; receipt/script remain under collapsed technical details.
 run.latest_outputs=[
  {id:'mesh',task:'render',attempt:'exact',path:'delivery/scene.blend',sha256:'mesh-hash',display_name:'Blender model',result_role:'primary',open_with:'Blender'},
  {id:'mesh-preview',task:'render',attempt:'exact',path:'delivery/preview.png',sha256:'native-pixels',display_name:'Render preview',result_role:'preview'},
  {id:'script',task:'render',attempt:'exact',path:'delivery/scene-script.py',display_name:'Generated script',result_role:'technical'},
  {id:'receipt',task:'render',attempt:'exact',path:'delivery/execution.json',display_name:'Execution receipt',result_role:'technical'}];
 run.tasks[0].planned_outputs=[{path:'delivery/scene.blend',media_type:'application/x-blender'},{path:'delivery/preview.png',media_type:'image/png'}];
 previewHash='native-pixels';
 await list.children[3].querySelector('.job-row').onclick();await flush();cls(body,'workflow-step')[0].onclick();await flush();
 panel=cls(body,'workflow-inspector')[0];
 assert.equal(cls(panel,'node-result').length,2);
 const nativeShortcuts=cls(body,'canvas-output-open');assert.equal(nativeShortcuts.length,2);
 const callsBeforeQuickNative=calls.length;
 await nativeShortcuts[0].onclick({stopPropagation(){},preventDefault(){}});await flush();
 assert.deepEqual(JSON.parse(JSON.stringify(calls[callsBeforeQuickNative])),{path:'workspace-open-artifact',value:{artifact:'mesh',sha256:'mesh-hash'}});
 await nativeShortcuts[1].onclick({stopPropagation(){},preventDefault(){}});await flush();
 assert.equal(cls(document.body,'canvas-output-dialog')[0].querySelector('img').src,'data:image/png;base64,aW1hZ2U=');
 button(cls(document.body,'canvas-output-dialog')[0],'Close').onclick();

 assert.equal(walk(panel).filter(n=>n.tagName==='button'&&n.textContent==='Use output…').length,1);
 assert.equal(walk(panel).filter(n=>n.tagName==='button'&&n.textContent==='Chat about result').length,1);
 const technical=walk(panel).find(n=>n.tagName==='details'&&n.children[0]?.textContent==='Technical details');
 assert(!technical.open);assert.match(technical.textContent,/Generated script/);assert.match(technical.textContent,/Execution receipt/);
 assert(cls(panel,'node-result').every(n=>!n.textContent.includes('Execution receipt')));
 const startsBeforeOpen=calls.filter(r=>r.path==='node-run-start').length;
 await button(panel,'Open in Blender').onclick();await flush();
 assert.equal(JSON.stringify(calls.filter(r=>r.path==='workspace-open-artifact').at(-1).value),JSON.stringify({artifact:'mesh',sha256:'mesh-hash'}));
 assert.equal(calls.filter(r=>r.path==='node-run-start').length,startsBeforeOpen,'opening never reruns the node');
 button(panel,'Use output…').onclick();
 assert(button(panel,'Blender model'));assert(button(panel,'Render preview'));
 assert(!button(button(panel,'Use output…').parent,'Execution receipt'),'diagnostic files are not primary reuse choices');
 await button(panel,'Render preview').onclick();await flush();
 assert(button(panel,'Gemini image'),'choosing an output opens the existing compatible-node picker');

 // Exact Markdown and paged PDF previews appear directly in Results.
 run.latest_outputs=[{id:'markdown-file',task:'render',attempt:'exact',path:'report.md',sha256:'md-hash',display_name:'Report'},
 {id:'pdf-file',task:'render',attempt:'exact',path:'report.pdf',sha256:'pdf-hash',display_name:'PDF'}];
 await list.children[3].querySelector('.job-row').onclick();await flush();cls(body,'workflow-step')[0].onclick();await flush();
 panel=cls(body,'workflow-inspector')[0];
 const resultProse=cls(panel,'rich-text').find(n=>n.renderedHTML?.includes('<h1>Report'));
 assert(resultProse);assert.match(resultProse.renderedHTML,/<strong>Clear result<\/strong>/);assert.match(resultProse.renderedHTML,/<table>/);
 assert.match(panel.textContent,/Page 1 of 2/);assert.equal(button(panel,'Previous page').disabled,true);
 await button(panel,'Next page').onclick();await flush();assert.match(panel.textContent,/Page 2 of 2/);assert.equal(button(panel,'Next page').disabled,true);
 // Permanent delete is previewed from the list; cancel and blockers have no effect.
 await window.RelayWorkspace.refreshJobs();await flush();
 const initialDeletes=calls.filter(r=>r.path==='conversation-delete').length;
 await button(list.children[2],'Delete').onclick();
 assert.equal(calls.filter(r=>r.path==='conversation-delete').length,initialDeletes,'cancel keeps the job');
 deleteApproval=true;
 await button(list.children[0],'Delete').onclick();assert.match(list.textContent,/not finished/);
 const detailsBefore=calls.filter(r=>r.path==='workspace-detail').length;
 const chatEntry=list.children.find(e=>e.textContent.includes('Saved conversation'));
 await button(chatEntry,'Delete').onclick();await flush();
 assert(!list.textContent.includes('Saved conversation'));assert.equal(calls.filter(r=>r.path==='workspace-detail').length,detailsBefore);
 el('workspace-show-removed').checked=true;await el('workspace-show-removed').onchange();await flush();
 assert(!list.textContent.includes('Saved conversation'),'permanent deletion does not archive');
 el('workspace-show-removed').checked=false;await el('workspace-show-removed').onchange();await flush();
 // Stopped uncertainty requires the explicit warning and confirmation.
 items.push({id:'stopped',kind:'run',title:'Stopped image',status:'completed',channel:'desktop'});
 await window.RelayWorkspace.refreshJobs();await flush();deleteApproval=false;
 let stoppedEntry=list.children.find(e=>e.textContent.includes('Stopped image'));
 await button(stoppedEntry,'Delete').onclick();
 assert.match(deleteWarning,/unknown external outcome/);assert.match(deleteWarning,/Nothing will be retried/);
 assert(!calls.some(r=>r.path==='job-delete'));
 deleteApproval=true;await button(stoppedEntry,'Delete').onclick();await flush();
 assert(!list.textContent.includes('Stopped image'));
 // The same Jobs drawer is available outside a canvas; app navigation has no execution effects.
 const hiddenCanvas=new Element('section'),nestedDrawer=new Element('aside');hiddenCanvas.hidden=true;nestedDrawer.className='jobs-drawer';hiddenCanvas.append(nestedDrawer);el('workspace-content').append(hiddenCanvas);
 const beforeNavigation=calls.length;
 window.RelayWorkspace.navigate('settings');el('workspace-jobs-toggle').onclick();await flush();
 let appDrawer=cls(el('workspace-content'),'app-jobs-drawer')[0];assert(appDrawer);
 assert.equal(nestedDrawer.hidden,false,'global Jobs does not toggle a drawer inside the hidden canvas');
 assert.match(appDrawer.textContent,/Saved room workflow/);
 await button(cls(appDrawer,'jobs-drawer-footer')[0],'Telegram').onclick();await flush();
 assert.equal(el('workspace-breadcrumb').textContent,'Connections');
 assert.equal(cls(el('workspace-content'),'app-jobs-drawer').length,0,'drawer closes on destination change');
 el('workspace-jobs-toggle').onclick();await flush();appDrawer=cls(el('workspace-content'),'app-jobs-drawer')[0];
 await button(appDrawer,'Settings').onclick();assert.equal(el('workspace-breadcrumb').textContent,'Settings');
 assert(calls.slice(beforeNavigation).every(r=>['workspace-jobs','node-drafts'].includes(r.path)),'navigation never starts services or runs: '+JSON.stringify(calls.slice(beforeNavigation).map(r=>r.path)));
 const html=fs.readFileSync('task_relay/assets/companion.html','utf8');
 assert(!html.includes('workspace-app-menu'));assert(!html.includes('data-destination="catalog"'),'the canvas library is the sole Nodes entry');
 // Merge drafts and conversations by activity, without giving drafts priority.
 items.push({id:'new-telegram',kind:'chat',title:'Newest Telegram request',status:'failed',channel:'telegram',stamp:300});
 draftItems=[{id:'old-draft',kind:'draft',title:'Older draft',status:'draft',stamp:100},{id:'recent-draft',kind:'draft',title:'Recently edited draft',status:'draft',stamp:200}];
 await window.RelayWorkspace.refreshJobs();await flush();
 assert.match(list.children[0].textContent,/Newest Telegram request/);
 assert.match(list.children[1].textContent,/Recently edited draft/);
 assert.match(list.children[2].textContent,/Older draft/);
 draftItems[0].stamp=400;await window.RelayWorkspace.refreshJobs();await flush();
 assert.match(list.children[0].textContent,/Older draft/,'editing a draft can make it newest');
 assert.match(list.children[1].textContent,/Newest Telegram request/);
 // Failed Telegram conversations have a pinned composer; lost Send checks receipts only.
 Object.assign(chat,{id:'new-telegram',channel:'telegram',status:'failed',flow:null,can_message:true,message_model:{provider:'gemini',model:'shared-current'}});
 list.children[1].querySelector('.job-row').onclick();await flush();
 // Real saved Markdown reaches the shared renderer; user text remains literal.
 chat.answer='### Repairability\n\n* **Parts:** Keep a buffer.\n\n1. Check rust.\n2. Inspect it.\n\n[Source](https://docs.example/car)';
 chat.evidence={sources:[{url:'https://docs.example/car'}]};
 await el('workspace-detail-refresh').onclick();await flush();
 button(body,'Chat').onclick();await flush();
 let transcript=cls(body,'job-chat-messages')[0];
 const prose=cls(transcript,'rich-text')[0];
 assert.match(prose.renderedHTML,/<h3>Repairability<\/h3>/);assert.match(prose.renderedHTML,/<strong>Parts:<\/strong>/);
 assert.match(prose.renderedHTML,/<ol>/);assert(prose.renderOptions.linkAllowed('https://docs.example/car'));assert(!prose.renderOptions.linkAllowed('https://unrecorded.example'));
 assert.equal(cls(cls(transcript,'user')[0],'rich-text').length,0,'user request stays literal');
 transcript.scrollTop=480;transcript.onscroll();
 chat.answer+='\n\nUpdated detail';await el('workspace-detail-refresh').onclick();await flush();
 transcript=cls(body,'job-chat-messages')[0];assert.equal(transcript.scrollTop,480,'refresh preserves reading position away from the bottom');
 transcript.scrollTop=1300;transcript.onscroll();fixtureScrollHeight=2500;
 chat.answer+='\n\nNew reply';await el('workspace-detail-refresh').onclick();await flush();
 transcript=cls(body,'job-chat-messages')[0];assert.equal(transcript.scrollTop,1800,'reader at bottom follows new content');
 transcript.scrollTop=600;transcript.onscroll();button(body,'Chat').onclick();
 chat.answer+='\n\nHidden update';await el('workspace-detail-refresh').onclick();await flush();
 button(body,'Chat').onclick();await flush();assert.equal(cls(body,'job-chat-messages')[0].scrollTop,600,'hidden refresh retains reading position');
 let composer=cls(body,'workflow-chat-composer')[0];
 assert(composer);assert.match(composer.textContent,/gemini · shared-current · Shared setting/);
 assert.equal(button(composer,'Send').disabled,true);
 let input=walk(composer).find(e=>e.tagName==='textarea');input.value='Please continue with repairability';input.oninput();
 assert.equal(button(composer,'Send').disabled,false);
 await button(composer,'Send').onclick();await flush();
 assert.match(composer.textContent,/Check status/);assert.equal(input.disabled,true);
 assert.match(cls(body,'pending-chat-turn')[0].textContent,/Please continue with repairability/);
 assert.match(cls(body,'pending-chat-turn')[0].textContent,/Send not confirmed/);
 assert.equal(calls.filter(r=>r.path==='conversation-followup' && !r.value.check).length,1);
 // Reopen preserves unknown admission rather than generating a new request identity.
 list.children[1].querySelector('.job-row').onclick();await flush();composer=cls(body,'workflow-chat-composer')[0];
 assert(button(composer,'Check status'));const placeholdersBefore=replacementTexts.filter(s=>s==='Reading saved job…').length;
 await button(composer,'Check status').onclick();await flush();
 assert.equal(replacementTexts.filter(s=>s==='Reading saved job…').length,placeholdersBefore,'committed send refreshes in place without blanking the canvas');
 assert.equal(cls(body,'pending-chat-turn').length,0,'committed turn replaces optimistic bubble without duplication');
 assert.match(cls(body,'job-chat-panel')[0].textContent,/Waiting to start…/);
 const messageCalls=calls.filter(r=>r.path==='conversation-followup');assert.equal(messageCalls.length,2);
 assert.equal(messageCalls[1].value.request_id,messageCalls[0].value.request_id);assert.equal(messageCalls[1].value.check,true);
 assert.equal(storage.has('relay:conversation-message:new-telegram'),false);
 assert.match(cls(body,'job-chat-panel')[0].textContent,/Please continue with repairability/);
 assert.equal(button(cls(body,'workflow-chat-composer')[0],'Send').disabled,true,'pending reply cannot enqueue another request');
 // A conversation reply and its real execution coexist on the same canvas.
 const imageExecution={...run,canvas_document:null,workflow_export:{canvas:'work-image',revision:'graph-version',title:'Online photos'},name:'work-image',status:'completed',brief:'Online photos',tasks:[
  {id:'photos',objective:'Acquire requested photos',status:'completed',planned_outputs:[{path:'outputs/result.zip',media_type:'application/zip'}]},
  {id:'gallery',objective:'Show acquired photos',status:'completed',dependencies:[{task:'photos'}],planned_inputs:[{path:'photos.zip',from_task:'photos',output:'outputs/result.zip'}],planned_outputs:[{path:'outputs/result.html',media_type:'text/html'}]}],
  latest_outputs:[{id:'gallery-file',task:'gallery',path:'outputs/result.html',media_type:'text/html',sha256:'gallery-hash',purpose:'Photo gallery'}]};
 chat.flow={status:'completed',tasks:[],stages:[{request_id:'image-request',mode:'message',status:'completed',
  conversation:{id:'image-request',prompt:'Show online photos',answer:'Images acquired',status:'answered'},execution:imageExecution}]};
 await el('workspace-detail-refresh').onclick();await flush();
 assert.match(body.textContent,/Acquire requested photos/);assert.match(body.textContent,/Show acquired photos/);
 assert.match(body.textContent,/Photo gallery/);assert.match(body.textContent,/Images acquired/);
 cls(body,'workflow-step')[1].onclick();await flush();
 let galleryPanel=cls(body,'workflow-inspector')[0];
 assert.match(galleryPanel.textContent,/Photo gallery/);assert.match(galleryPanel.textContent,/\/saved\/jobs\/Volvo\/delivery/);
 const savedCanvas=cls(body,'canvas-host')[0];
 window.RelayWorkspace.navigate('settings');assert(!document.body.classList.contains('canvas-workspace'));
 el('settings-back-canvas').onclick();assert.equal(cls(body,'canvas-host')[0],savedCanvas);assert.equal(cls(body,'workflow-inspector')[0],galleryPanel);assert(document.body.classList.contains('canvas-workspace'));
 window.RelayWorkspace.navigate('connections');el('connections-back-canvas').onclick();assert.equal(cls(body,'workflow-inspector')[0],galleryPanel);
 let frame=walk(galleryPanel).find(n=>n.tagName==='iframe');
 assert.equal(frame.attributes.sandbox,'');assert.equal(frame.attributes.referrerpolicy,'no-referrer');assert.match(frame.srcdoc,/Saved Volvo gallery/);
 assert.notEqual(window.RelayWorkflow.renderKey({inputs:{value:{captured_at:1}}}),window.RelayWorkflow.renderKey({inputs:{value:{captured_at:2}}}),'user data named captured_at remains significant');
 // Observation timestamps alone must not detach the iframe or reset its inner scroll.
 walk(galleryPanel).find(n=>n.attributes['aria-label']==='Expand Results to full width').onclick();
 assert(galleryPanel.classList.contains('panel-expanded'));
 galleryPanel.scrollTop=480;galleryPanel.onscroll();
 imageExecution.captured_at=42;await el('workspace-detail-refresh').onclick();await flush();
 assert.equal(cls(body,'workflow-inspector')[0],galleryPanel,'timestamp-only polling retains the inspector DOM');
 assert.equal(walk(galleryPanel).find(n=>n.tagName==='iframe'),frame,'timestamp-only polling retains the embedded gallery');
 assert.equal(galleryPanel.scrollTop,480);
 button(galleryPanel,'Enlarge gallery').onclick();assert.equal(walk(galleryPanel).find(n=>n.tagName==='dialog').open,true);
 button(walk(galleryPanel).find(n=>n.tagName==='dialog'),'Close').onclick();
 button(galleryPanel,'Inputs').onclick();
 chat.answer='Changed status from background refresh';await el('workspace-detail-refresh').onclick();await flush();
 galleryPanel=cls(body,'workflow-inspector')[0];
 assert.match(galleryPanel.textContent,/Photo gallery/,'selected node survives changed conversation refresh');
 assert.equal(galleryPanel.scrollTop,480,'actual changes restore inspector reading position');
 assert(galleryPanel.classList.contains('panel-expanded'),'actual changes preserve full width');
 walk(galleryPanel).find(n=>n.attributes['aria-label']==='Restore Results width').onclick();
 assert.equal(button(galleryPanel,'Inputs').attributes['aria-pressed'],'true','selected inspector tab survives refresh');
 assert.equal(cls(body,'canvas-host')[0].classList.contains('inspector-hidden'),false);
 button(galleryPanel,'Results').onclick();assert(walk(galleryPanel).some(n=>n.tagName==='iframe'));
 const htmlReads=calls.filter(r=>r.path==='workspace-artifact' && r.value.preview && r.value.artifact==='gallery-file').length;assert.equal(htmlReads,1,'exact preview reused across refresh');
 walk(galleryPanel).find(n=>n.attributes['aria-label']==='Close inspector').onclick();
 chat.answer='Another refresh';await el('workspace-detail-refresh').onclick();await flush();
 assert.equal(button(cls(body,'workflow-inspector')[0],'Enlarge gallery'),undefined,'closed selection must not reopen on poll');
 assert.equal(cls(body,'canvas-host')[0].classList.contains('inspector-hidden'),true);
 assert.equal(calls.filter(r=>r.path==='conversation-followup').length,2,'display does not replay the request');
 window.__TAURI__.dialog={save:async()=>'/tmp/Photos.relay.zip',open:async()=>'/tmp/Photos.relay.zip'};
 button(body,'Export').onclick();let exportDialog=walk(document.body).find(n=>n.tagName==='dialog');
 assert.match(exportDialog.textContent,/Include input files/);assert.match(exportDialog.textContent,/API keys, results and history are not included/);
 await button(exportDialog,'Export workflow').onclick();assert.match(exportDialog.textContent,/Exported 2 nodes/);button(exportDialog,'Done').onclick();
 button(body,'Jobs').onclick();await flush();await button(body,'Import workflow').onclick();await flush();
 assert.equal(edited.id,'imported-draft','import opens an ordinary new editable draft');
 assert.equal(calls.filter(r=>r.path==='workflow-import').length,1);
 // Template browsing is read-only; selection creates one normal editable copy.
 const templateStart=calls.length;
 await button(body,'Templates').onclick();await flush();
 const templateDialog=cls(document.body,'workflow-template-dialog')[0];
 assert.match(templateDialog.textContent,/Cellular aggregation · from Chat/);
 assert.equal(calls.slice(templateStart).filter(r=>r.path==='node-draft-save').length,0);
 await button(templateDialog,'Use template').onclick();await flush();
 assert.equal(edited.id,'template-copy');assert.equal(edited.workflow.tasks.length,11);
 assert.equal(calls.slice(templateStart).filter(r=>r.path==='node-draft-save').length,1);
 assert(!calls.slice(templateStart).some(r=>/node-run|node-compose|node-connect/.test(r.path)),'template selection never executes or configures providers');


 console.log('Canvas app passed: chronological merged Jobs, searchable list, full canvas with toggled panels, exact bindings, late response and read-only navigation.');
})().catch(e=>{console.error(e);process.exitCode=1;});
