// Thin extractor fixtures. These are DOM doubles, not live site qualification.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('extensions/chrome/extract.js','utf8').replace('export function','function')+'\ntaskRelayCapture(selectionOnly)';
function element(tag='div',text='',flags={}){
 const el={tagName:tag.toUpperCase(),parentElement:null,flags,nodes:[],getClientRects(){return flags.noRect?[]:[{}];},
 closest(selector){let cur=this;while(cur){if(cur.flags.form&&selector.includes('form')||cur.flags.excluded&&selector.includes('script')||cur.flags['aria-hidden']==='true'&&selector.includes('[aria-hidden="true"]')||cur.flags.inert&&selector.includes('[inert]'))return cur;cur=cur.parentElement;}return null;},getAttribute(name){return flags[name];},matches(selector){return flags.match===selector;}};
 if(text)el.nodes.push({textContent:text,parentElement:el});return el;
}
function child(parent,el){el.parentElement=parent;parent.nodes.push(...el.nodes);return el;}
function execute({host='docs.example.test',text='Useful page',selection=null,messages=[],modernHeaders=[],flags={},selectionBad=false,selectedExtras=[],selectionOnly=false,startOffset=0,endOffset}){
 const body=element('body'),main=child(body,element('main',text,flags));
 child(main,element('nav','Do not collect navigation',{excluded:true}));child(main,element('input','Do not collect passwords',{excluded:true}));child(main,element('div','Do not collect hidden',{display:'none'}));
 for(const el of selectedExtras)child(main,el);
 body.nodes=main.nodes;
 const walk=root=>{let i=0;return{nextNode(){return root.nodes[i++]||null;}};};
 const nodes=selectionBad?main.nodes:main.nodes.filter(n=>n.parentElement===main||selectedExtras.includes(n.parentElement));
 class TextRange{
  selectNodeContents(n){this.startContainer=this.endContainer=n;this.startOffset=0;this.endOffset=n.textContent.length;}
  setStart(n,o){this.startContainer=n;this.startOffset=o;}setEnd(n,o){this.endContainer=n;this.endOffset=o;}
  get collapsed(){return this.startContainer===this.endContainer&&this.startOffset===this.endOffset;}
  compareBoundaryPoints(how,r){const end=how===2;const a=body.nodes.indexOf(this[end?'endContainer':'startContainer'])*100000+this[end?'endOffset':'startOffset'];const b=body.nodes.indexOf(r[end?'endContainer':'startContainer'])*100000+r[end?'endOffset':'startOffset'];return Math.sign(a-b);}
  toString(){const start=body.nodes.indexOf(this.startContainer),end=body.nodes.indexOf(this.endContainer);return body.nodes.slice(start,end+1).map((n,i)=>n.textContent.slice(i===0?this.startOffset:0,start+i===end?this.endOffset:undefined)).join('');}
 }
 const range=new TextRange();range.setStart(nodes[0],startOffset);range.setEnd(nodes.at(-1),endOffset??nodes.at(-1).textContent.length);range.intersectsNode=n=>nodes.includes(n);
 const selected=selection===null?{isCollapsed:true}:{isCollapsed:false,rangeCount:1,toString:()=>selection,getRangeAt:()=>range};
 const document={body,title:'A controlled page',createTreeWalker:walk,createRange:()=>new TextRange(),querySelector:()=>main,querySelectorAll:selector=>selector==='[data-turn-key] h4.sr-only'?modernHeaders:messages};
 const location={hostname:host,href:'https://'+host+'/test'};
 return vm.runInNewContext(code,{document,location,selectionOnly,window:{getSelection:()=>selected},NodeFilter:{SHOW_TEXT:4},URL,
   getComputedStyle:el=>({display:el.flags.display||(['SPAN','A','STRONG','SVG'].includes(el.tagName)?'inline':'block'),visibility:el.flags.visibility||'visible',opacity:el.flags.opacity??'1'})});
}
assert.match(execute({text:'x'.repeat(300001),selectionOnly:true}).captureError,/Select text/);
assert.equal(execute({selection:'Exact',selectionOnly:true}).selected_content,'Exact');
assert.equal(execute({text:'x'.repeat(60001)}).extracted_content.length,60001,'Longer text is retained intact');
const page=execute({text:'Useful page'});assert.equal(page.extracted_content,'Useful page');assert.equal(page.source_type,'page');
const selected=execute({text:'larger page',selection:'  Exact selected text\nwith spacing  '});assert.equal(selected.selected_content,'  Exact selected text\nwith spacing  ');assert.equal(selected.source_type,'selection');
const filtered=execute({text:'Visible paragraph',selection:'Visible paragraph hidden selection',selectionBad:true});assert.equal(filtered.selected_content,'Visible paragraph');assert(filtered.source_metadata.limitations.some(s=>s.includes('were excluded')));
assert.match(execute({text:'x'.repeat(300001)}).captureError,/nothing was truncated/);
const cited='Selected answer\nwith citations';
assert.equal(execute({selection:cited,selectedExtras:[element('span','+1',{'aria-hidden':'true'}),element('a','https://evidence.example.test',{inert:true}),element('svg','  ',{excluded:true,noRect:true})]}).selected_content,cited,'Rendered citation labels/links and empty SVG whitespace must not reject or rewrite the exact selection');
assert.equal(execute({text:'Visible',selection:'Visible and hidden',selectedExtras:[element('span','Hidden',{display:'none'})]}).selected_content,'Visible');
const mixed=execute({text:'First paragraph',selection:'First paragraph Copy Hidden Second paragraph',selectedExtras:[element('button','Copy',{excluded:true}),element('span','Hidden',{display:'none'}),element('p','Second paragraph')]});assert.equal(mixed.selected_content,'First paragraph\nSecond paragraph');
assert.equal(execute({text:'prefix Visible',selection:'Visible Hidden',startOffset:7,selectedExtras:[element('span','Hidden',{display:'none'})]}).selected_content,'Visible','Filtering retains partial selection offsets');
assert.match(execute({selection:'Visible and form',selectedExtras:[element('div','Private draft',{form:true})]}).captureError,/input field/);
assert.equal(execute({text:'Public text',selection:'Public text',selectedExtras:[element('div','Private draft',{form:true})],endOffset:0}).selected_content,'Public text','A zero-length endpoint touching a field is not selected content');
assert.match(execute({flags:{display:'none'},selection:'hidden'}).captureError,/No readable/);
assert.match(execute({text:'x'.repeat(300001),selection:'x'.repeat(300001),selectedExtras:[element('span','Hidden',{display:'none'})]}).captureError,/nothing was truncated/);
for(const [host,user,assistant,adapter] of [
 ['chatgpt.com',element('div','Ask Brazil',{'data-message-author-role':'user'}),element('div','Answer Brazil',{'data-message-author-role':'assistant'}),'chatgpt'],
 ['claude.ai',element('div','Ask Brazil',{match:'[data-testid="user-message"]'}),element('div','Answer Brazil'),'claude'],
 ['gemini.google.com',element('user-query','Ask Brazil'),element('model-response','Answer Brazil'),'gemini'],
 ['www.perplexity.ai',element('div','Ask Brazil',{match:'[data-testid="user-query"]'}),element('div','Answer Brazil'),'perplexity']]) {
 const result=execute({host,messages:[user,assistant]});assert.equal(result.source_metadata.adapter,adapter);assert(result.extracted_content.includes('user:\nAsk Brazil'));assert(result.extracted_content.includes('assistant:\nAnswer Brazil'));
}
const fallback=execute({host:'claude.ai'});assert.equal(fallback.source_metadata.adapter,'generic');assert(fallback.source_metadata.limitations.some(s=>s.includes('roles are unavailable')));
const modernHeaders=[['You said:',null,'Compare primary sources'],['ChatGPT said:','assistant','Evidence is still a proposal']].map(([label,role,body])=>{const parent=element('div',body),heading=element('h4','',{excluded:true,'data-conversation-role':role});heading.textContent=label;child(parent,heading);child(parent,element('button','Copy',{excluded:true}));return heading;});
const modern=execute({host:'chatgpt.com',modernHeaders});assert.equal(modern.source_metadata.adapter,'chatgpt');assert.equal(modern.extracted_content,'user:\nCompare primary sources\n\nassistant:\nEvidence is still a proposal');
console.log(JSON.stringify({result:'passed',scope:'Generic, exact selection, hidden/form exclusion, budgets, four synthetic AI-site adapters and current ChatGPT Work role boundaries without control text',live_sites:false}));
