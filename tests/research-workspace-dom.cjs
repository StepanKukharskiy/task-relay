// Controlled UI: source visibility, optional planning and unchanged retry identity.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ids=new Map();
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.attributes={};this.classList={toggle(){},add(){},remove(){}};}
  append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this.append(...children);}
  setAttribute(name,value){this.attributes[name]=value;}
  removeAttribute(name){delete this.attributes[name];}
  addEventListener(){}
  focus(){document.activeElement=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);}
  querySelector(tag){return walk(this).find(child=>child!==this && child.tagName===tag) || null;}
}
function walk(element){return [element,...element.children.flatMap(walk)];}
const document={activeElement:null,hidden:false,querySelectorAll:()=>[],createElement:tag=>new Element(tag),getElementById:id=>{
  if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);
}};
const calls=[],drafts=new Map();let lostReply=true;
const plan={id:'plan-one',channel:'desktop',status:'started',run:'run-one',request:'Any ideas for an old controller?',project:null};
const view={name:'run-one',brief:plan.request,channel:'desktop',status:'completed',local:true,tasks:[],controls:[],latest_outputs:[],research:{steps:[],files:[],pages:[],message:'No successful page read or search result is recorded for this job.'}};
const window={__TAURI__:{core:{invoke:async(command,args)=>{
  calls.push({command,args});
  if(command==='workspace_open_source')return;
  const {path,value}=args;
  if(path==='workspace-jobs')return {items:[{id:plan.id,kind:'plan',title:plan.request,status:'completed',channel:'desktop'}],scope:'fixture',can_plan:true,total:1,next_offset:null};
  if(path==='workspace-plan')return plan;
  if(path==='workspace-detail')return view;
  if(path==='plan-create') {if(lostReply){lostReply=false;throw Error('Response lost');}return {message:'Saved',plan_id:plan.id};}
  if(path==='workspace-request')return {plan_id:plan.id};
  throw Error('Unexpected request '+path);
}}},RelayWorkflow:{resultFiles:()=>({primary:[],other:[]}),mount:()=>()=>{}},scrollTo(){}};
const context=vm.createContext({window,document,localStorage:{getItem:key=>drafts.get(key)||null,setItem:(key,value)=>drafts.set(key,value),removeItem:key=>drafts.delete(key)},crypto:{randomUUID:()=> 'fixture-identity'},setInterval:()=>0,console});
vm.runInContext(fs.readFileSync('task_relay/assets/companion-workspace.js','utf8'),context);
(async()=>{
  await window.RelayWorkspace.refreshJobs();
  await document.getElementById('workspace-job-list').children[0].onclick();
  let body=document.getElementById('workspace-detail-body');
  assert(walk(body).some(e=>e.textContent==='No successful page read or search result is recorded for this job.'));
  const researchButton=walk(body).find(e=>e.textContent==='Plan a source-backed answer');assert(researchButton);
  const before=calls.length;researchButton.onclick();assert.equal(calls.length,before,'The choice opens a draft without submitting or dispatching');
  assert.equal(document.getElementById('workspace-goal').value,plan.request);
  await document.getElementById('workspace-create-form').onsubmit({preventDefault(){}});
  assert.equal(drafts.size,1,'An unconfirmed request keeps its exact draft');
  document.getElementById('workspace-goal').value='A different pending request';
  await document.getElementById('workspace-create-form').onsubmit({preventDefault(){}});
  assert.equal(calls.filter(c=>c.args?.path==='plan-create').length,1,'Changing a pending request cannot resubmit');
  document.getElementById('workspace-goal').value=plan.request;
  await document.getElementById('workspace-create-form').onsubmit({preventDefault(){}});
  const submits=calls.filter(c=>c.args?.path==='plan-create');assert.deepEqual(submits[0].args.value,submits[1].args.value);
  assert.equal(submits[0].args.value.research_mode,'sources','A selected recommendation retains the explicit choice without a dropdown');
  assert.equal(drafts.size,0,'A committed receipt clears the pending draft');
  async function refresh(){document.getElementById('workspace-detail-refresh').onclick();await new Promise(resolve=>setImmediate(resolve));body=document.getElementById('workspace-detail-body');}
  plan.research_advice={recommended_mode:'none',requirement:'optional',reason:'Explore reuse ideas; documentation can establish supported link interfaces.',questions:['Which existing projects support the link interface?']};
  await refresh();
  assert(walk(body).some(e=>e.textContent==='Orchestrator recommends a quick answer'));
  assert(walk(body).some(e=>e.textContent===plan.research_advice.reason));
  assert(walk(body).some(e=>e.tagName==='li'&&e.textContent===plan.research_advice.questions[0]));
  assert(walk(body).some(e=>e.textContent==='Plan a source-backed answer'));
  plan.research_advice={recommended_mode:'none',requirement:'unnecessary',reason:'This poem needs creative writing, with no factual lookup.',questions:[]};
  await refresh();assert(!walk(body).some(e=>e.textContent==='Plan a source-backed answer'));
  plan.research_advice={recommended_mode:'sources',requirement:'optional',reason:'Compatibility checks would help select projects.',questions:['Which projects are compatible?']};
  await refresh();const quick=walk(body).find(e=>e.textContent==='Plan a quick answer');assert(quick);
  const quickBefore=calls.length;quick.onclick();assert.equal(calls.length,quickBefore);assert.equal(document.getElementById('workspace-goal').value,plan.request);
  plan.research_advice.requirement='required';await refresh();assert(!walk(body).some(e=>e.textContent==='Plan a quick answer'));
  delete plan.research_advice;
  view.research={steps:[],files:[],pages:[{id:'receipt-id',url:'https://docs.example/spec',title:'Specification',kind:'page'},{id:'search-id',url:'https://docs.example/search',title:'Search only',kind:'search_result'}],message:'Recorded web sources are listed below.'};
  await document.getElementById('workspace-detail-refresh').onclick();
  await new Promise(resolve=>setImmediate(resolve));
  body=document.getElementById('workspace-detail-body');
  const link=walk(body).find(e=>e.tagName==='a'&&e.href==='https://docs.example/spec');assert(link);
  assert(walk(body).some(e=>e.textContent.includes('Search result · page read not recorded')));
  assert(!walk(body).some(e=>e.textContent==='Plan a source-backed answer'));
  await link.onclick({preventDefault(){},stopPropagation(){}});
  const opened=calls.find(c=>c.command==='workspace_open_source');assert.equal(opened.args.run,'run-one');assert.equal(opened.args.source,'receipt-id');
  assert(!calls.some(c=>['plan-decide','workspace-decide'].includes(c.args?.path)),'No Start, user acceptance or old-run mutation');
  console.log('Research advice UI passed: contextual recommendations, alternatives without dispatch, no-source visibility, separate draft, exact retry and receipt-bound source links.');
})().catch(error=>{console.error(error);process.exitCode=1;});
