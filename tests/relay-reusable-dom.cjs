// Controlled UI host with the actual Python portable service; no live chat/account.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),cp=require('node:child_process');
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.attributes={};this.parent=null;this.offsetHeight=800;}
  append(...v){for(const e of v){e.parent=this;this.children.push(e);}}
  replaceChildren(...v){this.children=[];this.append(...v);}
  setAttribute(k,v){this.attributes[k]=v;}
  focus(){}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}
  click(){this.clicked=true;if(this.tagName==='a')requestedDownloads++;}
}
const ids=new Map(),document={body:new Element('body'),documentElement:{scrollHeight:800},getElementById:id=>{if(!ids.has(id))ids.set(id,new Element('div'));return ids.get(id);},createElement:t=>new Element(t)};
const walk=e=>[e,...e.children.flatMap(walk)];
const python=process.env.RELAY_TEST_PYTHON||'.venv-plugin/bin/python';
function service(name,args){
  const result=cp.spawnSync(python,['-c',`import asyncio,json,sys
from task_relay.web_plugin import call
v=json.load(sys.stdin)
r=asyncio.run(call(v['name'],v['args']))
p=r.pop('_private',{})
print(json.dumps({'structuredContent':r,'_meta':p}))`],{input:JSON.stringify({name,args}),encoding:'utf8'});
  if(result.status!==0)throw Error(result.stderr);
  return JSON.parse(result.stdout);
}
const fixture=JSON.parse(cp.spawnSync(python,['-c',`import json
from tests.test_portable_work import proposal
print(json.dumps(proposal()))`],{encoding:'utf8'}).stdout);
let handler,tools=[],messages=[],exportCount=0,uploadFail=false,holdTool=null,releaseTool=null,requestedDownloads=0,expansions=0;
const window={parent:{postMessage(m){if(m.method==='ui/request-display-mode')expansions++;if(m.id)queueMicrotask(()=>handler({source:window.parent,data:{jsonrpc:'2.0',id:m.id,result:{hostContext:{displayMode:'inline',availableDisplayModes:['inline','fullscreen']}}}}));}},
  addEventListener(type,fn){if(type==='message')handler=fn;},confirm:()=>false,
  openai:{toolOutput:{view:'home',documents:[]},async callTool(name,args){tools.push({name,args});if(name==='relay_review_export')exportCount++;if(name===holdTool)await new Promise(resolve=>{releaseTool=resolve;});return service(name,args);},
    async sendFollowUpMessage({prompt}){messages.push(prompt);},async uploadFile(){if(uploadFail)throw Error('Host unavailable');return{fileId:'file-explicit'};}}};
const context=vm.createContext({window,document,console,Blob,File:class{constructor(parts,name,options){this.parts=parts;this.name=name;this.options=options;}},Uint8Array,Map,Set,JSON,Error,btoa,atob,
  URL:{createObjectURL:()=> 'blob:controlled',revokeObjectURL:()=>{}},setTimeout:(fn,ms)=>ms===30000?0:setTimeout(fn,ms),clearTimeout,queueMicrotask});
vm.runInContext(fs.readFileSync('task_relay/assets/relay-reusable.js','utf8'),context);
const find=(parent,label)=>walk(parent).find(e=>e.tagName==='button'&&e.textContent===label);
const visible=e=>e&&!e.hidden&&(!e.parent||visible(e.parent));
const click=async b=>{assert(b,'Expected button');await b.onclick();};
const resultNotification=data=>handler({source:window.parent,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:data}}});
(async()=>{
  await new Promise(r=>setImmediate(r));
  assert.equal(ids.get('welcome').hidden,false);
  assert.equal(ids.get('reuse-section').hidden,true,'First use hides file pickers, catalogs and continuation controls');
  assert.equal(ids.get('proposal-section').hidden,true);
  assert.equal(expansions,0,'A conversation widget never forces a full-screen workspace');
  await click(ids.get('make-reusable'));
  assert.equal(messages.length,1);
  assert(messages[0].startsWith('Make this conversation reusable'),'The first action sends a readable request');
  assert(!messages[0].startsWith('{'),'First-use chat message contains no implementation envelope');
  messages.length=0;
  resultNotification(fixture);
  assert.equal(exportCount,0,'Initial proposals never save automatically');
  const skillCard=ids.get('proposals').children[0],workCard=ids.get('proposals').children[1];
  assert.equal(skillCard.children[0].textContent,'Skill');
  assert.equal(workCard.children[0].textContent,'Work snapshot');
  assert(!visible(find(skillCard,'Download')),'Export is hidden until Review');
  await click(find(skillCard,'Review'));
  assert.equal(exportCount,0,'Review never exports');
  assert(visible(find(skillCard,'Download')));
  const skillFields=walk(skillCard).filter(e=>e.tagName==='textarea');
  skillFields[0].value+='\nA user-reviewed improvement.\n';skillFields[0].oninput();
  await click(find(skillCard,'Download'));
  assert.equal(exportCount,1);
  assert(!visible(find(workCard,'Download')),'Saving a Skill never opens or saves its work proposal');
  const exact=tools.find(t=>t.name==='relay_review_export').args.document.files[0].content;
  assert(exact.endsWith('A user-reviewed improvement.\n'),'Exact edits reach export');
  uploadFail=true;await click(find(skillCard,'Save to ChatGPT'));
  assert(ids.get('status').textContent.includes('Download'),'Library failure preserves the export fallback');
  assert(find(skillCard,'Download'));
  await click(find(workCard,'Review'));
  await click(find(workCard,'Download'));
  assert.equal(exportCount,2,'Work export requires its own review');
  await click(ids.get('back-home'));await click(ids.get('open-saved'));
  assert.equal(ids.get('reuse-section').hidden,false);
  assert.equal(ids.get('selected-files').children.length,2,'Both selected files are visible together');
  ids.get('new-request').value='Continue this work and prepare the report.';
  await click(ids.get('prepare-reuse'));
  assert.equal(ids.get('context-section').hidden,false);
  assert.equal(messages.length,0,'Preparing context never sends or executes the request');
  await click(ids.get('continue-chat'));
  const sent=messages.at(-1);
  assert(sent.includes('country-competitor-research')&&sent.includes('competition-example'));
  assert(sent.includes('A user-reviewed improvement.'));
  ids.get('new-request').value='Run the Skill for a different country.';ids.get('new-request').oninput();
  await click(ids.get('continue-chat'));
  assert.equal(messages.length,2,'Continue prepares and sends a changed request in one action');
  assert(messages.at(-1).includes('Run the Skill for a different country.'));
  await click(ids.get('update-work'));
  const update=JSON.parse(messages.at(-1));
  assert.equal(update.action,'update_work');assert.equal(update.bases.length,2);
  await click(ids.get('improve-skill'));
  const improve=JSON.parse(messages.at(-1));
  assert.equal(improve.action,'improve_skill');assert.equal(improve.bases.length,1);assert.equal(improve.bases[0].kind,'skill');
  await click(ids.get('select-library'));
  assert.equal(ids.get('upload-files').clicked,true,'No Library capability falls back to upload');
  // A later proposal must not discard the user's edited first proposal.
  resultNotification(fixture);
  assert.equal(skillFields[0].value,exact);
  assert(walk(ids.get('proposals')).filter(e=>e.tagName==='textarea').length>3);
  // A delayed export must never restore bytes for text edited during the call.
  const laterSkill=ids.get('proposals').children.at(-2);
  await click(find(laterSkill,'Review'));
  const laterField=walk(laterSkill).find(e=>e.tagName==='textarea');
  const downloadsBefore=requestedDownloads;holdTool='relay_review_export';
  const saving=click(find(laterSkill,'Download'));
  laterField.value+='\nEdited during preparation.\n';laterField.oninput();
  releaseTool();await saving;holdTool=null;
  assert.equal(requestedDownloads,downloadsBefore,'Delayed exports cannot download an earlier edit');
  await click(find(laterSkill,'Download'));
  assert.equal(requestedDownloads,downloadsBefore+1,'Current text can still be reviewed and exported');
  // Likewise, an earlier context response cannot replace a changed request.
  ids.get('new-request').value='First request';ids.get('new-request').oninput();
  const sendsBefore=messages.length;
  holdTool='relay_prepare_reuse';const preparing=click(ids.get('continue-chat'));
  ids.get('new-request').value='Changed during preparation';ids.get('new-request').oninput();
  releaseTool();await preparing;holdTool=null;
  assert.equal(ids.get('context-section').hidden,true,'Delayed preparation cannot restore stale context');
  assert.equal(messages.length,sendsBefore,'Changed inputs during Continue never send stale context');
  assert(!tools.some(t=>/commit_change|run_text|save_understanding/.test(t.name)));
  console.log('Task Relay simple UI: first-use choices, readable previews, independent review/export, one-action continuation, Library fallback, draft and delayed-response protection passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
