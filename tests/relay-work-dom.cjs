// Controlled MCP host: review cancellation, stale state, provenance and safe rendering.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.textContent='';this.value='';this.attributes={};this.hidden=false;}
  append(...v){this.children.push(...v);}
  replaceChildren(...v){this.children=v;}
  setAttribute(k,v){this.attributes[k]=v;}
}
const ids=new Map();
const document={getElementById:id=>{if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);},createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),querySelectorAll:()=>[...ids.values()]};
let handler,requests=[],packetChecks=0,commits=0,failPacket=false;
const work={project:{id:'work:fixture',title:'Guide',revision:1,request:'Make a guide'},decisions:[],decision_history:[],execution_records:[],proposals:[],topics:['Guide'],open_issues:[{id:'held',title:'Citation held for review',authority:'imported_proposal',data:{text:JSON.stringify({claim:{statement:'A reported result'},reason:'Quotation is not exact'}),basis:'failed_citation_check',topics:[]}}],artifacts:[{id:'v1',title:'<img src=x onerror=alert(1)>',selected:false,newest_recorded:true,freshness:'unknown',data:{version:1,path:'guide.md',topics:['Guide']}}],limitations:['Fixture scope']};
let remembered=null;
const window={openai:{widgetState:{project_id:work.project.id,view:'current',topic:'',capture_packet_id:'packet:previous'},setWidgetState(value){remembered=value;}},parent:{postMessage(m){
  requests.push(m);
  if(!m.id)return;
  let result={};
  if(m.method==='tools/call'){
    const {name,arguments:a}=m.params;
    if(name==='relay_list_work')result={structuredContent:{projects:[{id:work.project.id,title:work.project.title}]}};
    else if(name==='relay_open_work')result={structuredContent:{work:structuredClone(work)}};
    else if(name==='relay_prepare_change')result={structuredContent:{review:{review_id:'review:fixture',project_id:work.project.id,revision:1,request:a.request,change:a.change}},_meta:{confirmation_token:'fixture-control'}};
    else if(name==='relay_commit_change'){commits++;result={structuredContent:{work:structuredClone({...work,project:{...work.project,revision:2}})}};}
    else if(name==='relay_prepare_continuation')result={structuredContent:{packet_id:'packet:fixture',sha256:'fixture-hash',packet:{project:work.project,decisions:[],selected_artifacts:[],open_issues:[]}}};
    else if(name==='relay_validate_continuation'){packetChecks++;result=failPacket?{isError:true,content:[{type:'text',text:'Continuation is stale'}]}:{structuredContent:{packet_id:'packet:fixture',sha256:'fixture-hash',packet:{project:work.project,decisions:[],selected_artifacts:[],open_issues:[]}}};}
    else if(name==='relay_provenance')result={structuredContent:{record:{id:'v1',title:work.artifacts[0].title},sources:[]}};
    else if(name==='relay_work_graph')result={structuredContent:{graph:{project_id:a.project_id,revision:1,nodes:[...Array.from({length:45},(_,i)=>({id:'source:'+i,kind:'evidence',title:i===0?'<script>source</script>':'Source '+i,topics:['Guide'],authority:'imported_proposal'})),{id:'v1',kind:'artifact',title:'Guide',topics:['Guide'],authority:'imported_proposal'}],edges:[{source:'v1',target:'source:0',relation:'cites',basis:'imported_proposal'}]}}};
    else if(name==='relay_prepare_understanding')result={structuredContent:{input_id:'understanding:fixture',sha256:'fixture-hash',input:{project:work.project,sources:[],coverage:{selected_records:0}}}};
    else throw Error('Unexpected '+name);
  }
  queueMicrotask(()=>handler({source:window.parent,data:{jsonrpc:'2.0',id:m.id,result}}));
}},addEventListener(type,fn){if(type==='message')handler=fn;}};
const context=vm.createContext({window,document,console,setTimeout,clearTimeout,Map,JSON,Error,crypto:require('node:crypto').webcrypto});
vm.runInContext(fs.readFileSync('task_relay/assets/relay-work.js','utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r));
const walk=e=>[e,...e.children.flatMap(walk)];
(async()=>{
  await flush();
  await flush();
  assert.equal(ids.get('work').hidden,false,'Reopening fetches fresh work from the authorized project list');
  assert.equal(ids.get('capture-packet').value,'packet:previous','Optional host state restores only the capture identity');
  assert.deepEqual(Object.keys(remembered).sort(),['capture_packet_id','project_id','topic','view'],'Widget state excludes source data, draft text and review controls');
  window.openai.setWidgetState=()=>{throw Error('Optional host persistence unavailable');};
  handler({source:window.parent,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{work:structuredClone(work),review:{review_id:'review:initial',project_id:work.project.id,revision:1,request:'Select v1',change:{action:'select_artifact',target:'v1'}}},_meta:{confirmation_token:'fixture-initial'}}}});
  assert.equal(ids.get('work').hidden,false,'Model-initiated review opens its work in a fresh widget');
  assert.equal(ids.get('review').hidden,false);ids.get('cancel-change').onclick();
  await ids.get('projects').children[0].onclick();
  assert(walk(ids.get('artifacts')).some(e=>e.textContent===work.artifacts[0].title),'Untrusted titles render as text');
  assert(!walk(ids.get('artifacts')).some(e=>e.tagName==='img'),'No source HTML executes');
  assert(walk(ids.get('held-issues')).some(e=>e.textContent==='A reported result'),'Held citation claims have a readable inspection view');
  assert(!walk(ids.get('issues')).some(e=>e.textContent.includes('Quotation')),'Evidence failures are not displayed as project questions');
  assert.equal(ids.get('tab-current').attributes['aria-pressed'],'true','Projects open on Current state');
  assert(!requests.some(m=>m.params?.name==='relay_work_graph'),'Default work view does not load the graph');
  await ids.get('tab-sources').onclick();
  assert.equal(ids.get('sources').children.length,30,'Connected source index is bounded for browsing');
  assert(walk(ids.get('sources')).some(e=>e.textContent==='<script>source</script>'),'Source titles are rendered as text');
  ids.get('source-filter').value='Source 4'; ids.get('source-filter').oninput();
  assert.equal(ids.get('sources').children.length,6,'Title search includes every matching connected source');
  ids.get('source-filter').value=''; ids.get('source-filter').oninput();
  ids.get('more-sources').onclick(); assert.equal(ids.get('sources').children.length,46,'More sources remain reachable');
  await ids.get('tab-current').onclick();
  const select=walk(ids.get('artifacts')).find(e=>e.textContent==='Select for context…');
  await select.onclick();assert.equal(ids.get('review').hidden,false);
  ids.get('cancel-change').onclick();assert.equal(commits,0,'Cancel never applies selection');
  await select.onclick();await ids.get('confirm-change').onclick();assert.equal(commits,1);
  assert(requests.some(m=>m.params?.arguments?.confirmation_token==='fixture-control'),'Confirmation carries exact app-only review control');
  const source=walk(ids.get('artifacts')).find(e=>e.textContent==='Provenance');await source.onclick();
  assert.equal(ids.get('provenance').hidden,false);
  document.getElementById('continue-request').value='Continue the guide.';await ids.get('prepare-context').onclick();
  failPacket=true;await ids.get('send-context').onclick();assert.equal(packetChecks,1);
  assert(!requests.some(m=>m.method==='ui/message'),'Stale context never reaches ChatGPT');
  failPacket=false;await ids.get('send-context').onclick();assert.equal(packetChecks,2);
  assert.equal(requests.filter(m=>m.method==='ui/message').length,1);
  await select.onclick();
  handler({source:window.parent,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{work:{...work,project:{...work.project,id:'work:other',revision:1}}}}}});
  assert.equal(ids.get('review').hidden,true,'Switching projects invalidates visible review');
  assert.equal(ids.get('packet').hidden,true,'Switching projects clears prepared context');
  assert.equal(ids.get('capture-packet').value,'','Switching projects clears result-capture identities');
  await ids.get('tab-graph').onclick();assert.equal(ids.get('graph').children[0].tagName,'svg');
  const messageCount=requests.filter(m=>m.method==='ui/message').length;
  await ids.get('understand-work').onclick();
  assert.equal(requests.filter(m=>m.method==='ui/message').length,messageCount+1,'Understanding explicitly asks the host model to analyze');
  assert(requests.at(-1).params.content[0].text.includes('relay_save_understanding'));
  assert.equal(commits,1,'Requesting analysis never commits a reviewed change');
  const understood={...work,source_coverage:{connected_sources:4,added_since_understanding:0},project:{...work.project,revision:3},understanding:{record_id:'understood',stale:false,saved_at:1790852772,changed_records:0,coverage:{considered_sources:2,considered_records:3,cited_sources:1},
    report:{objective:{text:'Check the source.',citations:[{record_id:'v1',quote:'<img src=x onerror=alert(1)>'}]},conclusions:[],decision_proposals:[],open_questions:[],limits:[]}},
    next_actions:Array.from({length:6},(_,i)=>({id:i===0?'action:fixture':'action:'+i,data:{text:'Verify the source.',reason:'The brief requires it.',topics:['Guide']}}))};
  handler({source:window.parent,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{work:understood}}}});
  assert.equal(ids.get('tab-current').attributes['aria-pressed'],'true','Host project switches restore Current state');
  assert(ids.get('understanding-meta').textContent.includes('2 sources considered'),'Source coverage comes from the saved input');
  assert(ids.get('understanding-meta').textContent.includes('Updated'),'The saved overview has a visible update time');
  const supporting=walk(ids.get('understanding-objective')).find(e=>e.textContent==='Based on 1 supporting record');
  await supporting.onclick();
  assert(walk(ids.get('statement-sources')).some(e=>e.textContent==='<img src=x onerror=alert(1)>'),'Literal citation quotes stay safe in the statement inspector');
  assert(!walk(ids.get('statement-sources')).some(e=>e.tagName==='img'));
  await walk(ids.get('statement-sources')).find(e=>e.textContent==='Open supporting record').onclick();
  assert.equal(requests.at(-1).params.arguments.record_id,'v1','Per-statement inspection uses its exact supporting identity');
  assert.equal(ids.get('next-actions').children.length,4,'The default list stays focused on four next steps');
  assert.equal(ids.get('other-actions').children.length,2,'Other grounded suggestions remain inspectable');
  assert.equal(ids.get('more-actions').hidden,false);
  assert.equal(ids.get('sources').children.length,0,'Changed work clears its stale source index');
  handler({source:window.parent,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{graph:{project_id:'work:other',revision:1,nodes:[],edges:[]}}}}});
  assert.equal(ids.get('sources').children.length,0,'Late source data from another project is ignored');
  let next=walk(ids.get('next-actions')).find(e=>e.textContent==='Continue…');await next.onclick();
  assert(requests.some(m=>m.params?.name==='relay_prepare_continuation' && m.params.arguments.action_id==='action:fixture'),'Suggested action identity reaches the continuation contract');
  const preparedCount=requests.filter(m=>m.params?.name==='relay_prepare_continuation').length;
  handler({source:window.parent,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{work:{...understood,project:{...understood.project,revision:4},understanding:{...understood.understanding,stale:true}}}}}});
  assert.equal(ids.get('understanding-state').className,'freshness stale','Changed work gets a prominent stale overview marker');
  next=walk(ids.get('next-actions')).find(e=>e.textContent==='Continue…');await next.onclick();
  assert.equal(requests.filter(m=>m.params?.name==='relay_prepare_continuation').length,preparedCount,'Stale suggestions cannot prepare context');
  console.log('Relay MCP UI controlled checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
