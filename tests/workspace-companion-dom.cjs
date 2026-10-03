// Regression for a polling refresh invalidating an unchanged focused job row.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const ids=new Map();
const document={activeElement:null,hidden:false,querySelectorAll:()=>[],createElement:tag=>new Element(tag),getElementById:id=>{
  if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);
}};
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.value='';this.attributes={};this.classList={toggle(){},add(){},remove(){}};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){if(this.children.includes(document.activeElement))document.activeElement=null;this.children=children;}
  setAttribute(name,value){this.attributes[name]=value;}
  addEventListener(){}
  focus(){document.activeElement=this;}
}
let stamp=0;
const items=[{id:'one',kind:'run',title:'Same request',status:'cancelled',channel:'desktop'},
  {id:'two',kind:'run',title:'Same request',status:'cancelled',channel:'desktop'}];
const window={__TAURI__:{core:{invoke:async(command,{path})=>{
  assert.equal(path,'workspace-jobs');return {items:items.map(item=>({...item,stamp:++stamp})),scope:'fixture',can_plan:true,total:2,next_offset:null};
}}},scrollTo(){}};
const context=vm.createContext({window,document,localStorage:{getItem:()=>null},setInterval:()=>0,console});
vm.runInContext(fs.readFileSync('task_relay/assets/companion-workspace.js','utf8'),context);
(async()=>{
  await window.RelayWorkspace.refreshJobs();
  const list=document.getElementById('workspace-job-list'), row=list.children[0];row.focus();
  assert.notEqual(row.attributes['aria-label'],list.children[1].attributes['aria-label']);
  await window.RelayWorkspace.refreshJobs();
  assert.equal(list.children[0],row,'An updated timestamp must not invalidate an unchanged row');
  assert.equal(document.activeElement,row,'Polling must retain keyboard focus');
  items[0].status='completed';await window.RelayWorkspace.refreshJobs();
  assert.notEqual(list.children[0],row,'A changed status must still update the list');
  assert.match(list.children[0].attributes['aria-label'],/Completed/);
  console.log('Workspace polling passed: focused rows survive unchanged reads and duplicate titles remain distinguishable.');
})().catch(error=>{console.error(error);process.exitCode=1;});
