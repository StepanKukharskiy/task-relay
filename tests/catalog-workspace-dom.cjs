// Exercise the actual workspace view with the registered catalog projection.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const rows=JSON.parse(fs.readFileSync(process.argv[2],'utf8')).operations;
const ids=new Map(),calls=[];let hold=null,fail=false;
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.checked=false;this.classList={toggle(){},add(){},remove(){}};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(){} addEventListener(){} querySelector(){return null;}
}
const document={hidden:false,querySelectorAll:()=>[],createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),getElementById:id=>{if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);}};
const $=document.getElementById;
const window={scrollTo(){},__TAURI__:{core:{invoke:async(_,request)=>{
  calls.push(request);
  if(request.path==='workspace-jobs')return {items:[],scope:'fixture',can_plan:false,total:0,next_offset:null};
  assert.equal(request.path,'node-catalog','Catalog must not execute or mutate');
  if(fail)throw Error('fixture failure');
  if(hold)return new Promise(resolve=>hold.push(resolve));
  return {operations:rows.filter(r=>request.value.include_legacy || !r.legacy),execution_authorized:false};
}}}};
vm.runInNewContext(fs.readFileSync('task_relay/assets/companion-workflow.js','utf8'),{window,document});
vm.runInNewContext(fs.readFileSync('task_relay/assets/companion-workspace.js','utf8'),{window,document,localStorage:{getItem:()=>null},setInterval(){},console});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const text=e=>e.textContent+e.children.map(text).join('\n');
(async()=>{
 window.RelayWorkspace.navigate('catalog');await settle();
 assert.equal($('workspace-catalog-list').children.length,58);
 $('workspace-catalog-search').value='images.crop';$('workspace-catalog-search').oninput();
 assert.equal($('workspace-catalog-list').children.length,1);assert.match(text($('workspace-catalog-list')),/Source image/);assert.match(text($('workspace-catalog-list')),/Cropped image/);
 $('workspace-catalog-search').value='collection.subjects';$('workspace-catalog-search').oninput();assert.doesNotMatch(text($('workspace-catalog-list')),/"baseline"/);
 $('workspace-catalog-search').value='sourcing.merge';$('workspace-catalog-search').oninput();assert.match(text($('workspace-catalog-list')),/No matching/);
 // Historical definitions must stay absent even if a stale response includes them.
 hold=[];window.RelayWorkspace.navigate('catalog');const pending=hold;hold=null;
 window.RelayWorkspace.navigate('catalog');await settle();pending[0]({operations:rows});await settle();assert.match(text($('workspace-catalog-list')),/No matching/);
 assert(calls.filter(c=>c.path==='node-catalog').every(c=>c.value.include_legacy===false));
 fail=true;window.RelayWorkspace.navigate('catalog');await settle();assert.match($('workspace-catalog-status').textContent,/fixture failure/);assert.equal($('workspace-catalog-list').children.length,0);
 assert(calls.every(c=>['workspace-jobs','node-catalog'].includes(c.path)));
 console.log('Catalog UI passed: registered ports, legacy filtering, unsupported baseline omission, stale response and failure handling; read-only requests.');
})().catch(error=>{console.error(error);process.exitCode=1;});
