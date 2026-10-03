// Execute the actual serialized tab function with small DOM fixtures. No model,
// account, message sending or installed-browser qualification is implied.
const assert=require('node:assert/strict'),vm=require('node:vm'),path=require('node:path');
class El {
  constructor(tag='DIV',content=''){this.tagName=tag;this.innerText=content;this.textContent=content;this.attrs={};this.hidden=false;this.children={};this.events=[];}
  getAttribute(key){return this.attrs[key]??null;}
  closest(selector){if(selector.includes('[hidden]'))return this.hidden?this:null;if(selector==='form')return this.form||null;if(selector==='pre')return this.pre||null;return null;}
  getClientRects(){return this.hidden?[]:[{}];}
  querySelectorAll(selector){return this.children[selector]||[];}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  focus(){this.focused=true;}
  dispatchEvent(event){this.events.push(event.type);}
}
class TextArea extends El {constructor(){super('TEXTAREA');this._value='';}get value(){return this._value;}set value(v){this._value=v;}}
const role=(name,content)=>{const el=new El('DIV',content);el.attrs['data-message-author-role']=name;return el;};
(async()=>{
 const {chatgptHandoff}=await import(path.resolve(__dirname,'../extensions/chrome/chatgpt.js'));
 const portable=await import(path.resolve(__dirname,'../extensions/chrome/portable.js'));
 const id='TASK_RELAY_REQUEST_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',marker=id.replace('REQUEST','RESPONSE');
 const payload={requestId:id,request:id+'\nPrepare reusable work.\nExact evidence.',url:'https://chatgpt.com/c/test'};
 let composer,rows,stream,edits,attachment,editorFailure,href;
  let modern=false;
  const document={querySelectorAll(selector){if(selector==='#prompt-textarea,[data-composer-markdown][contenteditable="true"][role="textbox"]')return[composer];if(selector==='[data-message-author-role]')return modern?[]:rows;if(selector==='[data-turn-key] h4.sr-only')return modern?rows.map(row=>row.heading):[];return stream?[stream]:[];},
   createRange(){return{selectNodeContents(){}};},execCommand(command,ui,content){assert.equal(command,'insertText');edits++;composer.innerText=content;composer.textContent=content;return !editorFailure;}};
 const context=vm.createContext({document,location:{get href(){return href;}},URL,TextEncoder,HTMLTextAreaElement:TextArea,Event:class{constructor(type){this.type=type;}},
   window:{getSelection(){return{removeAllRanges(){},addRange(){}};}},getComputedStyle(el){return{display:el.display||'block',visibility:'visible',opacity:'1'};}});
 const injected=vm.runInContext('('+chatgptHandoff.toString()+')',context);
 const tab=(...args)=>{const result=injected(...args);if(result.handoffError)throw Error(result.handoffError);return result;};
 function reset(editable=false){composer=editable?new El():new TextArea();if(editable)composer.attrs.contenteditable='true';rows=[];stream=null;edits=0;attachment=null;editorFailure=false;href=payload.url;}
 reset();assert.equal(tab('inspect').adapter,'chatgpt');assert.equal(composer.value,'');
 composer.value='An important unsent draft';assert.throws(()=>tab('insert',payload),/draft was preserved/);assert.equal(composer.value,'An important unsent draft');
 composer.value='';assert.equal(tab('insert',payload).inserted,true);assert.equal(composer.value,payload.request);assert.deepEqual(composer.events,['input']);
 assert.equal(tab('insert',payload).reused,true);assert.equal(composer.events.length,1,'Retry reuses the exact draft without another edit');
 composer.value='';assert.throws(()=>tab('response',payload),/Send the message/);assert.equal(composer.value,'','Result retrieval never restores a deleted draft implicitly');
 assert.equal(tab('insert',payload).inserted,true);assert.equal(composer.value,payload.request,'Explicit restoration returns the exact deleted request');assert.equal(composer.events.length,2);
 composer.value='My replacement draft';assert.throws(()=>tab('insert',payload),/draft was preserved/);assert.equal(composer.value,'My replacement draft');
 reset();const oldId='TASK_RELAY_REQUEST_11111111-2222-3333-4444-555555555555';const old={requestId:oldId,request:oldId+'\nOld request',url:payload.url};composer.value=old.request;
 assert.equal(tab('insert',{...payload,replaceDraft:old}).inserted,true);assert.equal(composer.value,payload.request);
 composer.value=old.request+' edited';assert.throws(()=>tab('insert',{...payload,replaceDraft:old}),/draft was preserved/);
 composer.value=old.request;assert.throws(()=>tab('insert',{...payload,replaceDraft:{...old,url:'https://chatgpt.com/c/other'}}),/draft was preserved/);
 const oldPortable={...old,request:oldId+'\nRelay request\n\n'+JSON.stringify({capture:{content:'selected'},existing_work:null})};composer.value=oldPortable.request;
 assert.equal(tab('inspect').existingDraft.request,oldPortable.request,'Explicit New can retain an owned draft after reload');composer.value='My ordinary draft';assert.equal(tab('inspect').existingDraft,undefined);
 reset(true);assert.equal(tab('insert',payload).inserted,true);assert.equal(edits,1);assert.equal(composer.innerText,payload.request);
 reset(true);editorFailure=true;assert.throws(()=>tab('insert',payload),/did not accept/);assert.equal(composer.innerText,payload.request);
 editorFailure=false;assert.equal(tab('insert',payload).reused,true);assert.equal(edits,1,'An uncertain editor acknowledgement never duplicates the edit');
 reset();composer.form=new El('FORM');composer.form.children['[data-testid*="attachment"],[data-testid*="file"],button[aria-label^="Remove"]']=[new El()];assert.throws(()=>tab('insert',payload),/attachment/);assert.equal(composer.value,'');
 reset();stream=new El();assert.throws(()=>tab('insert',payload),/still responding/);assert.equal(composer.value,'');
 reset();href='https://claude.ai/chat/test';assert.throws(()=>tab('inspect'),/Open a ChatGPT/);
 href='https://chatgpt.com/c/other';assert.throws(()=>tab('insert',payload),/conversation changed/);
 reset();assert.throws(()=>tab('response',payload),/Send the message/);
 const recovery=JSON.parse(JSON.stringify(injected('response',payload)));assert(recovery.handoffError.includes('Send the message'));assert.equal(recovery.handoffCode,'draft_missing');assert.equal(recovery.url,payload.url,'Recovery error survives the serialized injection boundary');
 rows=[role('user',payload.request)];assert.throws(()=>tab('insert',payload),/already in the conversation/);assert.equal(composer.value,'');assert.throws(()=>tab('response',payload),/No response/);
 const json=JSON.stringify({skill_candidates:[],work_changes:[]});
 const answer=role('assistant',marker+'\njson\nCopy code\n'+json),body=new El('DIV',answer.innerText),p=new El('P',marker),code=new El('CODE',json);
 code.pre=new El('PRE');body.children['p']=[p];body.children['pre code,code[class*="CodeContent-"]']=[code];answer.children['.markdown']=[body];answer.attrs['data-message-id']='matching-result';rows.push(answer);
 stream=new El();assert.throws(()=>tab('response',payload),/still responding/);stream=null;
 const result=tab('response',payload);assert.equal(result.messageId,'matching-result');assert(result.response.includes('```json'));assert(!result.response.includes('Copy code'));assert.deepEqual(portable.importResponse(result.response),JSON.parse(json));
 rows.push(role('user','An unrelated follow-up'));assert.throws(()=>tab('response',payload),/later user message/);rows.pop();
 rows.unshift(role('user',payload.request));assert.throws(()=>tab('response',payload),/Several matching/);rows.shift();
 rows[0]=role('user',payload.request+' altered');assert.throws(()=>tab('response',payload),/collapsed or edited/);assert.throws(()=>tab('insert',payload),/already in the conversation/);rows[0]=role('user',payload.request);
 body.children['p']=[new El('P','A different response marker')];assert.throws(()=>tab('response',payload),/did not identify/);body.children['p']=[p];
 body.children['pre code,code[class*="CodeContent-"]']=[code,new El('CODE',json)];assert.throws(()=>tab('response',payload),/Several response blocks/);body.children['pre code,code[class*="CodeContent-"]']=[code];
 rows.push(role('assistant','Another response'));assert.throws(()=>tab('response',payload),/Several response sections/);rows.pop();
 code.textContent='{"skill_candidates":';assert.throws(()=>portable.importResponse(tab('response',payload).response),/complete response/);code.textContent=json;
 code.textContent='x'.repeat(240001);assert.throws(()=>tab('response',payload),/too large/);code.textContent=json;
 href='https://chatgpt.com/c/newly-created';assert.throws(()=>tab('response',payload),/conversation changed/);
 assert.equal(tab('response',{...payload,url:'https://chatgpt.com/'}).messageId,'matching-result','A new chat may acquire its ID only with an exact matching request');
 rows=[];assert.throws(()=>tab('response',{...payload,url:'https://chatgpt.com/'}),/Send the message/);
 // Current live Work markup: no composer ID, role headings, rendered code
 // without pre, and user controls outside the paragraph content.
 reset(true);modern=true;composer.attrs['data-composer-markdown']='';composer.attrs.role='textbox';assert.equal(tab('insert',payload).inserted,true);
 const user=new El('DIV','You said:\n'+payload.request+'\nShow less'),userHeading=new El('H4','You said:');userHeading.parentElement=user;user.heading=userHeading;user.children.p=[new El('P',payload.request)];
 const modernAnswer=new El('DIV','ChatGPT said:\n'+marker+'\njson\nCopy\n'+json),assistantHeading=new El('H4','ChatGPT said:');assistantHeading.attrs['data-conversation-role']='assistant';assistantHeading.parentElement=modernAnswer;modernAnswer.heading=assistantHeading;
 modernAnswer.attrs['data-chatgpt-search-message-ids']='modern-result';modernAnswer.children.p=[new El('P',marker)];modernAnswer.children['pre code,code[class*="CodeContent-"]']=[new El('CODE',json)];rows=[user,modernAnswer];
 assert.equal(tab('response',payload).messageId,'modern-result');assert.deepEqual(portable.importResponse(tab('response',payload).response),JSON.parse(json));
 user.children.p=[new El('P',payload.request.slice(0,60)+'…')];assert.throws(()=>tab('insert',payload),/already in the conversation/);assert.throws(()=>tab('response',payload),/collapsed or edited/);
 const recoveredContext={capture:{content:'Exact evidence.',url:'https://example.test/evidence'},existing_work:null,selected_skill:null};
 const recoveryRequest=id+'\nReply with '+marker+'\n\n'+JSON.stringify(recoveredContext);
 const header=new El('P',id+'\nReply with '+marker),inline=new El('P',JSON.stringify(recoveredContext));
 inline.innerText=inline.textContent.replace('https://','\nhttps://');
 const sourceUrl=recoveredContext.capture.url,parts=inline.textContent.split(sourceUrl),link=new El('A',sourceUrl),decoration=new El('SPAN','Copy');
 link.nodeType=1;link.attrs['aria-hidden']='true';link.attrs.inert='';decoration.nodeType=1;decoration.attrs['data-markdown-copy']='exclude';
 inline.childNodes=[{nodeType:3,textContent:parts[0]},link,decoration,{nodeType:3,textContent:parts[1]}];
 user.children.p=[header,inline];
 user.display='contents';user.getClientRects=()=>[];user.children['*']=[header,inline];
 assert.equal(tab('response',{...payload,request:recoveryRequest}).messageId,'modern-result','Display-contents message wrappers and inline link layout must preserve request identity');
 const restored=tab('recover');assert.equal(restored.requestId,id);assert.equal(restored.recoveredContext.capture.url,recoveredContext.capture.url);assert.equal(edits,1,'Recovery never inserts or sends');
 user.children.p=[new El('P','A later unrelated message')];assert.throws(()=>tab('recover'),/No recoverable/);user.children.p=[header,inline];
 inline.childNodes=[];inline.textContent='{incomplete';assert.throws(()=>tab('recover'),/collapsed or incomplete/);
 console.log(JSON.stringify({result:'passed',scope:'Serialized ChatGPT adapter: legacy and current Work markup, preserved drafts/attachments, editor recovery, collapsed-request deduplication, exact request/reply matching, rendered code extraction, incomplete/ambiguous/streaming replies and conversation boundaries',live_chrome:false,live_ai:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
