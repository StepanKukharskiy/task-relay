// Parent job navigation, whole-history statistics and exact deletion confirmation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ids=new Map();
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.value='';this.attributes={};this.classList={toggle(){},add(){},remove(){}};this._text='';}
  get textContent(){return this._text+this.children.map(c=>c.textContent || '').join(' ');}
  set textContent(value){this._text=String(value);}
  append(...children){this.children.push(...children);}
  insertBefore(n,b){const i=this.children.indexOf(b);this.children.splice(i<0?this.children.length:i,0,n);}
  replaceChildren(...children){this.children=children;this._text='';}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(){}
  querySelector(){return null;}
  focus(){}
}
const document={hidden:false,querySelectorAll:()=>[],createElement:t=>new Element(t),getElementById:id=>{
  if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);
}};
const item={id:'parent',kind:'pipeline',title:'One completed job',status:'completed',channel:'desktop'};
const view={...item,request:'Exact objective',stats:{stages:2,stages_completed:2,tasks:2,tasks_completed:2,workers_created:4,reviewers_created:2,operations_started:1,running:0,uncertain:0,runs:2},
  usage:{elapsed_seconds:120,totals:{total_tokens:{reported:100,unknown_records:1}}},outputs:[],plans:[],
  stages:[{id:'make',status:'completed',run:'latest',tasks:[{id:'author',status:'completed',attempts:1,backend:{type:'api',model:'fixture'}},{id:'check',status:'completed',attempts:1,review_of:'author',backend:{type:'api',model:'fixture'}}]}],
  attempts:[{id:'old',task:'check',state:'blocked',reviewer:true,current:false,run:'old-run',backend:{model:'fixture'},error:'Earlier rejected candidate'}]};
let approved=false,confirmed=0,deleted=0,blockers=[];const calls=[];
const window={__TAURI__:{core:{invoke:async(command,{path,value})=>{
  calls.push({path,value});
  if(path==='workspace-jobs')return {items:[item],total:1,next_offset:null,can_plan:true,scope:'fixture',review_total:1,review_items:[{id:'older',kind:'pipeline',title:'Older job',status:'blocked'}]};
  if(path==='workspace-detail'){assert.deepEqual(JSON.parse(JSON.stringify(value)),{pipeline:'parent'});return view;}
  if(path==='job-delete-preview')return {id:'parent',title:item.title,digest:'exact-reviewed-digest',counts:{attempts:5},plans:['a'],runs:['old','new'],blockers};
  if(path==='job-delete'){assert.equal(value.digest,'exact-reviewed-digest');deleted++;return {status:'complete'};}
  throw Error('Unexpected request '+path);
}}},scrollTo(){},RelaySavedWork:{confirm:async()=>{confirmed++;return approved;}}};
const context=vm.createContext({window,document,localStorage:{getItem:()=>null},setInterval:()=>0,console});
vm.runInContext(fs.readFileSync('task_relay/assets/companion-workspace.js','utf8'),context);
function descendants(n){return [n,...n.children.flatMap(descendants)];}
(async()=>{
  await window.RelayWorkspace.refreshJobs();
  assert.match(document.getElementById('workspace-review-list').textContent,/Older job/);
  assert.equal(document.getElementById('workspace-review-count').textContent,'1');
  await document.getElementById('workspace-job-list').children[0].onclick();
  const body=document.getElementById('workspace-detail-body');
  assert.match(body.textContent,/2 producer attempts · 2 reviewer attempts/);
  assert.match(body.textContent,/Reviewer of Author/);
  assert.match(body.textContent,/Completed. No workers running./);
  assert.equal(descendants(body).find(e=>e.tagName==='details' && e.children[0]?.textContent==='Make · Completed · 2\/2 tasks').open,false);
  assert.match(body.textContent,/Earlier run/);
  assert.match(body.textContent,/1 unknown usage records/);
  view.status='active';view.activity={controller_fresh:true,attempts:[{task:'check',reviewer:true,state:'running',current:true}]};
  await document.getElementById('workspace-job-list').children[0].onclick();
  assert.match(body.textContent,/Check · Reviewer · In progress/);
  assert.doesNotMatch(body.textContent,/No workers running/);
  view.activity={controller_fresh:false,attempts:[]};
  await document.getElementById('workspace-job-list').children[0].onclick();
  assert.match(body.textContent,/No worker is currently running/);
  assert.match(body.textContent,/Controller health is stale or unavailable/);
  const savedStages=view.stages;
  view.status='blocked';view.activity={controller_fresh:true,attempts:[]};
  const internal='Required correction workload exceeds the existing recovery allocation. Partition the work or review its authorization before dispatch.';
  view.stages=[{id:'deck',status:'blocked',tasks:[],error:internal,lifecycle:{phase:'held',recovery_code:'capacity_exhausted',reason:internal,next_action:'partition_or_review_authorization',remaining_recovery_cycles:4}}];
  await document.getElementById('workspace-job-list').children[0].onclick();
  const visible=e=>e.tagName==='details' && !e.open ? e.children[0]?.textContent || '' : e._text+' '+e.children.map(visible).join(' ');
  descendants(body).find(e=>e.className==='job-diagnostics').open=true;
  assert.match(visible(body),/Presentation paused. Your completed work is saved./);
  assert.match(visible(body),/couldn't start a required correction/);
  assert.doesNotMatch(visible(body),/Partition the work|recovery allocation|Recovery action|No workers running|cycles remaining/);
  assert.match(body.textContent,/Partition the work/,'Exact diagnostics must remain available');
  assert.ok(descendants(body).some(e=>e.tagName==='details' && e.children[0]?.textContent==='Technical details' && !e.open));
  view.status='active';view.stages[0].status='running';view.stages[0].error=null;
  view.stages[0].lifecycle={phase:'executing',reason:'Correcting exact candidate',next_action:'observe_receipt'};
  view.activity.attempts=[{task:'correct',reviewer:false,state:'running',current:true}];
  await document.getElementById('workspace-job-list').children[0].onclick();
  descendants(body).find(e=>e.className==='job-diagnostics').open=true;
  assert.match(visible(body),/Correct · Worker · In progress/);
  assert.doesNotMatch(visible(body),/Presentation paused|couldn't start/);
  view.stages=savedStages;
  view.status='completed';view.activity={controller_fresh:true,attempts:[]};
  await document.getElementById('workspace-job-list').children[0].onclick();
  view.coverage={shortfall:[{item:'sofa'},{item:'sofa'}],unresolved_items:['sofa']};
  await document.getElementById('workspace-job-list').children[0].onclick();
  assert.match(document.getElementById('workspace-detail-meta').textContent,/Completed with coverage gaps/);
  assert.match(body.textContent,/1 items below the requested option count; 1 with no options/);
  const remove=descendants(body).find(e=>e.tagName==='button' && e.textContent==='Delete job…');assert.ok(remove);
  await remove.onclick();assert.equal(confirmed,1);assert.equal(deleted,0,'Cancelled confirmation cannot delete');
  blockers=['Uncertain worker outcome'];approved=true;await remove.onclick();assert.equal(confirmed,1);assert.equal(deleted,0,'A blocked preview cannot reach confirmation or deletion');
  blockers=[];await remove.onclick();assert.equal(confirmed,2);assert.equal(deleted,1);
  console.log('Parent navigation, whole-job stats, off-page reviews and exact deletion confirmation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
