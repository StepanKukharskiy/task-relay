// Small DOM fixture: camera/selection interactions must never mutate execution data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.dataset={};this.style={};this.hidden=false;this.textContent='';this.clientWidth=1000;this.clientHeight=600;this.offsetHeight=27;this.offsetTop=80;this.isConnected=true;const classes=new Set();this.classList={add:(...v)=>v.forEach(x=>classes.add(x)),contains:v=>classes.has(v),toggle:(v,force)=>{const on=force===undefined?!classes.has(v):force;if(on)classes.add(v);else classes.delete(v);return on;}};}
 append(...nodes){for(const n of nodes){n.remove();n.parent=this;this.children.push(n);}}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
 replaceChildren(...nodes){this.children.forEach(n=>n.parent=null);this.children=[];this.append(...nodes);}
 setAttribute(k,v){this.attributes[k]=v;} addEventListener(k,v){this['on'+k]=v;}
 querySelector(tag){return this.children.find(c=>c.tagName===tag)||this.children.map(c=>c.querySelector(tag)).find(Boolean);}
 getBoundingClientRect(){return {left:0,top:0,width:1000,height:600};}
 setPointerCapture(id){this.capture=id;}hasPointerCapture(id){return this.capture===id;}releasePointerCapture(){this.capture=null;}
 focus(){}scrollIntoView(){}
}
const node=(tag,value,cls)=>{const e=new Element(tag);if(value!==undefined)e.textContent=value;if(cls)e.classList.add(...cls.split(' '));return e;};
const button=(label,action,cls)=>{const e=node('button',label,cls);e.onclick=action;return e;};
const saved=(label,value)=>{const e=node('details');e.append(node('summary',label),node('pre',JSON.stringify(value)));return e;};
const root={},frames=[];let disconnected=0;
vm.runInNewContext(fs.readFileSync('task_relay/assets/companion-workflow.js','utf8'),{window:root,document:{createElement:tag=>node(tag),createElementNS:(_,tag)=>node(tag)},requestAnimationFrame:f=>frames.push(f),ResizeObserver:class{observe(){}disconnect(){disconnected++;}}});
const tasks=[{id:'fetch',objective:'Read article',status:'completed',latest_attempt:'a',planned_inputs:[{path:'url.txt'}],planned_outputs:[{path:'article/page.md'}],dependencies:[],recorded_inputs:[]},
 {id:'summary',objective:'Summarise',status:'blocked',latest_attempt:'b',planned_inputs:[{path:'inputs/article.md',from_task:'fetch',output:'article/page.md'}],planned_outputs:[{path:'summary.md'}],recorded_inputs:[{path:'inputs/article.md',file:{id:'exact-file',path:'article/page.md',sha256:'abc'}}],dependencies:[{task:'fetch'}],error:'Needs source text'}];
const view={name:'fixture',tasks,latest_outputs:[]},original=JSON.stringify(view),selections=[],files=[];
const options={node,button,saved,stateLabel:x=>x,outputFile:f=>{files.push(f);return node('p',f.path);},select:id=>selections.push(id)};
const walk=(e,cls)=>[...(e.classList.contains(cls)?[e]:[]),...e.children.flatMap(c=>walk(c,cls))];
const host=node('main'),dispose=root.RelayWorkflow.mount(host,view,options);frames.splice(0).forEach(f=>f());
const map=walk(host,'workflow-map')[0],world=walk(host,'workflow-world')[0],cards=walk(host,'workflow-node'),steps=walk(host,'workflow-step');
steps[1].onclick();assert.equal(selections.at(-1),'summary');assert.equal(files[0].sha256,'abc');assert.equal(walk(host,'workflow-inspector')[0].hidden,false);
const inspector=walk(host,'workflow-inspector')[0],tabs=walk(host,'inspector-tabs')[0];
tabs.children[0].onclick();assert.equal(tabs.children[0].attributes['aria-pressed'],'true');
tabs.children[1].onclick();assert.equal(tabs.children[1].attributes['aria-pressed'],'true');
const wire=walk(host,'workflow-lines')[0],controls=walk(host,'canvas-tools')[0],style=controls.children.find(e=>e.tagName==='select');
assert.match(wire.children[0].attributes.d,/ C /);assert.doesNotMatch(wire.children[0].attributes.d,/ L /,'curves have no invented overhead routing lanes');
style.value='straight';style.onchange();assert.match(wire.children[0].attributes.d,/ L /);
style.value='bezier';style.onchange();assert.match(wire.children[0].attributes.d,/ C /);
const p={button:0,clientX:100,clientY:100,pointerId:1};steps[1].onpointerdown(p);map.onpointermove({...p,clientX:160});map.onpointerup(p);steps[1].onclick();assert.equal(selections.length,1,'drag is not a click');
const x=cards[1].style.left;assert.notEqual(x,'310px');
const gridBeforePan=map.style.backgroundPosition.split(' ').map(parseFloat),spacingBefore=parseFloat(map.style.backgroundSize);
assert.equal(spacingBefore,24,'100% grid has 24px spacing');
map.onpointerdown({...p,target:map});map.onpointermove({...p,clientX:200});map.onpointerup(p);
assert.equal(parseFloat(map.style.backgroundPosition)-gridBeforePan[0],100,'dots follow pan without changing node coordinates');
assert.equal(cards[1].style.left,x,'panning does not snap or move nodes');
map.onwheel({preventDefault(){},deltaX:0,deltaY:-40,ctrlKey:true,clientX:500,clientY:300});const camera=world.style.transform;
const gridPosition=map.style.backgroundPosition,gridSize=map.style.backgroundSize;
assert(Math.abs(parseFloat(gridSize)/spacingBefore-Math.exp(.2))<1e-9,'grid scales with zoom');
assert.equal(JSON.stringify(view),original,'view interactions must not rewrite saved job');dispose();assert.equal(disconnected,1);
const next=node('main');root.RelayWorkflow.mount(next,{...view,tasks:tasks.map(t=>({...t,status:'completed'}))},options);frames.splice(0).forEach(f=>f());
assert.equal(walk(next,'workflow-node')[1].style.left,x);assert.equal(walk(next,'workflow-world')[0].style.transform,camera,'poll updates retain camera');
assert.equal(walk(next,'workflow-map')[0].style.backgroundPosition,gridPosition);
assert.equal(walk(next,'workflow-map')[0].style.backgroundSize,gridSize,'poll updates retain grid alignment');
const nextMap=walk(next,'workflow-map')[0];
nextMap.onwheel({preventDefault(){},deltaX:0,deltaY:10000,ctrlKey:true,clientX:500,clientY:300});
assert.equal(parseFloat(nextMap.style.backgroundSize),24,'at 25% only every fourth dot is drawn');
assert.equal(JSON.stringify(view),original,'grid never mutates execution data');
const edges=root.RelayWorkflow.canvasEdges(tasks);assert.equal(edges.length,1);assert.equal(edges[0].kind,'binding');
const broken=JSON.parse(JSON.stringify(tasks));broken[1].planned_inputs[0].output='missing.md';assert.equal(root.RelayWorkflow.canvasEdges(broken)[0].kind,'dependency','unknown port never appears as a file handoff');
const hi={id:'hi',objective:'Reply with exactly: Hi',backend:{type:'codex-agent',model:'gpt-6.1-sol'},attempts:1,max_attempts:2,status:'completed',planned_inputs:[],planned_outputs:[]};
const hiView={name:'hi',tasks:[hi]},hiOriginal=JSON.stringify(hiView),hiHost=node('main');
root.RelayWorkflow.mount(hiHost,hiView,options);
assert.equal(walk(hiHost,'canvas-node-title')[0].children[0].textContent,'AI model');
assert.equal(walk(hiHost,'canvas-model')[0].textContent,'Codex · gpt-6.1-sol');
assert.equal(walk(hiHost,'canvas-attempts')[0].textContent,'1/2 attempts');
assert.equal(walk(hiHost,'canvas-prompt')[0].children[1].textContent,hi.objective);
walk(hiHost,'workflow-step')[0].onclick();
assert(walk(hiHost,'workflow-instruction').some(e=>e.textContent===hi.objective));
assert.equal(JSON.stringify(hiView),hiOriginal,'displaying the prompt never rewrites the saved assignment');
const draftHost=node('main');
root.RelayWorkflow.mount(draftHost,{name:'image-draft',tasks:[{id:'image',operation:'gemini.image',objective:'Gemini · image',prompt:'A cup',backend:{model:'fixture-image'},status:'draft'}]},options);
assert.equal(walk(draftHost,'canvas-model')[0].textContent,'Gemini · fixture-image');
assert.equal(walk(draftHost,'canvas-attempts').length,0,'a draft has no invented attempt grant');
const source={node:{id:'saved-source',run:'original',objective:'Red cup',operation:'gemini.image',status:'completed',reused_source:true,planned_outputs:[{path:'outputs/result.png'}]},file:{id:'cup',task:'saved-source',path:'outputs/result.png',sha256:'red'}};
const continued={tasks:[{id:'adjust',objective:'Blue cup',planned_inputs:[{path:'input.png',artifact:'cup',sha256:'red'}]}],completed_sources:[source],latest_outputs:[]};
const unchanged=JSON.stringify(continued),projected=root.RelayWorkflow.withCompletedSources(continued);
assert.equal(projected.tasks.length,2);
assert.equal(root.RelayWorkflow.canvasEdges(projected.tasks)[0].from,'saved-source');
assert.equal(projected.latest_outputs[0].sha256,'red');
assert.equal(JSON.stringify(continued),unchanged,'source projection does not change current delivery or execution records');
continued.tasks[0].planned_inputs[0].sha256='different';
assert.equal(root.RelayWorkflow.canvasEdges(root.RelayWorkflow.withCompletedSources(continued).tasks).length,0,'wrong version cannot invent a wire');
console.log('Canvas passed: exact file inspection, distinct binding/prerequisite wires, drag vs click, pan/zoom, refresh retention, cleanup and no workflow mutation.');

const imagePorts=root.RelayWorkflow.taskPorts({operation:'gemini.image',planned_inputs:[{path:'inputs/original/result.png'}],planned_outputs:[{path:'outputs/result.png',media_type:'image/png'}]});
assert.equal(imagePorts.inputs[0].label,'Reference image');assert.equal(imagePorts.outputs[0].label,'Generated image');
const nativeOutputs=[
  {path:'delivery/scene.blend',purpose:'Registered operation output',label:'Blender model'},
  {path:'delivery/preview.png',media_type:'image/png',purpose:'Registered operation output',label:'Render preview'}
];
const nativePorts=root.RelayWorkflow.taskPorts({planned_outputs:nativeOutputs}).outputs;
assert.equal(nativePorts[0].label,'Blender model');assert.equal(nativePorts[1].label,'Render preview');
assert.equal(nativePorts[0].id,'delivery/scene.blend');assert.equal(nativePorts[1].id,'delivery/preview.png');
const namedEdges=root.RelayWorkflow.canvasEdges([
  {id:'model',dependencies:[],planned_outputs:nativeOutputs},
  {id:'consumer',dependencies:[],planned_inputs:[{path:'reference',from_task:'model',output:'delivery/preview.png'}]}
]);
assert.equal(namedEdges[0].output,'delivery/preview.png');assert.equal(namedEdges[0].input,'reference');
const realFrozen={...continued,tasks:[{id:'adjust',planned_inputs:[{path:'inputs/cup/result.png',artifact:'cup'}],recorded_inputs:[{path:'inputs/cup/result.png',artifact:'cup',sha256:'red'}]}]};
const wired=root.RelayWorkflow.withCompletedSources(realFrozen);assert.equal(root.RelayWorkflow.canvasEdges(wired.tasks).length,1);assert.equal(root.RelayWorkflow.layout(wired.tasks).layers.length,2);

const runs=[];
for(const [state,label,busy] of [['draft','Not run',false],['queued','Waiting for inputs',true],['launching','Starting',true],['running','Running',true],['settling','Finishing',true],['completed','Completed',false],['blocked','Blocked',false],['uncertain','Needs attention · outcome unknown',true]]){
 const h=node('main');root.RelayWorkflow.mount(h,{name:'state-'+state,tasks:[{...hi,status:state}]},{...options,runNode:t=>runs.push(t.id)});
 assert.equal(walk(h,'canvas-node-state')[0].children.at(-1).textContent,label);
 assert.equal(walk(h,'canvas-node-run')[0].disabled,busy);
 if(state==='completed')walk(h,'canvas-node-run')[0].onclick();
}
assert.deepEqual(runs,['hi']);
const pendingElsewhere=node('main');
root.RelayWorkflow.mount(pendingElsewhere,{name:'removed-running-node',tasks:[{...hi,status:'completed'}],executing_runs:['active-version']},{...options,runNode:()=>{}});
assert.equal(walk(pendingElsewhere,'canvas-node-run')[0].disabled,true,'an active version outside current nodes still disables Run');

// Failures are visible directly on the node, with no automatic retry or fabricated detail.
for (const state of ['uncertain','blocked','completed']) {
 const h=node('main'),error='Gemini request failed (connection-or-response)\nOutcome remains unknown. No automatic retry.';
 const data={name:'failure-'+state,tasks:[{...hi,status:state,error}]},before=JSON.stringify(data);
 root.RelayWorkflow.mount(h,data,{...options,runNode:()=>{throw Error('No dispatch from display');}});
 assert.equal(walk(h,'canvas-node-error').length,state==='completed'?0:1);
 if(state!=='completed')assert.equal(walk(h,'canvas-node-error')[0].textContent,error);
 if(state==='uncertain')assert.equal(walk(h,'canvas-node-run')[0].disabled,true);
 assert.equal(JSON.stringify(data),before);
}

const allowedUnknown=node('main');
root.RelayWorkflow.mount(allowedUnknown,{name:'explicit-new',tasks:[{...hi,status:'uncertain',can_start_new_attempt:true}]},{...options,runNode:()=>{}});
assert.equal(walk(allowedUnknown,'canvas-node-run')[0].disabled,false);
assert.match(walk(allowedUnknown,'canvas-node-run')[0].title,/separate new attempt/);
const runningUnknown=node('main');
root.RelayWorkflow.mount(runningUnknown,{name:'still-running',tasks:[{...hi,status:'uncertain',can_start_new_attempt:true}],executing_runs:['busy']},{...options,runNode:()=>{}});
assert.equal(walk(runningUnknown,'canvas-node-run')[0].disabled,true);

// Quick-open targets each exact current output, independent of inspector selection.
(async()=>{
 const quickHost=node('main'),opened=[],chosen=[];
 const output={id:'exact-answer',task:'answer',path:'delivery/answer.md',output_port:'answer',sha256:'exact'};
 const quickView={name:'quick-open',tasks:[{id:'answer',status:'completed',planned_inputs:[{path:'source'}],planned_outputs:[{path:'answer',output_port:'answer',label:'Research answer'},{path:'missing',output_port:'missing',label:'Missing file'}]}],latest_outputs:[output],historical_outputs:[{...output,id:'old',sha256:'old'}]};
 const savedView=JSON.stringify(quickView);
 root.RelayWorkflow.mount(quickHost,quickView,{...options,select:id=>chosen.push(id),openOutput:async f=>opened.push(f)});
 const icons=walk(quickHost,'canvas-output-open');assert.equal(icons.length,1);
 assert.equal(icons[0].attributes['aria-label'],'Open Research answer');
 let stopped=0;await icons[0].onclick({stopPropagation(){stopped++;},preventDefault(){}});
 assert.equal(stopped,1);assert.equal(opened[0].id,output.id);assert.equal(opened[0].sha256,output.sha256);assert.equal(chosen.length,0);
 assert.equal(JSON.stringify(quickView),savedView);
 const ambiguous=node('main');root.RelayWorkflow.mount(ambiguous,{...quickView,name:'ambiguous',latest_outputs:[output,{...output,id:'another'}]}, {...options,openOutput:()=>assert.fail('Ambiguous output')});
 assert.equal(walk(ambiguous,'canvas-output-open').length,0);
 const pathHost=node('main');root.RelayWorkflow.mount(pathHost,{...quickView,name:'paths',tasks:[{id:'answer',planned_outputs:[{path:output.path,label:'Answer'}]}]}, {...options,openOutput:()=>{}});
 assert.equal(walk(pathHost,'canvas-output-open').length,1,'legacy exact paths stay usable');
 console.log('Quick-open exact ports, ambiguity, unavailable files, selection and history checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
