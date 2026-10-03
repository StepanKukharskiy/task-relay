// Saved chat projection, request drafting and receipt-bound source opening.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
assert(!fs.readFileSync('task_relay/assets/companion.html','utf8').includes('id="workspace-research"'),'There is no research dropdown');
const ids=new Map(),calls=[],storage=new Map();
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.attributes={};this.classList={toggle(){},add(){},remove(){}};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(name,value){this.attributes[name]=value;}
  removeAttribute(name){delete this.attributes[name];}
  addEventListener(){}
  focus(){document.activeElement=this;}
  querySelector(tag){return walk(this).find(e=>e!==this&&e.tagName===tag)||null;}
}
function walk(element){return [element,...element.children.flatMap(walk)];}
const document={activeElement:null,hidden:false,querySelectorAll:()=>[],createElement:tag=>new Element(tag),getElementById:id=>{
  assert(!id.startsWith('workspace-research'),'The UI must not depend on the removed dropdown');
  if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);
}};
const view={id:1,prompt:'Any reuse ideas for a controller?',answer:'Exact saved Telegram answer.\nSecond paragraph.\nSaved metadata.',display_answer:'Exact saved Telegram answer.\nSecond paragraph.',source_summary:{visible:true,label:'Sources: 1 page read'},research_advice:{reason:'Read the interface documentation.',questions:['What interfaces are supported?']},status:'answered',channel:'telegram',can_continue:false,
  option_digests:['b'.repeat(64)],next_options:[{title:'Prototype the UI',outcome:'A local text UI before hardware work.',request:'Prepare a local UI prototype plan.',tools:['graph_executors:codex-cli']}],
  evidence:{sources:[{url:'https://docs.example/spec',kind:'page'}],partial:false}};
const window={__TAURI__:{core:{invoke:async(command,args)=>{
  calls.push({command,args});
  if(command==='workspace_open_chat_source'||command==='companion_open')return;
  const {path}=args;
  if(path==='conversation-delete-preview')return {id:String(view.id),title:view.prompt,digest:'a'.repeat(64),trace_files:1,blockers:[]};
  if(path==='conversation-delete')return {id:String(view.id),status:'complete'};
  if(path==='workspace-jobs')return {items:[{id:'1',kind:'chat',title:view.prompt,status:'answered',channel:view.channel}],can_plan:true,scope:'fixture',total:1,next_offset:null};
  if(path==='workspace-chat')return view;
  if(path==='conversation-followup')return {root_id:'1',request_id:'fixture-identity',mode:'plan',status:'queued'};
  if(path==='plan-create')return {message:'Saved'};
  if(path==='workspace-request')return {conversation:view};
  throw Error('Unexpected route '+path);
}}},RelaySavedWork:{confirm:async()=>false},scrollTo(){}};
const context=vm.createContext({window,document,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},crypto:{randomUUID:()=> 'fixture-identity'},setInterval:()=>0,console});
vm.runInContext(fs.readFileSync('task_relay/assets/companion-workspace.js','utf8'),context);
(async()=>{
  await window.RelayWorkspace.refreshJobs();await document.getElementById('workspace-job-list').children[0].onclick();
  let body=document.getElementById('workspace-detail-body');
  assert(walk(body).some(e=>e.className==='conversation-answer'&&e.textContent===view.display_answer),'Display the receipt-backed conversational body');
  assert(walk(body).some(e=>e.tagName==='pre'&&e.textContent===view.answer),'Preserve the exact saved reply in details');
  assert(walk(body).some(e=>e.tagName==='details'&&e.className==='conversation-sources'&&!e.open),'Keep provenance collapsed');
  assert(!walk(body).some(e=>e.tagName==='button'&&e.textContent===view.next_options[0].title),'Messenger choices keep their original conversation');
  const link=walk(body).find(e=>e.tagName==='a');let stopped=false;await link.onclick({preventDefault(){},stopPropagation(){stopped=true;}});assert(stopped,'Receipt-bound links do not bubble into the generic setup opener');
  const opened=calls.find(c=>c.command==='workspace_open_chat_source').args;
  assert.equal(opened.id,'1');assert.equal(opened.url,'https://docs.example/spec');
  view.channel='desktop';view.can_continue=true;view.can_delete=true;
  view.project='/fixture/project';view.files=['/fixture/frozen/input.txt'];
  document.getElementById('workspace-detail-refresh').onclick();await new Promise(resolve=>setImmediate(resolve));
  body=document.getElementById('workspace-detail-body');
  const remove=walk(body).find(e=>e.textContent==='Delete conversation…');assert(remove,'Completed Desktop conversations expose Delete');
  await remove.onclick();assert.equal(calls.filter(c=>c.args.path==='conversation-delete').length,0,'Cancel does not delete local history');
  const prepare=walk(body).find(e=>e.tagName==='button'&&e.textContent===view.next_options[0].title);assert(prepare);
  await prepare.onclick();
  const sent=calls.find(c=>c.args.path==='conversation-followup');assert(sent);
  assert.equal(sent.args.value.id,'1');assert.equal(sent.args.value.index,0);assert.equal(sent.args.value.digest,'b'.repeat(64));
  assert(!calls.some(c=>c.args.path==='plan-create'),'Choosing an outcome queues its saved data without a blank form');
  assert.equal(storage.size,0,'Only a known saved receipt clears the request identity');
  assert.equal(body.children.at(-1).children[0].textContent,'Conversation history','Deletion is below the answer and workflow');
  window.RelayWorkspace.newTask({goal:'A new ordinary question.'});
  await document.getElementById('workspace-create-form').onsubmit({preventDefault(){}});
  assert.equal(calls.filter(c=>c.args.path==='plan-create').at(-1).args.value.entry_mode,'conversation','Ordinary questions stay conversational');
  window.RelayWorkspace.newTask({parent_id:'plan-existing',goal:'Revise the original plan.'});
  await document.getElementById('workspace-create-form').onsubmit({preventDefault(){}});
  const revision=calls.filter(c=>c.args.path==='plan-create').at(-1);assert.equal(revision.args.value.entry_mode,'plan');assert.equal(revision.args.value.parent_id,'plan-existing');
  window.RelaySavedWork.confirm=async()=>true;
  await remove.onclick();
  const deleted=calls.find(c=>c.args.path==='conversation-delete');assert.equal(deleted.args.value.id,'1');assert.equal(deleted.args.value.digest,'a'.repeat(64));
  console.log('Shared orchestrator UI passed: exact saved reply, original channel, source receipt, attached option selection, secondary Delete and revision scope.');
})().catch(error=>{console.error(error);process.exitCode=1;});
