/* Proposals and selected files live only in this panel. Saving is always explicit. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const node = (tag, content, cls) => { const n = document.createElement(tag); if (content !== undefined) n.textContent = content; if (cls) n.className = cls; return n; };
  const compact = d => ({kind:d.kind, files:d.files.map(f => ({path:f.path, content:f.content}))});
  let connected = false, currentView = 'skill', packet = null, hostContext = {}, rpcID = 0, contextRevision = 0;
  const documents = new Map(), selected = new Set(), recents = [], pending = new Map();
  const status = (message, error = false) => { $('status').textContent = message; $('status').className = error ? 'error' : ''; $('status').hidden=!message; };
  const notify = (method, params) => window.parent.postMessage({jsonrpc:'2.0', method, params}, '*');
  const rpc = (method, params) => new Promise((resolve, reject) => {
    const id = ++rpcID;
    const timer = setTimeout(() => { pending.delete(id); reject(Error('The connection did not respond. Your review text is still here; no file was saved.')); }, 20000);
    pending.set(id, {resolve, reject, timer});
    window.parent.postMessage({jsonrpc:'2.0', id, method, params}, '*');
  });
  const perform = async (button, action) => {
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try { await action(); } catch (error) { status(error.message || 'Task Relay could not complete the request.', true); }
    finally { if (button) button.disabled = false; }
  };
  const tool = async (name, args) => {
    const result = window.openai?.callTool ? await window.openai.callTool(name, args) : await rpc('tools/call', {name, arguments:args});
    if (result.isError) throw Error(result.content?.find(x=>x.type==='text')?.text || 'The selected file or proposal is invalid.');
    return result;
  };
  const action = (label, fn, cls) => { const b = node('button', label, cls); b.type = 'button'; b.onclick = () => perform(b, () => fn(b)); return b; };
  const encoded = bytes => { let value = ''; for (let i=0; i<bytes.length; i+=8192) value += String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(value); };
  const selectedDocuments = () => [...selected].map(k=>documents.get(k)).filter(Boolean);
  function showView(view) {
    $('welcome').hidden=view!=='home'; $('proposal-section').hidden=view!=='review';
    $('reuse-section').hidden=view!=='reuse'; $('back-home').hidden=view==='home';
    $('review-pending').hidden=!$('proposals').children.length;
  }
  function invalidateContext() { contextRevision++; packet = null; $('context-section').hidden = true; }
  function addDocument(d, choose = true) {
    documents.set(d.sha256, d);
    if (choose) { for (const key of selected) if (documents.get(key)?.kind === d.kind) selected.delete(key); selected.add(d.sha256); }
    invalidateContext(); renderDocuments();
  }
  function renderDocuments() {
    $('selected-files').replaceChildren();
    selectedDocuments().forEach(d=>$('selected-files').append(documentRow(d)));
    $('reuse-request').hidden=!selected.size;
    $('update-work').hidden=!selectedDocuments().some(d=>d.kind==='work');
    $('improve-skill').hidden=!selectedDocuments().some(d=>d.kind==='skill');
    $('file-catalog').hidden=!documents.size;
    $('documents').replaceChildren();
    for (const [kind, id] of [['skill','view-skills'],['work','view-work'],['recent','view-recent']]) $(id).setAttribute('aria-pressed', String(kind===currentView));
    if (currentView === 'recent') {
      $('catalog-note').textContent = 'Recent exports from this panel only. A new chat starts with files you select.';
      for (const r of recents) $('documents').append(node('p', `${r.filename} · ${r.destination}`));
      if (!recents.length) $('documents').append(node('p', 'No exports in this panel yet.', 'muted'));
      return;
    }
    $('catalog-note').textContent = 'Files remain yours. Open them again in a new chat; this panel does not search your Library.';
    const visible = [...documents.values()].filter(d=>d.kind===currentView);
    for (const d of visible) {
      const row=documentRow(d);
      const details = node('details'); details.append(node('summary', 'Inspect selected file'));
      for (const f of d.files) details.append(node('h3', f.path), node('pre', f.content));
      row.append(details); $('documents').append(row);
    }
    if (!visible.length) $('documents').append(node('p', currentView==='skill' ? 'Select a saved Skill to reuse its instructions.' : 'Select a work snapshot to pick up its current state.', 'muted'));
  }
  function documentRow(d) {
    const row=node('div',undefined,'document-row'),label=node('label'),checkbox=node('input');
    checkbox.type='checkbox'; checkbox.checked=selected.has(d.sha256);
    checkbox.onchange=()=>{if(checkbox.checked){for(const key of selected)if(documents.get(key)?.kind===d.kind)selected.delete(key);selected.add(d.sha256);}else selected.delete(d.sha256);invalidateContext();renderDocuments();};
    label.append(checkbox,node('span',d.title)); row.append(label,node('p',d.kind==='work'?`Work snapshot · revision ${d.revision}`:'Skill · reusable instructions','muted small'));
    return row;
  }
  function receive(result) {
    const data = result?.structuredContent;
    if (!data) return;
    if (data.candidates) renderProposals(data);
    if (data.documents) { data.documents.forEach(d=>addDocument(d)); if (data.documents.length) { currentView=data.documents[0].kind; renderDocuments(); showView('reuse'); } }
    if (data.packet) { packet=data.packet; $('context-preview').textContent=packet; $('context-section').hidden=false; }
    if (data.message && !['home','review'].includes(data.view)) status(data.message);
  }
  function renderProposals(data) {
    // Never discard an in-progress edit when another tool result arrives.
    if ($('proposals').children.length) {
      const note = node('p', 'Another proposal is ready below. Existing review text is preserved.', 'muted'); $('proposals').append(note);
    }
    showView('review');
    for (const candidate of data.candidates) {
      const card=node('section', undefined, 'card'), type=candidate.kind;
      card.append(node('span', type==='skill' ? 'Skill' : 'Work snapshot', 'badge'), node('h2',candidate.title));
      card.append(node('p',type==='skill'?'Instructions you can use for similar tasks.':'Your conclusions, open questions and next steps.','muted'));
      const controls=node('div',undefined,'actions'), editor=node('div',undefined,'proposal-editor'); editor.hidden=true;
      const fields=[],editDetails=node('details'); editDetails.append(node('summary','Edit the file'));
      for (const f of candidate.files) {
        const preview=node('div',undefined,'review-text'); renderReviewText(preview,f.content);
        if(f.path==='SKILL.md'||type==='work')editor.append(preview);
        else {const resource=node('details');resource.append(node('summary',f.path),preview);editor.append(resource);}
        const label=node('label',f.path), input=node('textarea'); input.value=f.content; input.maxLength=240000;
        label.append(input); editDetails.append(label); fields.push({path:f.path,input,preview});
      }
      editor.append(editDetails);
      if (candidate.base) {
        const before=node('details'); before.append(node('summary',type==='skill'?'Compare with the selected Skill':'Compare with the selected work'));
        candidate.base.files.forEach(f=>before.append(node('h3',f.path),node('pre',f.content))); editor.append(before);
      }
      let exported=null, edited=false, editRevision=0, ignored=false;
      for (const field of fields) field.input.oninput=()=>{editRevision++; edited=true; exported=null; renderReviewText(field.preview,field.input.value);};
      const showReview=()=>{editor.hidden=false; review.hidden=true; status('Read this file, then choose where to save it. You can edit it first.');};
      async function prepareExport(){
        if(editor.hidden) {showReview();return null;}
        if (!exported) {
          const args={document:{kind:type,files:fields.map(f=>({path:f.path,content:f.input.value}))},confirmed:true};
          if (candidate.base) args.base=compact(candidate.base);
          const reviewedRevision=editRevision;
          const result=await tool('relay_review_export',args);
          if (ignored) return null;
          if (reviewedRevision!==editRevision) {
            status('Your review changed while the file was being prepared. Read the current text and save again.'); return null;
          }
          exported={...result._meta?.export,document:result.structuredContent?.document};
          if (!exported.data_base64) throw Error('This host did not provide the download. Your review text is preserved.');
        }
        return exported;
      }
      const destinations=node('div',undefined,'actions');
      destinations.append(action('Download',async()=>{const file=await prepareExport();if(file)downloadFile(file);},'primary'));
      if(window.openai?.uploadFile)destinations.append(action('Save to ChatGPT',async()=>{const file=await prepareExport();if(file)await saveToChatGPT(file);}));
      editor.append(node('p','Keep this file to use it in a new chat.','muted small'),destinations);
      const review=action('Review',showReview,'primary');
      controls.append(review,action('Ignore',()=>{ if (edited && !window.confirm('Discard this edited proposal?')) return; ignored=true; card.remove(); $('review-pending').hidden=!$('proposals').children.length; },'quiet'));
      card.append(controls,editor); $('proposals').append(card);
    }
  }
  function renderReviewText(target,content){
    target.replaceChildren();
    const body=content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/,'');
    for(const line of body.split('\n')){
      if(!line.trim())continue;
      const heading=line.match(/^#{1,6}\s+(.+)/);
      target.append(node(heading?'h3':'p',heading?heading[1]:line));
    }
  }
  function downloadFile(file) {
    const bytes=Uint8Array.from(atob(file.data_base64),c=>c.charCodeAt(0));
      const blob=new Blob([bytes],{type:file.mime_type}), url=URL.createObjectURL(blob), link=node('a');
      link.href=url; link.download=file.filename; document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),30000);
      addDocument(file.document); recents.unshift({filename:file.filename,destination:'Download requested'}); renderDocuments();
      status('Download requested. Keep this file to resume in a new chat.');
  }
  async function saveToChatGPT(file){
      const bytes=Uint8Array.from(atob(file.data_base64),c=>c.charCodeAt(0));
      try {
        const result=await window.openai.uploadFile(new File([bytes],file.filename,{type:file.mime_type}),{library:true});
        if (!result?.fileId) throw Error('The host did not return a file ID.');
        addDocument(file.document); recents.unshift({filename:file.filename,destination:'Uploaded to ChatGPT'}); renderDocuments();
        status('Uploaded to ChatGPT. Library placement depends on this account; keep a download for portability.');
      } catch (_) { status('ChatGPT could not save this export here. Your reviewed file is ready to Download.',true); }
  }
  async function send(message) {
    if (window.openai?.sendFollowUpMessage) { await window.openai.sendFollowUpMessage({prompt:message}); return; }
    if (!connected) throw Error('Open this panel through the Task Relay plugin to continue in ChatGPT.');
    await rpc('ui/message',{role:'user',content:[{type:'text',text:message}]});
  }
  async function requestProposal(intent) {
    const docs=selectedDocuments();
    if(intent==='make_reusable'){
      await send('Make this conversation reusable with Task Relay. Propose reusable instructions as a Skill and the current work as a separate snapshot, where useful. I’ll review each before saving.');
      status('Sent to ChatGPT. Your files will appear here for review.'); return;
    }
    if (intent==='update_work' && !docs.some(d=>d.kind==='work')) throw Error('Select the work snapshot you want to update.');
    if (intent==='improve_skill' && !docs.some(d=>d.kind==='skill')) throw Error('Select the Skill you want to improve.');
    const relevant=intent==='improve_skill'?docs.filter(d=>d.kind==='skill'):docs;
    const message={action:intent, instruction:intent==='make_reusable' ? 'Make this reusable. Analyze useful context already available in this conversation and call relay_propose_reusable with a standard Skill and/or work snapshot. No full transcript. Keep general know-how separate from instance-specific work. Nothing is saved until I review and export it.' : intent==='update_work' ? 'Update saved work from the new results already available in this conversation. Call relay_propose_reusable with intent update_work and these exact base documents. Propose work changes separately from any possible reusable Skill improvements; preserve unresolved facts and decision status.' : 'Improve Skill. Propose only reusable lessons supported by this conversation, using intent improve_skill and this exact base Skill. Do not turn project-specific corrections into general rules or install anything.', bases:relevant.map(compact)};
    const payload=JSON.stringify(message);
    if (payload.length>60000) throw Error('Selected material is too large. Choose a smaller Skill or snapshot.');
    await send(payload); status('Sent to ChatGPT. Your updated file will appear here for review.');
  }
  for (const [id,intent] of [['make-reusable','make_reusable'],['update-work','update_work'],['improve-skill','improve_skill']]) $(id).onclick=()=>perform($(id),()=>requestProposal(intent));
  $('open-saved').onclick=()=>{showView('reuse');status('');};
  $('back-home').onclick=()=>{showView('home');status('');};
  $('review-pending').onclick=()=>{showView('review');status('');};
  $('upload-device').hidden=!window.openai?.selectFiles;
  $('upload-device').onclick=()=>$('upload-files').click();
  for (const [id,kind] of [['view-skills','skill'],['view-work','work'],['view-recent','recent']]) $(id).onclick=()=>{currentView=kind;renderDocuments();};
  $('new-request').oninput=invalidateContext;
  async function prepareContext(){
    const request=$('new-request').value;
    if (!request.trim()) throw Error('Enter the new task or continuation request.');
    const preparedRevision=contextRevision;
    const result=await tool('relay_prepare_reuse',{request,documents:selectedDocuments().map(compact),max_chars:60000});
    if (preparedRevision!==contextRevision) { throw Error('Your request or files changed. Click Continue again with the current selection.'); }
    receive(result);
  }
  $('prepare-reuse').onclick=()=>perform($('prepare-reuse'),prepareContext);
  $('continue-chat').onclick=()=>perform($('continue-chat'),async()=>{if(!packet)await prepareContext();await send('Continue this task using the bounded selected material below. Preserve its authority distinctions and request missing inputs only where needed.\n'+packet);status('Sent to ChatGPT. Continue the conversation there.');});
  $('upload-files').onchange=()=>perform(null,async()=>{
    for (const file of $('upload-files').files) {
      if(file.size>240000)throw Error('Choose files smaller than 240 KB.');
      const result=await tool('relay_import_portable_file',{filename:file.name,data_base64:encoded(new Uint8Array(await file.arrayBuffer()))});receive(result);
    }
    $('upload-files').value='';status('Selected files opened. Choose what to use and enter your next request.');
  });
  $('select-library').onclick=()=>perform($('select-library'),async()=>{
    if(!window.openai?.selectFiles){$('upload-files').click();status('Library selection is unavailable here. Upload your saved files instead.');return;}
    const files=await window.openai.selectFiles();
    for(const file of files){
      const {downloadUrl}=await window.openai.getFileDownloadUrl({fileId:file.fileId});
      const result=await tool('relay_import_selected_file',{file:{download_url:downloadUrl,file_id:file.fileId,file_name:file.fileName,mime_type:file.mimeType}});receive(result);
    }
    if(files.length)status('Selected files opened. Choose what to use and enter your next request.');
  });
  window.addEventListener('message',event=>{
    if(event.source!==window.parent || !event.data || event.data.jsonrpc!=='2.0')return;
    const data=event.data;
    if(data.id!==undefined&&pending.has(data.id)){const item=pending.get(data.id);pending.delete(data.id);clearTimeout(item.timer);data.error?item.reject(Error(data.error.message)):item.resolve(data.result);}
    if(data.method==='ui/notifications/tool-result')receive(data.params);
    if(data.method==='ui/notifications/host-context-changed'){hostContext={...hostContext,...data.params};resize();}
  });
  function resize(){if(connected)notify('ui/notifications/size-changed',{height:Math.ceil(document.body.offsetHeight)});window.openai?.notifyIntrinsicHeight?.();}
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(resize).observe(document.body);
  showView('home'); renderDocuments();
  if(window.openai?.toolOutput)receive({structuredContent:window.openai.toolOutput,_meta:window.openai.toolResponseMetadata?._meta});
  if(window.parent!==window){
    rpc('ui/initialize',{appInfo:{name:'Task Relay',version:'0.3.1'},appCapabilities:{availableDisplayModes:['inline','fullscreen']},protocolVersion:'2026-01-26'}).then(result=>{
      connected=true;hostContext=result.hostContext||{};notify('ui/notifications/initialized',{});resize();
      if(!$('proposals').children.length&&!documents.size)status('');
    }).catch(error=>status(error.message,true));
  }
})();
