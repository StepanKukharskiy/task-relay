// Controlled Chrome/DOM doubles + the actual shared Python capture bridge.
// Does not claim installed Chrome or live AI-site qualification.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm'),cp=require('node:child_process');
const root=path.resolve(__dirname,'..'),python=process.env.RELAY_TEST_PYTHON||path.join(root,'.venv-plugin/bin/python');
const folder=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'relay-chrome-test-')));
function call(value){const child=cp.spawnSync(python,['-c',`import json,sys
from pathlib import Path
from unittest.mock import patch
from task_relay import browser_capture as bc,browser_native as native,work_state as ws
db=ws.connect(Path(sys.argv[1])/'state.sqlite');bc.initialize(db)
with patch('task_relay.gemini.read_config',return_value=None):
 print(json.dumps(native.dispatch(db,Path(sys.argv[1]),json.load(sys.stdin))))
db.close()`,folder],{input:JSON.stringify(value),encoding:'utf8',cwd:root});if(child.status!==0)throw Error(child.stderr);return JSON.parse(child.stdout);}
const fixture=JSON.parse(cp.spawnSync(python,['-c','import json;from tests.test_browser_capture import capture,answer;print(json.dumps({"capture":capture(),"answer":answer()}))'],{encoding:'utf8',cwd:root}).stdout);
class El{
 constructor(tag){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.style={};this.files=[];}
 append(...children){this.children.push(...children);for(const child of children)child.parent=this;}
 replaceChildren(...children){this.children=[];this.append(...children);}
 setAttribute(name,value){this[name]=String(value);}
 get firstChild(){return this.children[0];}get options(){return this.children;}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}focus(){}select(){}click(){downloads.push({name:this.download,url:this.href});}
}
const walk=e=>[e,...e.children.flatMap(walk)],ids=new Map();
const htmlIds=new Set([...fs.readFileSync(path.join(root,'extensions/chrome/panel.html'),'utf8').matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]));
const document={body:new El('body'),getElementById(id){assert(htmlIds.has(id),'Panel control is missing from HTML: '+id);if(!ids.has(id))ids.set(id,new El('div'));return ids.get(id);},createElement:tag=>new El(tag),querySelectorAll:selector=>selector==='button'?[...ids.values()].flatMap(walk).filter(el=>el.tagName==='button'):[]};
let downloads=[],nativeCalls=[],storage={},settings={},captureCalls=0,loseSave=false,permission=false,grantRequest=true,permissionRequests=0,removedListener;
let clipboard=[],clipboardFails=false;
let chatgptPermission=false,grantChatGPT=false,chatgptPermissionRequests=0;
Object.defineProperty(global,'navigator',{value:{clipboard:{async writeText(text){if(clipboardFails)throw Error('Clipboard unavailable');clipboard.push(text);}}},configurable:true});
const chrome={permissions:{async contains(value){return value.origins?chatgptPermission:permission;},async request(value){if(value.origins){assert.deepEqual(value.origins,['https://chatgpt.com/*']);chatgptPermissionRequests++;chatgptPermission=grantChatGPT;return grantChatGPT;}permissionRequests++;permission=grantRequest;return grantRequest;},async remove(value){if(value.origins){chatgptPermission=false;removedListener?.(value);return true;}permission=false;removedListener?.({permissions:['nativeMessaging']});return true;},onRemoved:{addListener(fn){removedListener=fn;}}},
runtime:{async sendMessage(value){try{if(value.type.startsWith('chatgpt-'))return{ok:false,error:'Controlled manual-route fixture'};if(value.type==='capture'){captureCalls++;return{ok:true,result:{capture:structuredClone(fixture.capture)}};}nativeCalls.push(value.value);const result=call(value.value);if(value.value.action==='save'&&loseSave){loseSave=false;throw Error('controlled lost reply');}return{ok:true,result};}catch(error){return{ok:false,error:error.message};}}},
storage:{local:{async get(){return settings;},async set(value){settings={...settings,...value};}},session:{async get(){return storage;},async set(value){storage={...storage,...structuredClone(value)};},async remove(key){delete storage[key];}}}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(){for(let i=0;i<30;i++)await flush();}
async function click(el){assert(el,'Expected control');await el.onclick();await settle();}
function button(parent,label){return walk(parent).find(e=>e.tagName==='button'&&e.textContent===label);}
global.document=document;global.chrome=chrome;
const realTimeout=global.setTimeout;global.setTimeout=(fn,ms)=>ms===60000?0:realTimeout(fn,ms);
(async()=>{
 const portable=await import(path.join(root,'extensions/chrome/portable.js'));
 await import(path.join(root,'extensions/chrome/panel.js'));
 assert.equal(captureCalls,0,'Opening the panel never reads a page');
 assert.equal(nativeCalls.length,0,'Portable startup never probes a native application');assert.equal(permissionRequests,0);
 assert.equal(ids.get('local-work-option').hidden,true);
 await click(ids.get('connect-desktop'));assert.equal(permissionRequests,1);assert.equal(settings.desktop_enabled,true);assert.equal(ids.get('local-work-option').hidden,false);
 assert.equal(call({action:'library'}).work.length,0);
 await click(ids.get('keep'));assert.equal(captureCalls,1);assert.equal(ids.get('capture-text').value,fixture.capture.extracted_content);
 await click(ids.get('use-chat'));assert(ids.get('analysis-prompt').value.includes('skill_candidates'));assert.equal(call({action:'library'}).work.length,0);
 assert.equal(clipboard.at(-1),ids.get('analysis-prompt').value);assert.equal(ids.get('copy-prompt').hidden,true);
 await click(ids.get('import-response'));assert.equal(ids.get('response-import').hidden,false);
 ids.get('answer').value='Here is what is worth keeping.\n\n```json\n'+JSON.stringify(fixture.answer)+'\n```\n\nReview before saving.';await click(ids.get('review-answer'));
 assert.equal(call({action:'library'}).work.length,0,'Review does not save');
 const cards=ids.get('proposal-items').children,skillCard=cards[0],workCard=cards[1];
 assert(button(skillCard,'Save Skill locally'));assert(button(workCard,'Save Work locally'));
 loseSave=true;await click(button(workCard,'Save Work locally'));assert(ids.get('status').textContent.includes('lost reply'));assert.equal(call({action:'library'}).work.length,1);
 await click(button(workCard,'Save Work locally'));assert.equal(call({action:'library'}).work.length,1,'Lost reply recovers the committed Work');
 const workId=call({action:'library'}).work[0].id;
 await click(button(workCard,'Save Work locally'));assert.equal(call({action:'library'}).work.length,1);
 await click(ids.get('save-source'));await click(ids.get('save-source'));assert.equal(call({action:'library'}).sources.length,1,'Repeated Source save remains idempotent');
 await click(button(skillCard,'Save Skill locally'));assert.equal(call({action:'library'}).skills.length,1);
 const saves=nativeCalls.filter(c=>c.action==='save');assert.equal(saves[0].request_key,saves[1].request_key);assert.equal(saves[0].base_revision,saves[1].base_revision);
 ids.get('reuse-work').value=workId;ids.get('reuse-skill').value='competitor-research';ids.get('new-request').value='Prepare report';
 await click(ids.get('prepare-context'));assert(ids.get('context').value.includes('competitor-research'));assert(ids.get('context').value.includes('Which companies?'));
 ids.get('new-request').value='Changed request';ids.get('new-request').oninput();assert.equal(ids.get('context-preview').hidden,true,'Changed inputs invalidate copied context');
 const doc=portable.skill(fixture.answer.skill_candidates[0].files),blob=portable.skillZip(doc),zip=Buffer.from(await blob.arrayBuffer());
 const work=await portable.workMarkdown(fixture.answer.work_changes[0],fixture.capture,'Keep exact request\nwith two lines');
 const updated=await portable.workMarkdown(fixture.answer.work_changes[0],fixture.capture,'Capture progress',portable.workBase(work.content));
 const validate=cp.spawnSync(python,['-c',`import json,sys,base64
from task_relay.portable_work import import_file,work_document
v=json.load(sys.stdin)
doc=import_file('competitor-research.skill.zip',v['zip'])
first=work_document(v['work']);second=work_document(v['updated'])
assert first['request']=='Keep exact request\\nwith two lines'
assert second['revision']==2 and second['based_on_sha256']==first['sha256']
print(doc['name'])`],{input:JSON.stringify({zip:zip.toString('base64'),work:work.content,updated:updated.content}),encoding:'utf8',cwd:root});assert.equal(validate.status,0,validate.stderr);assert(validate.stdout.includes('competitor-research'));
 const base=await portable.skillBase(doc.files);assert.equal(base.sha256,call({action:'skill',name:doc.name}).sha256,'Browser base hash matches the shared Skill validator');
 const sourceText=await portable.sourceMarkdown(portable.source(fixture.capture));assert(sourceText.endsWith(fixture.capture.extracted_content));assert(sourceText.includes(await portable.sha(fixture.capture.extracted_content)));assert(sourceText.includes('Only loaded text was captured.'));
 const savedSource=call({action:'source',source_id:call({action:'library'}).sources[0].id});assert((await portable.sourceMarkdown(savedSource)).includes('Work identity: '+workId),'Local evidence exports retain their explicit Work association');
 assert.throws(()=>portable.validateAnswer(fixture.capture,{...fixture.answer,work_changes:[{...fixture.answer.work_changes[0],conclusions:[{text:'Fake',quote:'absent evidence'}]}]}),/absent/);
 const sourceReferenceAnswer=structuredClone(fixture.answer);
 sourceReferenceAnswer.work_changes[0].artifact_references=[{label:'Captured conversation',url:fixture.capture.url}];
 assert(!portable.source(fixture.capture).content.includes(fixture.capture.url));
 const citedSource=portable.validateAnswer(fixture.capture,sourceReferenceAnswer);
 assert.equal(citedSource.work_changes[0].artifact_references[0].url,fixture.capture.url);
 const sourceReferenceExport=await portable.workMarkdown(citedSource.work_changes[0],fixture.capture,'Keep source-linked work');
 assert(sourceReferenceExport.content.includes('Captured conversation: '+fixture.capture.url));
 for(const missing of [fixture.capture.url+'?invented=true','https://files.example.test/uncaptured']){
   sourceReferenceAnswer.work_changes[0].artifact_references[0].url=missing;
   assert.throws(()=>portable.validateAnswer(fixture.capture,sourceReferenceAnswer),/absent from/);
 }
 for(const unsafe of ['javascript:alert(1)','https://user:pass@example.test/artifact']){
   sourceReferenceAnswer.work_changes[0].artifact_references[0].url=unsafe;
   assert.throws(()=>portable.validateAnswer({...fixture.capture,extracted_content:fixture.capture.extracted_content+' '+unsafe},sourceReferenceAnswer),/absent from/);
 }
 assert.throws(()=>portable.skill([{path:'../SKILL.md',content:'bad'}]),/Unsafe/);
 assert.throws(()=>portable.continuation('Continue',[{content:'x'.repeat(180000)}]),/exceeds/);
 // Service worker accepts only its own side panel and checks navigation after
 // extraction. A content script cannot call the native bridge.
 let listener,nativeConnections=0,toolbarListener,panelBehavior,panelOpens=[],createdTabs=[],activatedTabs=[];const workerChrome={permissions:{async contains(){return false;}},action:{onClicked:{addListener(fn){toolbarListener=fn;}}},runtime:{id:'fixture',getURL:p=>'chrome-extension://fixture/'+p,onMessage:{addListener(fn){listener=fn;}},connectNative(){nativeConnections++;throw Error('Unexpected native connection');}},sidePanel:{async setPanelBehavior(value){panelBehavior=value;},async open(value){panelOpens.push(value);}},tabs:{async query(){return[{id:1,url:'https://chatgpt.com/c/controlled'}];},async create(value){createdTabs.push(value);return{id:42};},async update(id,value){activatedTabs.push({id,...value});return{id};}},scripting:{async executeScript(){return[{result:fixture.capture}];}}};
 const workerContext=vm.createContext({chrome:workerChrome,setTimeout:callback=>callback()}),chatModule=new vm.SourceTextModule(fs.readFileSync(path.join(root,'extensions/chrome/chatgpt.js'),'utf8'),{context:workerContext});await chatModule.link(()=>{});
 const mod=new vm.SourceTextModule(fs.readFileSync(path.join(root,'extensions/chrome/worker.js'),'utf8'),{context:workerContext});const extractModule=new vm.SourceTextModule(fs.readFileSync(path.join(root,'extensions/chrome/extract.js'),'utf8'),{context:workerContext});await extractModule.link(()=>{});await mod.link(specifier=>specifier==='./extract.js'?extractModule:chatModule);await mod.evaluate();
 const sender={id:'fixture',url:'chrome-extension://fixture/panel.html'};
 assert.equal(panelBehavior.openPanelOnActionClick,false,'Disable declarative opening so toolbar action invokes activeTab');
 let authorized=false,workerCaptures=0;workerChrome.tabs.query=async()=>[authorized?{id:1,url:fixture.capture.url}:{id:1}];workerChrome.scripting.executeScript=async()=>{workerCaptures++;return[{result:fixture.capture}];};
 const ungranted=await new Promise(r=>listener({type:'capture'},sender,r));assert.equal(ungranted.ok,false);assert(ungranted.error.includes('toolbar icon'));assert.equal(workerCaptures,0);
 // Chrome grants activeTab when invoking the action listener. The fixture
 // supplies URL access at that boundary, not simply when the panel appears.
 authorized=true;toolbarListener({id:1,url:fixture.capture.url});assert.equal(panelOpens.length,1);assert.equal(panelOpens[0].tabId,1);assert.equal(workerCaptures,0,'Toolbar opens the panel without reading the page');
 toolbarListener({});assert.equal(panelOpens.length,1,'Missing tab never opens another panel');
 assert.equal(listener({type:'native',value:{action:'save'}},{...sender,tab:{id:1}},()=>{}),false);
 const noPermission=await new Promise(r=>listener({type:'native',value:{action:'status'}},sender,r));assert.equal(noPermission.ok,false);assert.equal(nativeConnections,0);
 let captureInjection;workerChrome.scripting.executeScript=async injection=>{captureInjection=injection;return[{result:fixture.capture}];};
 const captured=await new Promise(r=>listener({type:'capture',selectionOnly:true},sender,r));assert.equal(captureInjection.func.name,'taskRelayCapture');assert.equal(captureInjection.args[0],true);assert.equal(captured.ok,true);
 workerChrome.scripting.executeScript=async()=>[{result:{captureError:'Select a smaller excerpt; nothing was truncated.'}}];
 const rejectedCapture=await new Promise(r=>listener({type:'capture'},sender,r));assert.equal(rejectedCapture.ok,false);assert.equal(rejectedCapture.error,'Select a smaller excerpt; nothing was truncated.','Extraction errors cross the injection boundary without being masked as access or navigation failures');
 workerChrome.scripting.executeScript=async()=>[{result:fixture.capture}];
 let count=0;workerChrome.tabs.query=async()=>[{id:++count,url:'https://chatgpt.com/c/controlled'}];
 const navigated=await new Promise(r=>listener({type:'capture'},sender,r));assert.equal(navigated.ok,false);assert(navigated.error.includes('changed'));
 workerChrome.tabs.query=async()=>[{id:1,url:fixture.capture.url}];let handoffInjections=0;
 workerChrome.tabs.query=async()=>[{id:1}];const missingChatAccess=await new Promise(r=>listener({type:'chatgpt-inspect'},sender,r));assert.equal(missingChatAccess.code,'page_access_required');assert(missingChatAccess.error.includes('once'));workerChrome.tabs.query=async()=>[{id:1,url:fixture.capture.url}];
 workerChrome.scripting.executeScript=async()=>{throw Error('Cannot access contents of url: host permission required');};const revokedAccess=await new Promise(r=>listener({type:'chatgpt-inspect'},sender,r));assert.equal(revokedAccess.code,'page_access_required');
 workerChrome.scripting.executeScript=async injection=>{handoffInjections++;assert.equal(injection.func.name,'chatgptHandoff');return[{result:{url:fixture.capture.url,adapter:'chatgpt'}}];};
 const wrongTab=await new Promise(r=>listener({type:'chatgpt-insert',handoff:{tabId:2}},sender,r));assert.equal(wrongTab.ok,false);assert.equal(handoffInjections,0,'Wrong tab is refused before a page edit');
 const inspected=await new Promise(r=>listener({type:'chatgpt-inspect'},sender,r));assert.equal(inspected.ok,true);assert.equal(inspected.result.tabId,1);assert.equal(nativeConnections,0);
 let injectedTicket;workerChrome.scripting.executeScript=async injection=>{injectedTicket=injection.args[1];return[{result:{url:fixture.capture.url}}];};
 await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1,attachmentTabId:2,allowAttachmentResponse:true}},sender,r));assert.equal(injectedTicket.allowAttachmentResponse,false,'A caller flag cannot authorize attachment matching in a different tab');
 await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1,attachmentTabId:1}},sender,r));assert.equal(injectedTicket.allowAttachmentResponse,true);
 workerChrome.scripting.executeScript=async()=>[{result:{url:fixture.capture.url,handoffError:'The matching request is collapsed or edited. Expand its Show more control in ChatGPT, then retry Get result.'}}];
 const collapsed=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(collapsed.ok,false);assert(collapsed.error.includes('Show more'));assert(!collapsed.error.includes('tab changed'),'Expected page recovery errors must not be masked as navigation');
 let expansionReads=0,expansionMode='ready';
 workerChrome.scripting.executeScript=async injection=>{assert.equal(injection.args[0],'response');expansionReads++;if(expansionReads===1)return[{result:{url:fixture.capture.url,handoffError:'Expanding',handoffCode:'request_expanded'}}];assert.equal(injection.args[1].expansionAttempted,true);if(expansionMode==='lost')throw Error('Lost expansion read reply');if(expansionMode==='pending'||expansionReads===2)return[{result:{url:fixture.capture.url,handoffError:'Still expanding',handoffCode:'request_expanding'}}];return[{result:{url:fixture.capture.url,response:'verified result',requestVerification:'exact-visible-request'}}];};
 const expanded=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(expanded.ok,true);assert.equal(expanded.result.response,'verified result');assert.equal(expansionReads,3);
 expansionReads=0;expansionMode='pending';const expansionTimeout=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(expansionTimeout.code,'request_expanding');assert.equal(expansionReads,11,'Expansion has a bounded wait, with no repeated display click');
 expansionReads=0;expansionMode='lost';const expansionLost=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(expansionLost.ok,false);assert.equal(expansionReads,2,'Uncertain injection replies are not retried');
 expansionReads=0;expansionMode='ready';workerChrome.tabs.query=async()=>[{id:expansionReads?2:1,url:fixture.capture.url}];const expansionSwitched=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(expansionSwitched.ok,false);assert.equal(expansionReads,1,'A tab switch stops expansion recovery before further reads');workerChrome.tabs.query=async()=>[{id:1,url:fixture.capture.url}];
 expansionReads=0;workerChrome.scripting.executeScript=async injection=>{assert.equal(injection.args[0],'recover');expansionReads++;return[{result:expansionReads===1?{url:fixture.capture.url,handoffError:'Expanding',handoffCode:'request_expanded'}:{url:fixture.capture.url,recoveredRequest:'full request'}}];};const recoveredExpansion=await new Promise(r=>listener({type:'chatgpt-recover'},sender,r));assert.equal(recoveredExpansion.ok,true);assert.equal(expansionReads,2);
 workerChrome.scripting.executeScript=async()=>[{result:{url:fixture.capture.url,handoffError:'Send the message first.',handoffCode:'draft_missing'}}];
 const deletedDraft=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(deletedDraft.code,'draft_missing');
 workerChrome.scripting.executeScript=async()=>[{result:undefined}];
 const emptyReply=await new Promise(r=>listener({type:'chatgpt-response',handoff:{tabId:1}},sender,r));assert.equal(emptyReply.ok,false);assert(emptyReply.error.includes('did not return'));assert(!emptyReply.error.includes('tab changed'));
 workerChrome.tabs.query=async()=>[{id:++count,url:fixture.capture.url}];
 const handoffNavigation=await new Promise(r=>listener({type:'chatgpt-inspect'},sender,r));assert.equal(handoffNavigation.ok,false);assert(handoffNavigation.error.includes('tab changed'),'Actual tab switching remains blocked even without an injection result');
 assert.equal(listener({type:'chatgpt-insert'},{...sender,tab:{id:1}},()=>{}),false,'A page cannot request draft insertion');
 const destination=await new Promise(r=>listener({type:'open-chatgpt'},sender,r));assert.equal(destination.result.tabId,42);assert.deepEqual(structuredClone(createdTabs),[{url:'https://chatgpt.com/'}]);
 await new Promise(r=>listener({type:'open-chatgpt',tabId:42},sender,r));assert.deepEqual(activatedTabs,[{id:42,active:true}]);assert.equal(createdTabs.length,1,'Returning to the known destination does not create another tab');
 assert.equal(listener({type:'open-chatgpt'},{...sender,tab:{id:1}},()=>{}),false,'A webpage cannot open destinations through the extension worker');
 // Exercise the real worker's explicit, bounded destination wait. Readiness
 // probes do not edit; after readiness, the existing insertion guard is used.
 let hostAccess=false,readyQueries=0,readyProbes=0,readyEdits=0,readyMode='loading';
 workerChrome.permissions.contains=async value=>!!value.origins&&hostAccess;
 workerChrome.tabs.get=async id=>{readyQueries++;return{id,status:readyMode==='never'?'loading':readyQueries===1?'loading':'complete',url:readyMode==='redirect'?'https://other.example.test/':'https://chatgpt.com/'};};
 workerChrome.tabs.query=async()=>[{id:readyMode==='switched'?99:42,url:'https://chatgpt.com/'}];
 workerChrome.scripting.executeScript=async injection=>{if(injection.args[0]==='inspect'){readyProbes++;return[{result:readyProbes===1?{handoffError:'ChatGPT’s message box was not recognized. Use Copy request instead.'}:{adapter:'chatgpt',url:'https://chatgpt.com/'}}];}assert.equal(injection.args[0],'insert');readyEdits++;return[{result:{inserted:true,url:'https://chatgpt.com/'}}];};
 const readyMessage={type:'chatgpt-insert',waitForReady:true,handoff:{tabId:42,url:'https://chatgpt.com/'}};
 const deniedAutofill=await new Promise(r=>listener(readyMessage,sender,r));assert.equal(deniedAutofill.code,'page_access_required');assert.equal(readyQueries,0);assert.equal(readyEdits,0);
 hostAccess=true;const readyInsertion=await new Promise(r=>listener(readyMessage,sender,r));assert.equal(readyInsertion.ok,true);assert.equal(readyEdits,1);assert.equal(readyProbes,2);
 readyMode='switched';readyQueries=0;const switchedAutofill=await new Promise(r=>listener(readyMessage,sender,r));assert.equal(switchedAutofill.ok,false);assert.equal(readyEdits,1,'Switching tabs never edits either page');
 readyMode='redirect';readyQueries=0;const redirectedAutofill=await new Promise(r=>listener(readyMessage,sender,r));assert.equal(redirectedAutofill.ok,false);assert.equal(readyEdits,1);
 readyMode='never';readyQueries=0;const delayedAutofill=await new Promise(r=>listener(readyMessage,sender,r));assert.equal(delayedAutofill.ok,false);assert.equal(readyQueries,40);assert.equal(readyEdits,1,'A timed-out destination retains the ticket and performs no edit');
 // A fresh panel with no native host can capture, review/export and continue
 // from selected files without Desktop credentials or a Relay provider.
 ids.clear();storage={};settings={};nativeCalls=[];const bridgeSend=chrome.runtime.sendMessage;
 // Even a previously granted permission is insufficient without explicit opt-in.
 permission=true;
 chrome.runtime.sendMessage=async value=>{if(value.type==='native'){nativeCalls.push(value.value);return{ok:false,error:'Native host unavailable'};}return bridgeSend(value);};
 await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?fallback');
 assert(ids.get('connection').textContent.includes('off'));assert.equal(nativeCalls.length,0);await click(ids.get('keep'));assert.equal(ids.get('save-source').hidden,true);
 await click(ids.get('use-chat'));ids.get('answer').value=JSON.stringify(fixture.answer);await click(ids.get('review-answer'));
 assert.equal(button(ids.get('proposal-items'),'Save Skill locally'),undefined);
 await click(button(ids.get('proposal-items'),'Download Skill'));await click(button(ids.get('proposal-items'),'Download work'));
 assert(downloads.some(d=>d.name===doc.name+'.md'));assert(downloads.some(d=>d.name.endsWith('.relay.md')));
 const skillNameEditor=walk(ids.get('proposal-items').children[0]).find(e=>e.tagName==='textarea'),originalSkillText=skillNameEditor.value;
 skillNameEditor.value=originalSkillText.replace('name: competitor-research','name: updated-competitor-research');skillNameEditor.oninput();await settle();await click(button(ids.get('proposal-items'),'Download Skill'));assert.equal(downloads.at(-1).name,'updated-competitor-research.md','Export uses the reviewed name at click time');skillNameEditor.value=originalSkillText;skillNameEditor.oninput();await settle();
 ids.get('open-files').files=[{name:'SKILL.md',size:doc.files[0].content.length,text:async()=>doc.files[0].content},{name:work.filename,size:work.content.length,text:async()=>work.content}];await ids.get('open-files').onchange();await settle();
 const selectedLegacy=structuredClone(storage.panel.opened);
 ids.get('open-files').files=[{name:doc.name+' (1).md',size:doc.files[0].content.length,text:async()=>doc.files[0].content},{name:work.filename,size:work.content.length,text:async()=>work.content}];await ids.get('open-files').onchange();await settle();
 assert.equal(storage.panel.opened[0].kind,'skill');assert.equal((await portable.skillBase([{path:'SKILL.md',content:storage.panel.opened[0].content}])).sha256,base.sha256,'Named downloads, including Chrome duplicate suffixes, preserve the standard Skill content and base hash');
 const selectedNamed=structuredClone(storage.panel.opened);ids.get('open-files').files=[{name:'not-a-skill.md',size:12,text:async()=>'# Plain text'}];await ids.get('open-files').onchange();await settle();assert.deepEqual(storage.panel.opened,selectedNamed,'Invalid renamed Markdown cannot replace selected files');
 assert.equal(selectedLegacy[0].content,selectedNamed[0].content);
 ids.get('new-request').value='Continue Brazil';await click(ids.get('prepare-context'));assert(ids.get('context').value.includes('competitor-research'));assert(ids.get('context').value.includes('Which companies?'));assert.equal(nativeCalls.length,0);
 const portableTarget=[...ids.get('work-target').options].find(o=>o.value.startsWith('portable:'));assert(portableTarget);
 ids.get('work-target').value=portableTarget.value;await ids.get('work-target').onchange();await settle();
 await click(ids.get('capture-progress'));await click(ids.get('use-chat'));assert(clipboard.at(-1).startsWith('Capture progress'));assert(clipboard.at(-1).includes(work.filename));
 ids.get('answer').value='A previous response';clipboardFails=true;await click(ids.get('use-chat'));assert.equal(ids.get('copy-prompt').hidden,false);assert.equal(ids.get('settings').hidden,false);assert.equal(ids.get('answer').value,'','Preparing a fresh request clears stale response transport');clipboardFails=false;
 const beforeDenial=structuredClone(storage.panel);grantRequest=false;await click(ids.get('connect-desktop'));assert.equal(nativeCalls.length,0);assert.equal(settings.desktop_enabled,false);assert.deepEqual(storage.panel.capture,beforeDenial.capture);
 grantRequest=true;await click(ids.get('connect-desktop'));assert.equal(nativeCalls.length,1);assert.equal(settings.desktop_enabled,false);assert.equal(ids.get('save-source').hidden,true);assert(ids.get('connection').textContent.includes('unavailable'));assert.deepEqual(storage.panel.capture,beforeDenial.capture);assert.equal(ids.get('disconnect-desktop').hidden,false,'Granted access can be removed even if the bridge is unavailable');
 // Failed response imports preserve the existing review; no raw parser error is
 // presented and no object is saved.
 const previousCards=ids.get('proposal-items').children;ids.get('answer').value='Not a Relay response';await click(ids.get('review-answer'));assert(ids.get('status').textContent.includes('complete response block'));assert.equal(ids.get('proposal-items').children,previousCards);
 assert.throws(()=>portable.importResponse('```json\n'+JSON.stringify(fixture.answer)+'\n```\n```json\n'+JSON.stringify(fixture.answer)+'\n```'),/several Relay/);
 // Explicit response-file import and review work without a Desktop probe.
 ids.get('response-file').files=[{size:JSON.stringify(fixture.answer).length,text:async()=>JSON.stringify(fixture.answer)}];await ids.get('response-file').onchange();await settle();assert.equal(ids.get('proposal-items').children.length,2);
 const editableWork=walk(ids.get('proposal-items').children[1]).filter(e=>e.tagName==='textarea')[1];editableWork.value='User edited objective';editableWork.oninput();await settle();
 await chrome.permissions.remove({permissions:['nativeMessaging']});await settle();assert.equal(walk(ids.get('proposal-items').children[1]).filter(e=>e.tagName==='textarea')[1].value,'User edited objective','Revoking optional access preserves review edits');
 fixture.capture.source_type='page';fixture.capture.url='https://pricing.example.test/br';fixture.capture.source_metadata.adapter='generic';await click(ids.get('keep'));assert.equal(ids.get('export-source').textContent,'Download evidence');assert.equal(storage.panel.capture.source_metadata.work_reference.work_id,portable.workBase(work.content).work_id);
 const callsBeforeReload=nativeCalls.length;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-portable');assert.equal(ids.get('work-target').value,portableTarget.value,'Reopening the panel preserves the portable Work association');assert.equal(nativeCalls.length,callsBeforeReload);
 // A supported ChatGPT tab prepares a retained ticket, never copies or sends
 // automatically, and recovers the exact request after a lost insertion reply.
 let insertAttempts=0,resultMode='good';let lastInsertion,selectionRequested=false;
 chrome.runtime.sendMessage=async value=>{
   if(value.type==='chatgpt-inspect')return{ok:true,result:{tabId:7,url:'https://chatgpt.com/c/handoff',adapter:'chatgpt'}};
   if(value.type==='capture')selectionRequested=value.selectionOnly===true;
   if(value.type==='chatgpt-insert'){lastInsertion=structuredClone(value.handoff);insertAttempts++;if(insertAttempts===1)return{ok:false,error:'Controlled lost insertion reply; check draft'};return{ok:true,result:{tabId:7,url:value.handoff.url,inserted:true,reused:true}};}
   if(value.type==='chatgpt-response'){if(resultMode==='wrong')return{ok:true,result:{requestId:'unrelated',response:JSON.stringify(fixture.answer)}};
     if(resultMode==='wrong-category')return{ok:true,result:{requestId:value.handoff.requestId,response:JSON.stringify(fixture.answer)}};
     if(resultMode==='invalid')return{ok:true,result:{requestId:value.handoff.requestId,response:'Incomplete result'}};
     const answer=value.handoff.request.includes('work_changes must be empty')?{...fixture.answer,work_changes:[]}:value.handoff.request.includes('skill_candidates must be empty')?{...fixture.answer,skill_candidates:[]}:fixture.answer;
     if(resultMode==='source-reference')answer.work_changes[0].artifact_references=[{label:'Captured source',url:fixture.capture.url}];
     return{ok:true,result:{requestId:value.handoff.requestId,response:value.handoff.requestId.replace('REQUEST','RESPONSE')+'\n```json\n'+JSON.stringify(answer)+'\n```',messageId:'controlled-result',url:value.handoff.url}};}
   return bridgeSend(value);
 };
 const previousCopies=clipboard.length;await click(ids.get('use-chat'));assert.equal(clipboard.length,previousCopies);assert.equal(insertAttempts,0);assert.equal(storage.panel.handoff.state,'prepared');assert.equal(ids.get('get-chatgpt-result').hidden,true);
 const ticket=structuredClone(storage.panel.handoff);assert.equal(ids.get('analysis-prompt').value,ticket.request);assert(ticket.request.startsWith(ticket.requestId+'\n'));
 await click(ids.get('insert-chatgpt'));assert.equal(storage.panel.handoff.state,'inserting');assert.equal(storage.panel.handoff.request,ticket.request);assert.equal(insertAttempts,1);
 ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-handoff');assert.equal(ids.get('analysis-prompt').value,ticket.request);assert.equal(ids.get('get-chatgpt-result').hidden,false);assert.equal(insertAttempts,1,'Restoring an uncertain handoff does not retry');
 await click(ids.get('insert-chatgpt'));assert.equal(insertAttempts,2);assert.equal(storage.panel.handoff.requestId,ticket.requestId);assert.equal(storage.panel.handoff.state,'inserted');
 const oldReview=ids.get('proposal-items').children;resultMode='wrong';await click(ids.get('get-chatgpt-result'));assert.equal(ids.get('proposal-items').children,oldReview);assert(ids.get('status').textContent.includes('another request'));
 resultMode='invalid';await click(ids.get('get-chatgpt-result'));assert.equal(ids.get('proposal-items').children,oldReview);assert.equal(storage.panel.handoff.state,'inserted');
 resultMode='good';await click(ids.get('get-chatgpt-result'));assert.equal(ids.get('proposal-items').children.length,2);assert.equal(storage.panel.handoff.state,'reviewed');assert.equal(storage.panel.handoff.messageId,'controlled-result');assert.equal(ids.get('review-view').hidden,false);
 const reviewedObjective=walk(ids.get('proposal-items').children[1]).filter(e=>e.tagName==='textarea')[1];reviewedObjective.value='Keep my reviewed edit';reviewedObjective.oninput();await settle();await click(ids.get('get-chatgpt-result'));assert.equal(walk(ids.get('proposal-items').children[1]).filter(e=>e.tagName==='textarea')[1].value,'Keep my reviewed edit','Repeated retrieval cannot discard review edits');
 assert.equal(button(ids.get('proposal-items'),'Save Skill locally'),undefined,'The ChatGPT handoff works without Desktop');
 assert.equal(insertAttempts,2,'Reading a response never repeats insertion');await click(ids.get('keep'));assert.equal(storage.panel.handoff,null,'A new capture invalidates the old response ticket');
 const priorMessage=chrome.runtime.sendMessage;let recoveryCalls=0,recoveryInvalid=false;
 const recoveredSource=portable.source(fixture.capture);
 chrome.runtime.sendMessage=async value=>value.type==='chatgpt-recover'?(recoveryCalls++,{ok:true,result:{tabId:7,url:ticket.url,requestId:ticket.requestId,recoveredRequest:ticket.request,recoveredContext:{capture:recoveredSource,existing_work:null,selected_skill:null},response:recoveryInvalid?'invalid':JSON.stringify(fixture.answer),messageId:'recovered-result'}}):priorMessage(value);
 await click(ids.get('recover-chatgpt'));assert.equal(recoveryCalls,0,'Recovery must preserve an existing capture/review without reading another message');
 await click(ids.get('forget'));recoveryInvalid=true;await click(ids.get('recover-chatgpt'));assert.equal(storage.panel,undefined,'Invalid recovered response must not install a capture or handoff');
 recoveryInvalid=false;await click(ids.get('recover-chatgpt'));assert.equal(storage.panel.handoff.state,'reviewed');assert.equal(storage.panel.handoff.requestId,ticket.requestId);assert.equal(storage.panel.capture.extracted_content,recoveredSource.content);assert.equal(ids.get('proposal-items').children.length,2);assert.equal(insertAttempts,2,'Recovery never repeats insertion');assert.equal(storage.panel.capture.source_metadata.captured_at,recoveredSource.captured_at);
 const priorReview=structuredClone(storage.panel),beforeNewCapture=chrome.runtime.sendMessage;
 await click(ids.get('new-text'));assert.equal(ids.get('preview').hidden,true);assert.equal(ids.get('make-now').hidden,false);
 chrome.runtime.sendMessage=async value=>value.type==='capture'?{ok:false,error:'Select visible document text only.'}:beforeNewCapture(value);
 await click(ids.get('make-now'));assert.equal(ids.get('status').textContent,'Select visible document text only.');assert.deepEqual(storage.panel,{...priorReview,startingNew:true},'Failed replacement capture preserves prior reviewed state');
 chrome.runtime.sendMessage=beforeNewCapture;
 // The primary click composes existing capture/prepare/insert boundaries. An
 // uncertain insertion cannot become another capture or duplicate request.
 await click(ids.get('forget'));const beforePrimary=captureCalls;insertAttempts=0;
 await click(ids.get('make-now'));assert.equal(captureCalls,beforePrimary+1);assert.equal(insertAttempts,1);assert.equal(storage.panel.handoff.state,'inserting');assert.equal(selectionRequested,true);assert(storage.panel.handoff.request.includes('work_changes must be empty'));assert(storage.panel.handoff.request.includes('company-agnostic'));assert(storage.panel.handoff.request.includes('named inputs'));const retainedPrimary=structuredClone(storage.panel);
 await click(ids.get('make-now'));assert.equal(captureCalls,beforePrimary+1);assert.equal(insertAttempts,1);assert.deepEqual(storage.panel.handoff,retainedPrimary.handoff,'Repeated primary click preserves the uncertain request');
 await click(ids.get('insert-chatgpt'));assert.equal(storage.panel.handoff.state,'inserted');resultMode='wrong-category';const beforeWrongCategory=downloads.length;await click(ids.get('get-chatgpt-result'));assert.equal(downloads.length,beforeWrongCategory);assert.equal(storage.panel.handoff.state,'inserted');assert(ids.get('status').textContent.includes('only a Skill'));resultMode='good';const beforeDownload=downloads.length;await click(ids.get('get-chatgpt-result'));assert.equal(ids.get('proposal-items').children.length,1);assert.equal(downloads.length,beforeDownload+1);assert.equal(downloads.at(-1).name,'competitor-research.md');
 await click(ids.get('new-text'));await click(ids.get('make-job'));assert(storage.panel.handoff.request.includes('instance-specific portable work snapshot'));assert(storage.panel.handoff.request.includes('skill_candidates must be empty'));resultMode='source-reference';await click(ids.get('get-chatgpt-result'));resultMode='good';
 assert.equal(ids.get('proposal-items').children.length,1);assert(downloads.at(-1).name.endsWith('.relay.md'));
 // Retained pre-rename make_job sessions keep reviewed edits and identity,
 // while displaying the new snapshot terminology without new AI requests.
 const retainedSnapshot=structuredClone(storage.panel);const insertsBeforeRenameReload=insertAttempts;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?snapshot-naming');assert.deepEqual(storage.panel,retainedSnapshot);assert.equal(insertAttempts,insertsBeforeRenameReload);assert.equal(ids.get('result-heading').textContent,'Your work.');
 const primaryWork=ids.get('proposal-items').children[0],editor=walk(primaryWork).find(e=>e.className==='editor'),exportButton=button(primaryWork,'Download work');
 assert.equal(editor.hidden,true);assert.equal(exportButton.parent.className,'actions','Download is directly on the result card, outside its editor');
 await click(button(primaryWork,'Edit'));assert.equal(editor.hidden,false);const primaryObjective=walk(editor).filter(e=>e.tagName==='textarea')[1];primaryObjective.value='My edited reusable work';primaryObjective.oninput();await settle();await click(button(primaryWork,'Done'));assert.equal(editor.hidden,true);await click(exportButton);assert.equal(storage.panel.proposals.work_changes[0].objective,'My edited reusable work');
 // Deleting an unsent draft has a visible explicit restoration path. Get
 // results cannot restore/insert implicitly or overwrite an unrelated draft.
 await click(ids.get('new-text'));await click(ids.get('make-now'));const pending=structuredClone(storage.panel),afterPendingInsert=insertAttempts;
 assert.equal(ids.get('insert-chatgpt').hidden,false);assert.equal(ids.get('insert-chatgpt').textContent,'Place request');
 const pendingMessages=chrome.runtime.sendMessage;
 chrome.runtime.sendMessage=async value=>value.type==='chatgpt-response'?{ok:false,error:'Send the message in ChatGPT first.',code:'draft_missing'}:pendingMessages(value);
 await click(ids.get('get-chatgpt-result'));assert.equal(insertAttempts,afterPendingInsert);assert.equal(storage.panel.handoff.requestId,pending.handoff.requestId);
 assert.equal(ids.get('get-chatgpt-result').textContent,'Download Skill');await click(ids.get('get-chatgpt-result'));assert.equal(insertAttempts,afterPendingInsert,'Repeated Download never becomes an insertion');
 await click(ids.get('insert-chatgpt'));assert.equal(insertAttempts,afterPendingInsert+1);assert.equal(storage.panel.handoff.request,pending.handoff.request);assert.equal(storage.panel.handoff.requestId,pending.handoff.requestId,'Separate explicit restoration keeps the exact request identity');
 chrome.runtime.sendMessage=pendingMessages;
 const beforeReplyRecovery=structuredClone(storage),downloadsBeforeReplyRecovery=downloads.length,insertionsBeforeReplyRecovery=insertAttempts;
 chrome.runtime.sendMessage=async value=>value.type==='chatgpt-insert'?{ok:false,error:'The matching Relay reply is already in this chat.',code:'reply_available'}:pendingMessages(value);
 await click(ids.get('insert-chatgpt'));assert.equal(storage.panel.handoff.state,'reviewed');assert.equal(downloads.length,downloadsBeforeReplyRecovery+1);assert.equal(insertAttempts,insertionsBeforeReplyRecovery,'A completed reply redirects explicit Restore to result retrieval without another draft edit');
 chrome.runtime.sendMessage=pendingMessages;storage=beforeReplyRecovery;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-after-reply-recovery');
 // New text is an explicit choice, even with an unfinished request. Reopening
 // and Back retain that request; replacement capture preserves it separately.
 await click(ids.get('new-text'));assert.equal(storage.panel.startingNew,true);assert.equal(ids.get('analysis-section').hidden,true);assert.equal(ids.get('back-current').hidden,false);
 ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-new-text');assert.equal(ids.get('make-now').hidden,false);assert.equal(ids.get('analysis-section').hidden,true);assert.equal(insertAttempts,afterPendingInsert+1);
 await click(ids.get('back-current'));assert.equal(storage.panel.handoff.request,pending.handoff.request);assert.equal(ids.get('insert-chatgpt').hidden,false);
 await click(ids.get('new-text'));await click(ids.get('make-now'));const replacement=structuredClone(storage.panel.handoff);assert.notEqual(replacement.requestId,pending.handoff.requestId);assert.equal(storage.panel.previousSessions.at(-1).handoff.request,pending.handoff.request);assert.equal(lastInsertion.replaceDraft.request,pending.handoff.request,'Explicit New permits replacement only of the retained exact draft');
 const beforePrevious=insertAttempts;await click(ids.get('previous-request'));assert.equal(storage.panel.handoff.requestId,pending.handoff.requestId);assert.equal(storage.panel.previousSessions.at(-1).handoff.requestId,replacement.requestId);assert.equal(insertAttempts,beforePrevious,'Returning to a previous capture never inserts or sends');
 // Skills with resources export the whole portable package, never just the
 // entry file. Editing and direct export do not install or execute a Skill.
 await click(ids.get('forget'));await click(ids.get('keep'));fixture.answer.skill_candidates[0].files.push({path:'references/checks.md',content:'Check primary sources.'});
 ids.get('answer').value=JSON.stringify(fixture.answer);await click(ids.get('review-answer'));await click(button(ids.get('proposal-items'),'Download Skill folder'));assert(downloads.some(d=>d.name.endsWith('.skill.zip')));
 // Any selected article uses the same request/response contract. Creating a
 // destination neither injects into it nor sends a message. Only an explicit
 // result read in an authorized ChatGPT tab can bind the exact ticket.
 await click(ids.get('forget'));fixture.capture.url='https://article.example.test/method';fixture.capture.source_type='selection';
 let destinationOpens=0,crossInspections=0,crossReads=0,crossInserts=0,destinationReady=false,crossMode='wrong',loseOpen=false;
 chrome.runtime.sendMessage=async value=>{
  if(value.type==='capture')return{ok:true,result:{capture:structuredClone(fixture.capture)}};
  if(value.type==='open-chatgpt'){destinationOpens++;if(loseOpen)return{ok:false,error:'Controlled lost tab-opening reply'};return{ok:true,result:{tabId:42}};}
  if(value.type==='chatgpt-inspect'){crossInspections++;return destinationReady?{ok:true,result:{tabId:42,url:'https://chatgpt.com/c/article'}}:{ok:false,error:'Click the Relay toolbar icon in ChatGPT first.'};}
  if(value.type==='chatgpt-insert'){crossInserts++;assert.equal(value.waitForReady,true);assert.equal(storage.panel.handoff.state,'inserting','Insertion intent is retained before the external effect');if(crossMode==='auto-lost')return{ok:false,error:'Controlled lost insertion reply'};if(crossMode==='auto')return{ok:true,result:{url:'https://chatgpt.com/',inserted:true}};throw Error('Unexpected insertion during manual article handoff');}
  if(value.type==='chatgpt-response'){crossReads++;assert.equal(value.handoff.attachmentTabId,42);if(crossMode==='manual')return{ok:false,error:'Attachment response requires manual import.',code:'request_in_attachment'};return{ok:true,result:{requestId:crossMode==='wrong'?'another-request':value.handoff.requestId,response:JSON.stringify({...fixture.answer,work_changes:[]}),url:'https://chatgpt.com/c/article',messageId:'article-result',requestVerification:crossMode==='attached'?'attachment-response-marker':'exact-visible-request'}};}
  return{ok:false,error:'Unexpected action'};
 };
 await click(ids.get('make-now'));const articleTicket=structuredClone(storage.panel.handoff);
 assert.equal(articleTicket.unbound,true);assert.equal(articleTicket.state,'copied');assert.equal(destinationOpens,1);assert.equal(crossInserts,0);assert.equal(crossReads,0);assert.equal(clipboard.at(-1),articleTicket.request);assert(articleTicket.request.includes(fixture.capture.url));assert.equal(ids.get('get-chatgpt-result').hidden,false);
 await click(ids.get('get-chatgpt-result'));assert.equal(crossReads,0);assert.deepEqual(storage.panel.handoff,articleTicket,'No destination permission keeps the exact ticket');
 destinationReady=true;await click(ids.get('get-chatgpt-result'));assert.deepEqual(storage.panel.handoff,articleTicket,'An unrelated response does not bind or replace the source');
 const inspectionsBeforeReopen=crossInspections;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-article');assert.equal(crossInspections,inspectionsBeforeReopen);assert.equal(destinationOpens,1,'Reopening the panel does not navigate or inspect automatically');
 // Simulate the old misclassification retained in session storage. A completed
 // attached reply must still download, with no restoration or second request.
 storage.panel.handoff.needsRestore=true;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-attached');
 assert.equal(ids.get('get-chatgpt-result').textContent,'Download Skill','Old restoration flags never rename the download control');crossMode='manual';await click(ids.get('get-chatgpt-result'));assert.equal(storage.panel.handoff.needsRestore,undefined);assert.equal(storage.panel.handoff.manualReplyNeeded,true);assert.equal(crossInserts,0);assert(!htmlIds.has('paste-reply'),'Reply import belongs only in Options');
 crossMode='attached';await click(ids.get('get-chatgpt-result'));assert.equal(storage.panel.handoff.state,'reviewed');assert.equal(storage.panel.handoff.needsRestore,undefined);assert.equal(storage.panel.handoff.tabId,42);assert.equal(storage.panel.handoff.unbound,undefined);assert.equal(storage.panel.capture.url,fixture.capture.url);assert(downloads.at(-1).name.endsWith('.skill.zip'));assert.equal(crossInserts,0);assert(storage.panel.capture.source_metadata.limitations.some(v=>v.includes('attached text could not be verified')));assert(ids.get('review-intro').textContent.includes('could not be verified'));
 await click(ids.get('new-text'));destinationReady=false;loseOpen=true;await click(ids.get('make-now'));const uncertainOpen=structuredClone(storage.panel.handoff);assert.equal(uncertainOpen.openAttempted,true);const openingCount=destinationOpens;
 await click(ids.get('open-chatgpt'));await click(ids.get('make-now'));assert.equal(destinationOpens,openingCount,'A lost tab-opening reply is not repeated');assert.equal(storage.panel.handoff.requestId,uncertainOpen.requestId);
 // Clipboard failure offers manual copy without opening a tab or claiming it
 // copied a request. The source and previous session remain recoverable.
 await click(ids.get('new-text'));clipboardFails=true;await click(ids.get('make-now'));clipboardFails=false;assert.equal(destinationOpens,openingCount);assert.equal(storage.panel.handoff,null);assert.equal(ids.get('settings').hidden,false);assert.equal(ids.get('copy-prompt').hidden,false);assert(ids.get('analysis-prompt').value.includes('TASK_RELAY_REQUEST_'));
 // Autofill asks only for ChatGPT, in the explicit gesture, then opens and
 // prepares the retained draft without clipboard transport or a second click.
 assert.equal(chatgptPermissionRequests,1,'A denied optional origin is not requested repeatedly');grantChatGPT=true;await click(ids.get('enable-chatgpt'));assert.equal(chatgptPermission,true);assert.equal(ids.get('disable-chatgpt').hidden,false);
 const beforeAutoCopies=clipboard.length;clipboardFails=true;crossMode='auto';loseOpen=false;destinationReady=false;await click(ids.get('new-text'));await click(ids.get('make-now'));
 clipboardFails=false;assert.equal(storage.panel.handoff.state,'inserted');assert.equal(storage.panel.handoff.autofill,true);assert.equal(storage.panel.handoff.tabId,42);assert.equal(clipboard.length,beforeAutoCopies);assert.equal(crossInserts,1);assert(ids.get('handoff-status').textContent.includes('Press Send'));assert.equal(ids.get('settings').hidden,true,'Recovery buttons remain in hidden Options');
 await click(ids.get('open-chatgpt'));assert.equal(storage.panel.handoff.state,'inserted');assert.equal(crossInserts,1,'Returning to the known destination never repeats insertion');
 const beforeAutoReopen=crossInserts;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-autofill');assert.equal(crossInserts,beforeAutoReopen,'Panel reopening never edits or opens a tab');
 crossMode='auto-lost';await click(ids.get('new-text'));await click(ids.get('make-now'));assert.equal(storage.panel.handoff.state,'inserting');const afterUncertainAuto=crossInserts,opensAfterUncertainAuto=destinationOpens;await click(ids.get('make-now'));assert.equal(crossInserts,afterUncertainAuto);assert.equal(destinationOpens,opensAfterUncertainAuto,'Uncertain insertion/opening is never replayed implicitly');
 const beforeDisable=structuredClone(storage.panel);await click(ids.get('disable-chatgpt'));assert.equal(chatgptPermission,false);assert.deepEqual(storage.panel,beforeDisable,'Permission removal preserves the pending request and source');
 // Long file -> validated parts -> explicit next draft -> final map -> portable
 // export. This exercises actual panel persistence, not just planner helpers.
 await click(ids.get('forget'));let multipartInserts=0;
 chrome.runtime.sendMessage=async value=>{
   if(value.type==='capture')throw Error('A selected file must not capture a webpage');
   if(value.type==='chatgpt-inspect')return {ok:true,result:{tabId:71,url:'https://chatgpt.com/c/parts'}};
   if(value.type==='chatgpt-insert'){multipartInserts++;return {ok:true,result:{url:'https://chatgpt.com/c/parts',inserted:true}};}
   return {ok:false,error:'Unexpected multipart external action'};
 };
 const longBody=Array.from({length:1400},(_,i)=>`Evidence ${String(i).padStart(5,'0')}: this is a distinct observation and its stated qualification.\n`).join('');
 ids.get('text-file').files=[{name:'synthetic-history.md',size:longBody.length,async text(){return longBody;}}];await ids.get('text-file').onchange();await settle();
 await click(ids.get('make-job'));assert.equal(storage.panel.capture.extracted_content,longBody);assert(storage.panel.batch.parts.length>1);assert.equal(multipartInserts,1);assert.equal(storage.panel.batch.index,0);
 const firstTicket=storage.panel.handoff.requestId;
 const partAnswer=()=>{const part=storage.panel.batch.parts[storage.panel.batch.index],quote=longBody.slice(part.start,part.end).split('\n').find(s=>s.trim());return {skill_candidates:[],work_changes:[{...fixture.answer.work_changes[0],conclusions:[{text:'Reported observation',quote}],decision_proposals:[],questions:[],next_actions:[],artifact_references:[]}],work_graph:{nodes:[{key:'finding',kind:'finding',label:'Reported observation',status:'reported',quote}],edges:[]}};};
 ids.get('answer').value=JSON.stringify(partAnswer());const sessionSet=chrome.storage.session.set;let failPartSave=true;chrome.storage.session.set=async value=>{if(failPartSave){failPartSave=false;throw Error('Controlled session quota failure');}return sessionSet(value);};
 await click(ids.get('review-answer'));assert.equal(storage.panel.batch.index,0);assert.equal(storage.panel.handoff.requestId,firstTicket);assert(ids.get('status').textContent.includes('no next part'));chrome.storage.session.set=sessionSet;
 await click(ids.get('review-answer'));assert.equal(storage.panel.batch.index,1);assert.equal(multipartInserts,1,'Reading a reply does not prepare or send the next part');
 const progress={format:'task-relay-text-progress',version:1,pending_handoff:null,source_sha256:await portable.sha(longBody),capture:structuredClone(storage.panel.capture),batch:structuredClone(storage.panel.batch)};
 const beforeRestoreInsert=multipartInserts;ids.get('open-files').files=[{name:'progress.json',size:JSON.stringify(progress).length,async text(){return JSON.stringify(progress);}}];await ids.get('open-files').onchange();await settle();assert.equal(multipartInserts,beforeRestoreInsert,'Progress import never replays a request');assert.equal(storage.panel.batch.index,1);assert.equal(storage.panel.handoff,null);
 while(storage.panel.batch.phase==='parts'){
   await click(ids.get('next-part'));assert.notEqual(storage.panel.handoff.requestId,firstTicket);assert(storage.panel.handoff.request.length<180000);
   const beforeIndex=storage.panel.batch.index,answer=partAnswer(),bad=structuredClone(answer);bad.work_graph.nodes[0].quote='Invented evidence absent from this source';ids.get('answer').value=JSON.stringify(bad);await click(ids.get('review-answer'));assert.equal(storage.panel.batch.index,beforeIndex);
   ids.get('answer').value=JSON.stringify(answer);await click(ids.get('review-answer'));assert.equal(storage.panel.batch.index,beforeIndex+1);
 }
 // Export/import an uncertain pending draft without giving it resend authority.
 const finalPending={format:'task-relay-text-progress',version:1,pending_handoff:{requestId:firstTicket,request:'TASK_RELAY_REQUEST_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\nRetained request'},source_sha256:await portable.sha(longBody),capture:structuredClone(progress.capture),batch:structuredClone(progress.batch)};
 finalPending.pending_handoff.requestId='TASK_RELAY_REQUEST_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
 const completedParts=structuredClone(storage.panel);
 ids.get('open-files').files=[{name:'pending.json',size:JSON.stringify(finalPending).length,async text(){return JSON.stringify(finalPending);}}];await ids.get('open-files').onchange();await settle();assert.equal(storage.panel.handoff.readOnlyRecovery,true);const pendingInserts=multipartInserts;await click(ids.get('insert-chatgpt'));await click(ids.get('next-part'));assert.equal(multipartInserts,pendingInserts,'Imported uncertain requests cannot be resent');
 storage.panel=completedParts;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-after-uncertain-progress');
 assert.equal(storage.panel.batch.phase,'synthesis');const beforeReopen=multipartInserts;ids.clear();await import(require('node:url').pathToFileURL(path.join(root,'extensions/chrome/panel.js')).href+'?restore-multipart');assert.equal(multipartInserts,beforeReopen);assert.equal(ids.get('next-part').textContent,'Prepare final result');
 await click(ids.get('next-part'));const quote=progress.batch.receipts[0].answer.work_changes[0].conclusions[0].quote;
 ids.get('answer').value=JSON.stringify({skill_candidates:[],work_changes:[{...fixture.answer.work_changes[0],conclusions:[{text:'Final synthesis',quote}],decision_proposals:[],questions:[],next_actions:[],artifact_references:[]}]});await click(ids.get('review-answer'));assert.equal(storage.panel.batch.phase,'done');assert.equal(storage.panel.proposals.map.nodes.length,storage.panel.batch.parts.length);assert.equal(ids.get('review-view').hidden,false);
 assert(button(ids.get('proposal-items'),'Map'));await click(button(ids.get('proposal-items'),'Download work'));assert(downloads.at(-1).name.endsWith('.relay.md'));assert(storage.panel.opened[0].content.includes('```task-relay-map'));assert.equal(storage.panel.proposals.map.sources[0].content,longBody);
 const mapTabs=[],beforeMapDownload=downloads.length;chrome.runtime.getURL=p=>'chrome-extension://fixture/'+p;chrome.tabs={async create(value){mapTabs.push(value);}};await click(button(ids.get('proposal-items'),'Open full map'));assert.equal(mapTabs.at(-1).url,'chrome-extension://fixture/map.html');assert.deepEqual(storage.mapPreview,storage.panel.proposals.map);assert.equal(downloads.length,beforeMapDownload,'Opening a map never downloads an SVG automatically');
 const finalProgress={format:'task-relay-text-progress',version:1,pending_handoff:null,source_sha256:await portable.sha(longBody),capture:structuredClone(storage.panel.capture),batch:structuredClone(storage.panel.batch)};const beforeCompletedImport=multipartInserts;
 ids.get('open-files').files=[{name:'completed.json',size:JSON.stringify(finalProgress).length,async text(){return JSON.stringify(finalProgress);}}];await ids.get('open-files').onchange();await settle();assert.equal(storage.panel.batch.phase,'done');assert.equal(multipartInserts,beforeCompletedImport,'Completed progress reopens its final result without another synthesis request');assert(storage.panel.proposals.map);
 console.log(JSON.stringify({result:'passed',scope:'Portable panel, optional permissions/recovery, actual Python bridge, exports/continuation, worker gates and ChatGPT handoff: explicit preparation/insertion, retained uncertain ticket, access errors, destination-bound attachment reply matching with disclosed verification limits, old cleared-draft recovery, no automatic retry, failed import preservation and no autosave',live_chrome:false,live_provider:false}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{global.setTimeout=realTimeout;fs.rmSync(folder,{recursive:true,force:true});});
