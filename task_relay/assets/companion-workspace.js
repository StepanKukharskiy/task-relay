/* Main workspace; all authorization and receipt checks belong to the shared runtime. */
(() => {
  const $ = id => document.getElementById(id);
  const native = window.__TAURI__;
  const request = (path, value = {}) => native.core.invoke('relay_request', {path, value});
  // Exact-version, bounded display cache shared by canvas and inspector.
  const imagePreviews=new Map();
  const htmlPreviews=new Map();
  const documentPreviews=new Map();
  function outputDocumentPreview(file) {
    const wrap=node('div',undefined,'artifact-document-preview');let stopped=false;
    async function show(page=1){
      wrap.replaceChildren(node('p','Loading preview…','hint'));
      const key=JSON.stringify([file.id,file.sha256,page]);
      try{
        if(!documentPreviews.has(key)){
          const promise=request('workspace-artifact',{artifact:file.id,sha256:file.sha256,preview:true,page});
          documentPreviews.set(key,promise);promise.catch(()=>documentPreviews.delete(key));
          if(documentPreviews.size>32)documentPreviews.delete(documentPreviews.keys().next().value);
        }
        const value=await documentPreviews.get(key);if(stopped || !wrap.isConnected)return;
        if(value.sha256!==file.sha256)throw Error('Saved file version mismatch.');
        wrap.replaceChildren();
        if(value.media_type==='application/pdf'){
          if(!/^data:image\/jpeg;base64,/.test(value.data_url))throw Error('Invalid PDF preview.');
          const controls=node('div',undefined,'actions'),previous=button('Previous page',()=>show(page-1),'quiet'),next=button('Next page',()=>show(page+1),'quiet');
          previous.disabled=page<=1;next.disabled=page>=value.pages;
          controls.append(previous,node('span',`Page ${page} of ${value.pages}`),next);
          const image=node('img',undefined,'artifact-image');image.src=value.data_url;image.alt=`${file.display_name || file.path} · page ${page}`;
          wrap.append(controls,image);
        }else if(typeof value.text==='string'){
          const text=node(value.media_type==='text/markdown'?'div':'pre',undefined,'artifact-text');
          if(value.media_type==='text/markdown'){
            const notice=node('div',undefined,'artifact-link-error');notice.hidden=true;notice.setAttribute('role','status');
            let opening=false;
            renderMarkdown(text,value.text,{openLink:async url=>{
              if(opening || stopped)return;opening=true;notice.hidden=true;notice.replaceChildren();
              try{await native.core.invoke('workspace_open_artifact_link',{artifact:file.id,sha256:file.sha256,url});}
              catch(error){
                if(!stopped){
                  const dismiss=button('Dismiss',()=>{notice.hidden=true;notice.replaceChildren();},'quiet');
                  notice.replaceChildren(node('span','Could not open link: '+String(error)),dismiss);notice.hidden=false;
                }
              }finally{opening=false;}
            }});
            wrap.append(notice);
          }else text.textContent=value.text;
          wrap.append(text);if(value.truncated)wrap.append(node('p','Showing the first 40,000 characters. Open the saved file for the full result.','hint'));
        }else throw Error('Unsupported document preview.');
      }catch(error){if(!stopped)wrap.replaceChildren(node('p','Preview unavailable: '+String(error),'hint'));}
    }
    show();wrap.disposeThumbnail=()=>{stopped=true;};return wrap;
  }
  const isTextDocument=file=>/\.(md|markdown|txt|json|csv|py|js)$/i.test(file.path);
  function outputHtmlPreview(file) {
    const wrap=node('div',undefined,'artifact-html-preview'),status=node('p','Loading gallery…','hint');
    wrap.append(status);let stopped=false;
    const key=JSON.stringify([file.id,file.sha256]);
    if(!htmlPreviews.has(key)){
      const pending=request('workspace-artifact',{artifact:file.id,sha256:file.sha256,preview:true}).then(value=>{
        if(value.sha256!==file.sha256 || value.media_type!=='text/html' || typeof value.html!=='string')throw new Error('HTML version mismatch.');
        return value;
      }).catch(error=>{htmlPreviews.delete(key);throw error;});
      htmlPreviews.set(key,pending);if(htmlPreviews.size>8)htmlPreviews.delete(htmlPreviews.keys().next().value);
    }
    htmlPreviews.get(key).then(value=>{
      if(stopped || !wrap.isConnected)return;
      const frame=()=>{const f=node('iframe');f.setAttribute('sandbox','');f.setAttribute('referrerpolicy','no-referrer');f.title=file.display_name || file.purpose || 'Saved HTML preview';f.srcdoc=value.html;return f;};
      const enlarge=button('Enlarge gallery',()=>{
        const dialog=node('dialog',undefined,'artifact-html-dialog');
        const close=button('Close',()=>{dialog.close();dialog.remove();enlarge.focus();},'quiet');
        dialog.append(close,frame());dialog.oncancel=e=>{e.preventDefault();close.onclick();};wrap.append(dialog);dialog.showModal();
      },'quiet');
      wrap.replaceChildren(frame(),enlarge,node('p',value.transformation,'hint'));
    }).catch(error=>{if(!stopped && wrap.isConnected)status.textContent='Preview unavailable: '+String(error);});
    wrap.disposeThumbnail=()=>{stopped=true;};return wrap;
  }
  function imagePreview(file, retry=false) {
    const key=JSON.stringify([file.id,file.sha256]);
    if(retry && imagePreviews.get(key)?.failed)imagePreviews.delete(key);
    if(!imagePreviews.has(key)){
      const pending=request('workspace-artifact',{artifact:file.id,sha256:file.sha256,preview:true}).then(value=>{
        if(value.sha256!==file.sha256 || !/^data:image\/(png|jpeg|gif|webp);base64,/.test(value.data_url))throw new Error('Image version mismatch.');
        return value;
      }).catch(error=>{pending.failed=true;throw error;});
      imagePreviews.set(key,pending);
      if(imagePreviews.size>32)imagePreviews.delete(imagePreviews.keys().next().value);
    }
    return imagePreviews.get(key);
  }
  function outputThumbnail(file) {
    const wrap=node('div',undefined,'canvas-image-output');
    const name=file.display_name || file.path.split('/').pop();
    const open=button('Loading image…',()=>{},'canvas-image-button');
    open.disabled=true;open.setAttribute('aria-label','Enlarge '+name);
    wrap.append(open);
    let stopped=false;
    const load=(retry=false)=>imagePreview(file,retry).then(value=>{
      if(stopped || !wrap.isConnected)return;
      const img=node('img');img.src=value.data_url;img.alt=file.purpose || name;
      open.replaceChildren(img);open.disabled=false;open.title='Enlarge '+name;
      open.onclick=()=>{
        const dialog=node('dialog',undefined,'canvas-image-dialog');
        const close=button('Close',()=>{dialog.close();dialog.remove();open.focus();},'quiet');
        const large=node('img');large.src=value.data_url;large.alt=img.alt;
        dialog.setAttribute('aria-label',name);
        dialog.append(close,node('p',name),large);
        if(value.transformation && value.transformation!=='original')dialog.append(node('p',value.transformation,'hint'));
        dialog.oncancel=event=>{event.preventDefault();close.onclick();};
        dialog.onclick=event=>{if(event.target===dialog)close.onclick();};
        wrap.append(dialog);dialog.showModal();close.focus();
      };
    }).catch(error=>{
      if(stopped || !wrap.isConnected)return;
      open.textContent='Preview unavailable — Retry';open.title=String(error);open.disabled=false;
      open.onclick=()=>{open.disabled=true;load(true);};
    });
    // Read only images visible in the canvas, not an entire saved media job.
    let observer;
    if(typeof IntersectionObserver!=='undefined'){
      observer=new IntersectionObserver(entries=>{
        if(entries.some(e=>e.isIntersecting)){observer.disconnect();load();}
      });
      observer.observe(wrap);
    }else load();
    wrap.disposeThumbnail=()=>{stopped=true;observer?.disconnect();};
    return wrap;
  }
  async function openOutput(file,trigger) {
    if(file.open_with){
      await request('workspace-open-artifact',{artifact:file.id,sha256:file.sha256});return;
    }
    const image=/\.(png|jpe?g|webp|gif)$/i.test(file.path);
    const html=/\.html?$/i.test(file.path);
    const documentFile=isTextDocument(file) || /\.pdf$/i.test(file.path);
    if(!image && !html && !documentFile){
      // Existing verified Finder action is the fallback for other file formats.
      await native.core.invoke('workspace_reveal_artifact',{artifact:file.id});return;
    }
    const dialog=node('dialog',undefined,'canvas-output-dialog');
    dialog.setAttribute('aria-label',file.display_name || file.path);
    let preview;
    const close=button('Close',()=>{preview?.disposeThumbnail?.();dialog.close();dialog.remove();trigger?.focus();},'quiet');
    const heading=node('div',undefined,'canvas-output-heading');
    heading.append(node('strong',file.display_name || file.path.split('/').pop()),close);
    const content=node('div',undefined,'canvas-output-content');
    dialog.append(heading,content);document.body.append(dialog);
    dialog.oncancel=event=>{event.preventDefault();close.onclick();};dialog.showModal();close.focus();
    if(image){
      content.append(node('p','Loading preview…','hint'));
      try{
        const value=await imagePreview(file,true);if(!dialog.isConnected)return;
        const img=node('img',undefined,'artifact-image');img.src=value.data_url;img.alt=file.display_name || file.path;
        content.replaceChildren(img);
      }catch(error){content.replaceChildren(node('p','Preview unavailable: '+String(error),'hint'));}
    }else{
      preview=html?outputHtmlPreview(file):outputDocumentPreview(file);content.append(preview);
    }
  }
  const routes = {jobs:'workspace-jobs', compose:'workspace-compose', detail:'workspace-detail', reviews:'workspace-reviews', connections:'workspace-connections', settings:'workspace-settings', saved:'saved-work-panel', sessions:'computer-sessions-panel', 'agent-reviews':'review', revisions:'revisions'};
  const labels = {jobs:'Jobs', compose:'Jobs / New task', detail:'Jobs / Job', reviews:'Review', connections:'Connections', settings:'Settings', saved:'Jobs / Saved records', sessions:'Jobs / Safari sessions', 'agent-reviews':'Review / Agent requests', revisions:'Review / Revision candidates'};
  routes.catalog='workspace-catalog'; labels.catalog='Nodes';
  let catalogRows=[], catalogTicket=0;
  function renderCatalog() {
    const term=$('workspace-catalog-search').value.trim().toLowerCase();
    const rows=catalogRows.filter(r=>JSON.stringify([r.id,r.title,r.family,r.inputs,r.outputs]).toLowerCase().includes(term));
    const list=$('workspace-catalog-list'); list.replaceChildren();
    $('workspace-catalog-status').textContent=`${rows.length} of ${catalogRows.length} operations`;
    for(const r of rows) {
      const card=node('details',undefined,'detail-section');
      const heading=node('summary');heading.append(window.RelayWorkflow.operationIcon(r.id),node('span',`${r.title} · ${r.id}`));card.append(heading,node('p',r.definition.description || '', 'hint'));
      if(r.legacy)card.append(node('p',`Legacy operation. For new workflows use ${r.replaced_by}. Saved workflows keep their original operation.`, 'hint'));
      for(const [title,ports] of [['Inputs',r.inputs],['Outputs',r.outputs]]) {
        card.append(node('h3',title));
        for(const [id,port] of Object.entries(ports)) {
          const row=node('div'); row.append(node('strong',port.label),node('span',' · '),node('code',id));
          const info=title==='Inputs' ? [port.kind,port.required?'Required':'Optional',Object.hasOwn(port,'default')?`Default: ${JSON.stringify(port.default)}`:null] : [port.media_type];
          row.append(node('p',info.filter(Boolean).join(' · '),'hint'),saved('Port definition',port));card.append(row);
        }
        if(!Object.keys(ports).length)card.append(node('p',(title==='Inputs'?r.dynamic_inputs:r.dynamic_outputs)?'Declared by the task you author.':'None.','hint'));
      }
      card.append(saved('Operation definition',r.definition));list.append(card);
    }
    if(!rows.length)list.append(node('p','No matching operations.'));
  }
  async function loadCatalog() {
    const ticket=++catalogTicket;
    catalogRows=[]; $('workspace-catalog-list').replaceChildren(); $('workspace-catalog-status').textContent='Loading operations…';
    try {
      const result=await request('node-catalog',{include_legacy:false});
      if(ticket!==catalogTicket)return;
      catalogRows=result.operations.filter(r=>!r.legacy); renderCatalog();
    } catch(error) {if(ticket===catalogTicket)$('workspace-catalog-status').textContent='Could not read operations: '+String(error);}
  }
  let destination = 'jobs', items = [], next = null, jobsTicket = 0, detailTicket = 0, detailLoading = null, selected = null, editorSelection = null, detailKey = null;
  let detailReadError = null;
  let canPlan = false, busy = false, attachments = [], parent = null, previousRun = null, entryMode = 'node', researchMode = 'suggest', pendingPlan = null, storageKey = null, jobsRenderKey = null;
  const actionIdentities = new Map();
  const selectionNotes = new Map();
  const resultQuestions = new Map(), resultChoices = new Map();
  const workflowSelections = new Map();
  const workflowExpanded = new Map();
  const canvasTabs = new Map();
  const panelStates = new Map();
  const openSelections = new Set();
  const sourceScans = new Map();
  const openChanges = new Set();
  const openJobDetails = new Set();
  let disposeWorkflow = () => {};
  let suspendedCanvas=false;
  let returnPipeline=null;
  const conversationStages=new Map();
  let reviewItemsAll=null, reviewTotal=null;
  const pipelineExpanded=new Set();
  const pipelineStageExpanded=new Set();
  const pipelineStatsExpanded=new Set();
  const readable = value => String(value || '').replace(/[_-]+/g,' ').replace(/^./,c=>c.toUpperCase());
  function node(tag, value, className) { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; if (className) n.className = className; return n; }
  function button(label, action, className = '') { const b = node('button', label, className); b.type = 'button'; b.onclick = action; return b; }
  function feedback(id, value, error = false) { const n = $(id); n.textContent = value; n.hidden = !value; n.classList.toggle('error', error); }
  function saved(label, value) { const d = node('details'); d.append(node('summary', label), node('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); return d; }
  function section(title) { const s = node('section', undefined, 'detail-section'); s.append(node('h2', title)); return s; }
  function shortTitle(value) { return (value || 'Job').split('\n')[0].slice(0,180); }
  function stateLabel(status) { return ({awaiting_user:'Needs review', needs_input:'Needs input', ready:'Plan ready', sending:'Thinking', answered:'Answered', failed:'Failed', queued:'Queued', active:'In progress', running:'In progress', launching:'Starting', waiting:'Waiting', pending:'Waiting', skipped:'Skipped', awaiting_review:'Awaiting review', paused:'Paused', idle:'Ready', accepted:'Saved', uncertain:'Needs inspection', discarded:'Discarded', completed:'Completed', cancelled:'Cancelled', blocked:'Blocked', rejected:'Rejected',proposed:'Proposed · not run'})[status] || status; }
  function navigate(route, focus = true, restoreCanvas = false) {
    if (!routes[route]) route = 'jobs';
    const utility=['settings','connections'].includes(route);
    const returning=restoreCanvas && suspendedCanvas && route==='detail';
    const keep=returning || (utility && (suspendedCanvas || (destination==='detail' && !!$('workspace-detail-body').querySelector('.canvas-host'))));
    if(keep)suspendedCanvas=!returning;
    else {suspendedCanvas=false;disposeWorkflow();disposeWorkflow=()=>{};}
    destination = route;
    document.body?.classList.add('canvas-app');
    document.body?.classList.toggle('canvas-workspace',returning);
    if(route!=='detail' && !keep){detailTicket++;detailKey=null;returnPipeline=null;}

    jobsRenderKey=null;
    document.querySelectorAll('.workspace-view').forEach(n => { n.hidden = n.id !== routes[route]; });
    $('workspace-breadcrumb').textContent = labels[route];
    const primary = ['compose','detail','saved','sessions'].includes(route) ? 'jobs' : ['agent-reviews','revisions'].includes(route) ? 'reviews' : route;
    document.querySelectorAll('[data-destination]').forEach(b => { if (b.dataset.destination === primary) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current'); });
    if (focus) { $(routes[route]).querySelector('h1,h2')?.focus({preventScroll:true}); window.scrollTo(0,0); }
    if (route === 'jobs' || route === 'reviews') refreshJobs();
    $('workspace-content').querySelector('.app-jobs-drawer')?.remove();
    if (route === 'catalog') loadCatalog();
  }
  function backToCanvas(){
    if(suspendedCanvas)navigate('detail',true,true);
    else if(editorSelection || selected)openItem(editorSelection || selected);
    else editDraft();
  }
  function jobListEntry(item,row,updated=()=>{}) {
    const entry=node('div',undefined,'job-list-entry'),error=node('p',undefined,'hint job-list-error');
    const remove=button('Delete',async()=>{
      if(busy)return;busy=true;remove.disabled=true;error.textContent='';
      try{
        const review=await request('workspace-job-delete-preview',{kind:item.kind,id:item.id});
        if(review.blockers?.length)throw Error(review.blockers.join(' '));
        const scope=['canvas','draft'].includes(review.kind)?`This permanently removes the saved canvas, ${review.runs.length} executions and ${review.files} Relay-owned files. Imported originals and copies exported elsewhere are not removed.`:'This permanently removes this job and its owned history. External files and shared conversation history are not removed.';
        const uncertain=review.stopped_uncertain_attempts?.length || 0;
        const warning=uncertain?`\n\n${uncertain} stopped attempt(s) have an unknown external outcome. Deleting their local history does not cancel provider work or reverse any charge. Nothing will be retried.`:'';
        if(!await window.RelaySavedWork.confirm(`Permanently delete “${shortTitle(review.title || item.title || item.id)}”?\n\n${scope}${warning} This cannot be undone.`,'Delete permanently'))return;
        const result=await request(review.delete_action,{id:review.id,digest:review.digest,...(uncertain?{acknowledge_uncertain:true}:{})});
        for(const id of [...(review.draft_ids || []),...(review.runs || [])]){
          const key='relay:workflow-composition:'+id;
          try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved?.request_id)localStorage.removeItem('relay:workflow-preview:'+saved.request_id);}catch{}
          localStorage.removeItem(key);localStorage.removeItem(key+':history');
        }
        const open=editorSelection || selected;
        const current=open && ((open.kind===item.kind && open.id===item.id) || (review.runs || []).includes(open.id) || (review.draft_ids || []).includes(open.id));
        jobsRenderKey=null;await refreshJobs();updated();if(current)await editDraft(null,false,null,null,true);
        if(result.status==='cleanup_pending'){
          const message=node('div',undefined,'hint');message.append(node('p','Job records deleted; file cleanup needs retry. '+(result.error || '')),button('Retry file cleanup',async()=>{
            try{const cleanup=await request(review.delete_action+'-recover',{id:review.id});if(cleanup.status==='complete')message.remove();else message.firstChild.textContent=cleanup.error || 'File cleanup is still pending.';}catch(e){message.firstChild.textContent=String(e);}
          },'quiet'));$('workspace-detail-body').prepend(message);
        }
      }catch(e){error.textContent=String(e);}
      finally{busy=false;remove.disabled=false;}
    },'quiet job-delete');
    remove.setAttribute('aria-label',`Delete job ${shortTitle(item.title || item.id)}`);
    entry.append(row,remove,error);
    if(item.archived)entry.append(button('Restore',async()=>{try{await request('workspace-job-visibility',{kind:item.kind,id:item.id,deleted:false});jobsRenderKey=null;await refreshJobs();updated();}catch(e){error.textContent=String(e);}},'quiet'));
    return entry;
  }
  function renderJobs() {
    const term = $('workspace-search').value.trim().toLowerCase();
    const key=JSON.stringify({term,deleted:$('workspace-show-removed').checked || false,items:items.map(({stamp,...item})=>item),reviews:reviewItemsAll?.map(({stamp,...item})=>item),reviewTotal});if(key===jobsRenderKey)return;jobsRenderKey=key;
    const filtered = items.filter(i => ($('workspace-show-removed').checked?i.archived:!i.archived) && `${i.title} ${i.status} ${i.channel} ${i.id}`.toLowerCase().includes(term));
    const list = $('workspace-job-list'); list.replaceChildren();
    for (const item of filtered) {
      const row = button('', () => openItem(item), 'job-row');
      row.setAttribute('aria-label',`${shortTitle(item.title || item.id)} · ${stateLabel(item.status)} · saved job ${item.id}`);row.title=item.title || item.id;
      const copy = node('span', undefined, 'job-copy'); copy.append(node('strong', shortTitle(item.title || item.id)), node('span', `${item.channel === 'desktop' ? 'Relay' : item.channel === 'shared' ? 'Shared' : item.channel} · ${['task','chat','request'].includes(item.kind) && !item.conversation_flow ? 'Conversation' : 'Workflow'}`, 'hint'));
      row.append(copy, node('span', item.archived?'Deleted · '+stateLabel(item.status):stateLabel(item.status), 'job-state' + (['ready','awaiting_user','needs_input','blocked','uncertain','rejected'].includes(item.status) ? ' attention' : ''))); list.append(jobListEntry(item,row));
    }
    if (!filtered.length) {
      const empty = node('div', undefined, 'empty-state'); empty.append(node('h2', term ? 'No matching jobs' : 'Start something new'), node('p', term ? 'Try another search or load more saved jobs.' : 'Describe a task, attach your files and review the proposed plan.'));
      list.append(empty);
    }
    const reviewItems = reviewItemsAll || items.filter(i => !i.archived && ['ready','awaiting_user','needs_input','blocked','uncertain'].includes(i.status));
    const reviews = $('workspace-review-list'); reviews.replaceChildren();
    for (const [label,states] of [['Ready for review',['ready','awaiting_user']],['Needs attention',['needs_input','blocked','uncertain']]]) {
      const group=reviewItems.filter(i=>states.includes(i.status));if(!group.length)continue;reviews.append(node('h2',label));
      for(const item of group){const row=button(`${shortTitle(item.title || item.id)} · ${stateLabel(item.status)}`,()=>openItem(item),'row-link');row.setAttribute('aria-label',`${shortTitle(item.title || item.id)} · ${stateLabel(item.status)} · saved job ${item.id}`);reviews.append(row);}
    }
    if (!reviewItems.length) reviews.append(node('p', 'No plans or job decisions in the loaded history.', 'muted'));
    if(reviewTotal>reviewItems.length)reviews.append(node('p',`Showing ${reviewItems.length} of ${reviewTotal} jobs needing attention.`,'hint'));
    $('workspace-review-count').textContent = reviewTotal ?? reviewItems.length; $('workspace-review-count').hidden = !(reviewTotal ?? reviewItems.length);
  }
  async function refreshJobs(more = false) {
    const ticket = ++jobsTicket;
    try {
      const result = await request('workspace-jobs', {offset:more ? next : 0,include_archived:$('workspace-show-removed').checked || false});
      if (ticket !== jobsTicket) return;
      items = more ? [...items, ...result.items] : result.items; next = result.next_offset; canPlan = result.can_plan;
      reviewItemsAll=result.review_items || null;reviewTotal=result.review_total ?? null;
      $('workspace-jobs-count').textContent = `${items.length} of ${result.total} saved jobs`;
      $('workspace-jobs-more').hidden = next === null;
      $('workspace-create').disabled = busy || !canPlan;
      if (!canPlan && !pendingPlan) feedback('workspace-compose-feedback', 'Start the local Relay service in Connections before requesting a plan.');
      if (!storageKey && result.scope) {
        storageKey = 'relay:pending-plan:' + result.scope;
        try {
          const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
          if (saved?.request_id && typeof saved.goal === 'string') { saved.research_mode ||= 'suggest'; saved.entry_mode ||= 'plan'; pendingPlan = saved; restoreDraft(saved); }
        } catch (_) { feedback('workspace-compose-feedback', 'The saved draft could not be read. Task submission requires local draft storage.', true); }
      }
      if(window.RelayNodeEditor){
        const drafts=await request('node-drafts',{include_archived:$('workspace-show-removed').checked || false});if(ticket!==jobsTicket)return;
        items=[...drafts.items,...items.filter(i=>i.kind!=='draft')];
      }
      items.sort((a,b)=>(Number(b.stamp)||0)-(Number(a.stamp)||0));
      renderJobs();
      $('workspace-delete-recovery').replaceChildren(...(result.conversation_delete_pending || []).map(receipt=>button('Finish conversation cleanup',async()=>{
        try{const done=await request('conversation-delete-recover',{id:receipt.id});if(done.status!=='complete')throw Error(done.error);await refreshJobs();}
        catch(error){$('workspace-jobs-count').textContent=String(error);}
      })));
    } catch (error) { $('workspace-jobs-count').textContent = 'Could not read saved jobs: ' + String(error); }
  }
  function draft() { return {goal:$('workspace-goal').value, constraints:$('workspace-constraints').value, research_mode:researchMode, project:$('workspace-project').value.trim() || null, parent_id:parent, previous_run:previousRun, files:[...attachments], entry_mode:entryMode}; }
  function restoreDraft(value) {
    $('workspace-goal').value = value.goal; $('workspace-constraints').value = value.constraints || ''; $('workspace-project').value = value.project || '';
    researchMode = value.research_mode || 'suggest';
    parent = value.parent_id || null; previousRun = value.previous_run || null; attachments = value.files || []; renderAttachments();
    entryMode = value.entry_mode || (parent || previousRun ? 'plan' : 'node');
    $('workspace-create').textContent = entryMode === 'plan' ? 'Preview plan' : 'Run node';
    $('workspace-compose-title').textContent = parent ? 'Revise plan' : previousRun ? (entryMode === 'node' ? 'Continue node' : 'Plan next step') : 'New task';
    $('workspace-compose-context').textContent = parent ? 'Your original request and plan remain saved.' : previousRun ? (entryMode === 'node' ? `Continue ${previousRun} with its exact saved inputs, outputs and limits.` : `Follow-up to ${previousRun}. Review and Start approve a new bounded stage.`) : 'Ask for a text result. The node uses ChatGPT Codex and bounded public reads; it cannot perform paid or native actions.';
    if (pendingPlan) feedback('workspace-compose-feedback', 'A planning request is saved locally. An unchanged retry uses its original identity.');
  }
  function newTask(options = {}) {
    // An unconfirmed submission remains visible; starting over must not hide it.
    if (pendingPlan) { restoreDraft(pendingPlan); navigate('compose'); return; }
    if (!Object.keys(options).length && $('workspace-goal').value.trim()) { navigate('compose'); $('workspace-goal').focus(); return; }
    restoreDraft({goal:'', constraints:'', files:[], ...options}); feedback('workspace-compose-feedback', canPlan ? '' : 'Start the local Relay service in Connections before requesting a plan.');
    navigate('compose'); $('workspace-goal').focus();
  }
  function researchChoice(plan, mode='sources') {
    return button(mode==='sources'?'Plan a source-backed answer':'Plan a quick answer',()=>newTask({goal:plan.request,project:plan.project || '',research_mode:mode}),'quiet');
  }
  function renderSources(body, research, view, plan) {
    const panel=section('Sources and research');
    const advice=plan?.research_advice || research?.advice;
    if(advice) {
      panel.append(node('h3','Orchestrator recommends '+(advice.recommended_mode==='sources'?'a source-backed answer':'a quick answer')));
      panel.append(node('p',advice.reason));
      panel.append(node('p',({unnecessary:'Research is unnecessary for this request.',optional:'Research is optional for this request.',required:'Sources are needed to satisfy this request.'})[advice.requirement],'hint'));
      if(advice.questions.length) {
        panel.append(node('h3','Questions source checking would resolve'));
        const checks=node('ul');advice.questions.forEach(question=>checks.append(node('li',question)));panel.append(checks);
      }
      if(plan?.channel==='desktop' && advice.requirement==='optional')panel.append(researchChoice(plan,advice.recommended_mode==='sources'?'none':'sources'));
    }
    if(plan?.research_mode==='sources')panel.append(node('p','Source-backed answer requested.','hint'));
    panel.append(node('p',research?.message || 'No web research record is available for this job.'));
    for(const step of research?.steps || [])panel.append(node('p',`${step.objective}${step.status?' · '+stateLabel(step.status):' · Proposed'}`,'hint'));
    for(const page of research?.pages || []) {
      const link=node('a',page.title || page.url,'file-link');link.href=page.url;link.title='Open current page · '+page.url;
      link.onclick=async event=>{event.preventDefault();event.stopPropagation();try{await native.core.invoke('workspace_open_source',{run:view.name,source:page.id});}catch(error){feedback('workspace-detail-feedback',String(error),true);}};
      const row=node('div',undefined,'source-row');row.append(link,node('p',`${page.kind==='search_result'?'Search result · page read not recorded':'Page observed'} · ${page.url}`,'hint'));panel.append(row);
    }
    if(research?.files?.length) {
      panel.append(node('h3','Files supplied to workers'));
      research.files.forEach(file=>panel.append(fileLink(file)));
      panel.append(node('p','These exact saved files were supplied as inputs. This does not prove every passage was read.','hint'));
    }
    if(research?.partial)panel.append(node('p','Some receipts are unavailable, changed or beyond this view’s limit. The list is incomplete.','hint'));
    if(research?.note && ((research.pages || []).length || (research.steps || []).length))panel.append(node('p',research.note,'hint'));
    if(!advice && plan?.channel==='desktop' && !(research?.steps || []).length && !(research?.pages || []).length)panel.append(researchChoice(plan));
    body.append(panel);
  }
  function renderAttachments() {
    $('workspace-attachments').replaceChildren(...attachments.map(path => {
      const chip = node('div', undefined, 'attachment-chip'); const name = node('span', path.split(/[\\/]/).pop()); name.title = path;
      const remove = button('×', () => { attachments = attachments.filter(p => p !== path); renderAttachments(); }, 'quiet'); remove.setAttribute('aria-label','Remove ' + name.textContent); chip.append(name,remove); return chip;
    }));
  }
  async function submitPlan(event) {
    event.preventDefault(); if (busy || !canPlan) return;
    const value = draft(); if (!value.goal.trim()) return;
    if (pendingPlan && JSON.stringify(value) !== JSON.stringify((({request_id,...rest}) => rest)(pendingPlan))) {
      return feedback('workspace-compose-feedback', 'The previous submission is unconfirmed. Restore its exact content and retry to inspect its receipt before making another request.', true);
    }
    if (!pendingPlan) pendingPlan = {request_id:crypto.randomUUID(), ...value};
    try {
      if (!storageKey) throw new Error('Relay history is not connected yet.');
      localStorage.setItem(storageKey, JSON.stringify(pendingPlan));
    } catch (error) { feedback('workspace-compose-feedback', String(error) + ' The request was not sent.', true); return; }
    busy = true; $('workspace-create').disabled = true; feedback('workspace-compose-feedback', 'Saving request…');
    try {
      const receipt = await request('plan-create', pendingPlan);
      const id = pendingPlan.request_id;
      // Once the committed receipt is known, the database owns this identity.
      localStorage.removeItem(storageKey); pendingPlan = null;
      restoreDraft({goal:'',constraints:'',files:[]});
      feedback('workspace-compose-feedback', receipt.message);
      await refreshJobs(); await openItem({kind:'request', id});
    } catch (error) { feedback('workspace-compose-feedback', String(error) + ' Retry unchanged content to inspect the same request; it will not queue another plan.', true); }
    finally { busy = false; $('workspace-create').disabled = !canPlan; }
  }
  const advancingRuns=new Set();
  async function readRunningCanvas(id,paint=()=>{},current=()=>true){
    let view=await request('workspace-detail',{run:id});
    if(!current())return view;
    if(view.canvas_run){
      paint(view);
      const advancing=view.executing_runs || ((['active','settling'].includes(view.status) || view.canvas_pending)?[id]:[]);
      for(const run of advancing){
        if(!current())return view;
        if(advancingRuns.has(run))continue;
        advancingRuns.add(run);
        try{await request('node-run-advance',{run});}finally{advancingRuns.delete(run);}
      }
      if(advancing.length)view=await request('workspace-detail',{run:id});
    }
    const discussions=(view.result_chats || []).filter(t=>['active','settling'].includes(t.status));
    for(const turn of discussions){if(!current())return view;await request('node-run-advance',{run:turn.run});}
    if(discussions.length)view=await request('workspace-detail',{run:id});
    return view;
  }
  async function openItem(item, automatic = false) {
    if (automatic && (busy || detailLoading === detailTicket)) return;
    editorSelection=null;selected = {kind:item.kind, id:item.id};
    const ticket = ++detailTicket;
    detailLoading = ticket;
    let failed=false;
    if (!automatic) { detailKey = null; navigate('detail'); $('workspace-detail-body').replaceChildren(node('p','Reading saved job…','muted')); feedback('workspace-detail-feedback',''); }
    try {
      if(item.kind==='draft'){const record=await request('node-draft',{id:item.id});if(ticket===detailTicket)editDraft(record);return;}
      if (item.kind === 'pipeline') {
        const view=await request('workspace-detail',{pipeline:item.id});if(ticket===detailTicket)renderPipeline(view);return;
      }
      if (item.kind === 'request') {
        const result = await request('workspace-request', {request_id:item.id});
        if (ticket !== detailTicket) return;
        if (result.node_view) { renderRun(result.node_view, null); return; }
        if (result.plan_id) return openItem({kind:'plan', id:result.plan_id}, automatic);
        if (result.conversation) { renderChat(result.conversation); return; }
        renderRequest(result); return;
      }
      if (item.kind === 'chat') {
        const result = await request('workspace-chat', {id:item.id}); if (ticket === detailTicket) renderChat(result); return;
      }
      if (item.kind === 'task') {
        const result = await request('task-detail', {task_id:item.id}); if (ticket === detailTicket) renderTask(result); return;
      }
      if (item.kind === 'plan') {
        const plan = await request('workspace-plan', {plan_id:item.id});
        if (ticket !== detailTicket) return;
        if (plan.run) { const view = await request('workspace-detail',{run:plan.run}); if (ticket === detailTicket) renderRun(view, plan); }
        else renderPlan(plan);
      } else if (item.kind === 'run') {
        const authored=await request('workspace-detail',{run:item.id});
        if(authored.canvas_document){if(ticket===detailTicket)editDraft({...authored.canvas_document,display:authored});return;}
        const view=await readRunningCanvas(item.id,view=>{if(ticket===detailTicket)renderRun(view);},()=>ticket===detailTicket);
        if (ticket === detailTicket) renderRun(view);
      }
    } catch (error) { failed=true;if (ticket === detailTicket) {detailReadError=String(error);feedback('workspace-detail-feedback', detailReadError, true);} }
    finally {
      if (!failed && ticket===detailTicket && detailReadError!==null) {
        if($('workspace-detail-feedback').textContent===detailReadError)feedback('workspace-detail-feedback','');
        detailReadError=null;
      }
      if (detailLoading === ticket) detailLoading = null;
    }
  }
  function rememberChatScroll() {
    const panel=$('workspace-detail-body').querySelector('.job-chat-panel'), transcript=panel?.querySelector('.job-chat-messages');
    const state=panelStates.get(panel?.dataset.jobKey);
    if(state && transcript && !panel.hidden && transcript.clientHeight>0)
      state.chatScroll={top:transcript.scrollTop, bottom:transcript.scrollHeight-transcript.clientHeight-transcript.scrollTop<32};
  }
  function changed(key) { if (key === detailKey) return false; rememberChatScroll(); disposeWorkflow(); disposeWorkflow = () => {}; detailKey = key; return true; }
  function heading(title, detail) { $('workspace-detail-title').textContent = title; $('workspace-detail-meta').textContent = detail; }
  async function deletePipeline(view, control) {
    if(busy)return;busy=true;control.disabled=true;
    try {
      const review=await request('job-delete-preview',{id:view.id});
      if(review.blockers.length){feedback('workspace-detail-feedback','Deletion is unavailable: '+review.blockers.join(' '),true);return;}
      const count=Object.values(review.counts).reduce((sum,n)=>sum+n,0);
      const approved=await window.RelaySavedWork.confirm(`Permanently delete Relay history for “${review.title}”?\n\n${count} owned records, ${review.plans.length} plans and ${review.runs.length} runs will be removed. Unstarted historical assignments will be discarded. Exported deliverables, files outside Relay and shared messenger history remain. This cannot be undone.`,'Delete job');
      if(!approved)return;
      const result=await request('job-delete',{id:view.id,digest:review.digest});
      if(result.status==='cleanup_pending')throw Error('History was deleted; private cleanup needs recovery: '+result.error);
      selected=null;navigate('jobs');
    }catch(error){feedback('workspace-detail-feedback',String(error),true);}
    finally{busy=false;control.disabled=false;await refreshJobs();}
  }
  // One presentation shell over saved projections. It never dispatches work.
  function jobChat(prompt,events=[],answer=null,view=null) {
    const content=node('div',undefined,'job-chat-messages');
    const message=(label,text,kind)=>{
      if(!text)return;
      const item=node('section',undefined,'job-chat-message '+kind),prose=node(kind==='assistant'?'div':'p',text);
      if(kind==='assistant' && typeof renderMarkdown==='function')renderMarkdown(prose,presentationMarkdown(text),{
        linkAllowed:url=>(view?.evidence?.sources || []).some(source=>source.url===url),
        openLink:async url=>{try{await native.core.invoke('workspace_open_chat_source',{id:String(view.id),url});}
          catch{feedback('workspace-detail-feedback','Could not open this recorded source.',true);}}
      });
      item.append(node('strong',label),prose);content.append(item);
    };
    message('You',prompt,'user');
    if(answer)message('Relay',answer,'assistant');
    for(const event of events)message(event.role==='user'?'You':event.role==='assistant'?'Relay':'Saved update',event.text,event.role || 'update');
    if(!answer && !events.length)content.append(node('p','No reply is saved for this job.','hint'));
    return content;
  }
  function conversationChat(view) {
    const content=node('div',undefined,'saved-conversation-chat');
    const transcript=jobChat(view.prompt,[],view.display_answer ?? view.answer,view);
    for(const stage of view.flow?.stages || []){
      const turn=stage.conversation;
      const progress=({queued:'Waiting to start…',accepted:'Waiting to start…',sending:'Working on your reply…',running:'Working on your reply…'})[stage.status] || stateLabel(stage.status);
      const group=jobChat(turn?.prompt || stage.prompt,[],turn?.display_answer ?? turn?.answer ?? progress,turn);
      transcript.append(...Array.from(group.children));
    }
    const key='relay:conversation-message:'+view.id;
    let draft={text:'',request_id:null,pending:false};
    try{draft={...draft,...JSON.parse(localStorage.getItem(key)||'{}')};}catch{}
    // A recorded child proves admission, even if the original Send response was lost.
    if(draft.request_id && (view.flow?.stages || []).some(s=>s.request_id===draft.request_id)){
      draft={text:'',request_id:null,pending:false};localStorage.removeItem(key);
    }
    let pendingTurn=null;
    const showPending=()=>{
      if(pendingTurn)return;
      pendingTurn=jobChat(draft.text,[],'Sending…');
      // Keep the submitted turn visible while admission is in flight or unknown.
      pendingTurn.className='pending-chat-turn';transcript.append(pendingTurn);
      transcript.scrollTop=transcript.scrollHeight;
    };
    if(draft.pending)showPending();
    const form=node('form',undefined,'workflow-chat-composer');
    const input=node('textarea');input.placeholder='Continue this conversation…';input.value=draft.text;
    input.setAttribute('aria-label','Message');
    const model=view.message_model;
    const label=node('p',model?`${model.provider} · ${model.model} · Shared setting`:(view.message_setup || 'Choose a conversation model in Settings.'),'hint');
    const status=node('p',draft.pending?'Send outcome not confirmed. Check the saved message before sending again.':
      view.can_message?'Sending creates a new request here. Previous attempts stay in history.':'A request is in progress, or model setup is required.','hint');status.setAttribute('role','status');
    let admitted=false;
    const send=button(draft.pending?'Check status':'Send',()=>{},'primary');
    const save=()=>localStorage.setItem(key,JSON.stringify(draft));
    const controls=()=>{input.disabled=draft.pending || admitted;send.textContent=draft.pending?'Check status':'Send';send.disabled=busy || admitted || (!draft.pending && (!view.can_message || !input.value.trim()));};
    input.oninput=()=>{draft.text=input.value;draft.request_id=null;save();controls();};
    const submit=async()=>{
      if(busy || send.disabled)return;
      const checking=draft.pending;
      if(!checking){draft.text=input.value;draft.request_id ||= crypto.randomUUID();draft.pending=true;save();showPending();}
      busy=true;controls();status.textContent=checking?'Checking saved message…':'Sending…';
      try{
        const result=await request('conversation-followup',checking?
          {id:String(view.id),request_id:draft.request_id,check:true}:
          {id:String(view.id),request_id:draft.request_id,message:draft.text});
        if(result.status==='not_saved'){
          draft.pending=false;save();pendingTurn?.remove();pendingTurn=null;status.textContent='No message was saved. Press Send to submit it.';
        }else{
          admitted=true;input.value='';status.textContent='Message saved. Waiting to start…';controls();
          draft={text:'',request_id:null,pending:false};localStorage.removeItem(key);
          selected={kind:'chat',id:result.root_id};
          // Admission is committed. Refresh in place, without the navigation
          // placeholder that removes Chat and briefly shows “Reading saved job”.
          busy=false;await openItem(selected,true);await refreshJobs();
        }
      }catch(error){status.textContent=String(error)+' Your message is kept. Check status before sending again.';
        if(pendingTurn)pendingTurn.replaceChildren(...Array.from(jobChat(draft.text,[],'Send not confirmed. Check status before sending again.').children));}
      finally{busy=false;controls();}
    };
    send.onclick=submit;form.onsubmit=event=>{event.preventDefault();return submit();};
    form.append(label,input,send,status);content.append(transcript,form);controls();return content;
  }
  function mountUnavailable(canvas,key){
    return window.RelayWorkflow.mount(canvas,{name:key,tasks:[]},{node,button,saved,stateLabel,outputFile:fileLink,select:()=>{}});
  }
  function canvasPage(body,key,canvas,results,history,status,summary,chat=jobChat(null),canvasRecord=null) {
    document.body?.classList.add('canvas-workspace');
    results.classList.add('canvas-results');history.classList.add('canvas-history');
    const toolbar=node('div',undefined,'canvas-toolbar'),project=node('div',undefined,'canvas-project-island job-titlebar'),actions=node('div',undefined,'canvas-action-island');
    project.append(button('Jobs',()=>{panels.chat=false;chatPanel.hidden=true;chatToggle.setAttribute('aria-pressed','false');showJobs(body);},'quiet'),node('span',$('workspace-detail-title').textContent || 'Job','job-title'),node('span',summary.split(' · ').slice(-1)[0],'job-status-label'),window.RelayWorkflow.connectionIndicators({node,button,open:()=>navigate('connections')}));
    function show(name){canvas.hidden=false;history.hidden=name!=='history';historyToggle.setAttribute('aria-pressed',String(!history.hidden));canvasTabs.set(key,name);}
    const historyToggle=button('History',()=>show(history.hidden?'history':'canvas'),'quiet');
    const historyHeading=node('div',undefined,'section-title'),historyClose=button('×',()=>show('canvas'),'quiet');historyClose.setAttribute('aria-label','Close history');historyHeading.append(node('h3','History'),historyClose);history.insertBefore(historyHeading,history.children[0] || null);
    const diagnostics=node('details',undefined,'job-diagnostics');diagnostics.append(node('summary','Technical details'),status,results);history.append(diagnostics);
    const panels=panelStates.get(key) || {chat:false,inspector:false};panelStates.set(key,panels);
    if(panelStates.size>100)panelStates.delete(panelStates.keys().next().value);
    const chatPanel=node('aside',undefined,'job-chat-panel');chatPanel.hidden=!panels.chat;chatPanel.setAttribute('aria-label','Job chat');
    chatPanel.dataset.jobKey=key;
    const transcript=chat.classList.contains('job-chat-messages') || chat.className==='job-chat-messages'?chat:chat.querySelector('.job-chat-messages');
    const restoreScroll=()=>requestAnimationFrame(()=>{
      if(!transcript || !chatPanel.isConnected || chatPanel.hidden)return;
      transcript.scrollTop=panels.chatScroll?.bottom===false?panels.chatScroll.top:Math.max(0,transcript.scrollHeight-transcript.clientHeight);
    });
    if(transcript)transcript.addEventListener('scroll',rememberChatScroll);
    const chatHeading=node('div',undefined,'section-title');
    const chatToggle=button('Chat',()=>{rememberChatScroll();const jobs=body.querySelector('.jobs-drawer');if(jobs)jobs.hidden=true;chatPanel.hidden=!chatPanel.hidden;panels.chat=!chatPanel.hidden;chatToggle.setAttribute('aria-pressed',String(!chatPanel.hidden));restoreScroll();},'quiet');
    chatToggle.setAttribute('aria-pressed',String(panels.chat));
    chatHeading.append(node('h3','Chat'));window.RelayWorkflow.panelWidth(chatPanel,chatHeading,key+':chat','Chat',{button});chatHeading.append(button('×',()=>{chatPanel.hidden=true;panels.chat=false;chatToggle.setAttribute('aria-pressed','false');},'quiet'));
    chatHeading.children[chatHeading.children.length-1].setAttribute('aria-label','Close chat');
    chatPanel.append(chatHeading,chat);
    let inspectorVisible=panels.inspector;canvas.classList.toggle('inspector-hidden',!inspectorVisible);
    show.inspector=(visible=true)=>{inspectorVisible=visible;panels.inspector=visible;canvas.classList.toggle('inspector-hidden',!visible);};
    show.chat=()=>{panels.chat=true;chatPanel.hidden=false;chatToggle.setAttribute('aria-pressed','true');restoreScroll();};
    for(const [control,kind] of [[chatToggle,'chat'],[historyToggle,'history']]){const glyph=window.RelayWorkflow?.icon?.(kind);if(glyph)control.replaceChildren(glyph,node('span',kind==='chat'?'Chat':'History'));}
    if(canvasRecord)actions.append(button('Export',()=>exportWorkflow(canvasRecord),'quiet'));
    actions.append(chatToggle,historyToggle,button('+ Step',()=>editDraft(canvasRecord,true),'quiet'));
    if(canvasRecord)actions.append(button('Run',()=>editDraft(canvasRecord,false,'all'),'primary'));
    toolbar.append(project,actions);
    if(returnPipeline)toolbar.append(button('‹ '+shortTitle(returnPipeline.title),()=>openItem(returnPipeline),'quiet pipeline-back'));
    body.replaceChildren(toolbar,canvas,history,chatPanel);
    restoreScroll();
    show(canvasTabs.get(key)==='history'?'history':'canvas');return show;
  }
  function showJobs(body,beforeLeave=async()=>true){
    const chat=body.querySelector('.job-chat-panel');if(chat)chat.hidden=true;
    let drawer=body.querySelector(body===$('workspace-content')?'.app-jobs-drawer':'.jobs-drawer');
    if(drawer && !drawer.hidden){drawer.hidden=true;return true;}
    if(drawer)drawer.remove();
    drawer=node('aside',undefined,'jobs-drawer'+(body===$('workspace-content')?' app-jobs-drawer':''));drawer.setAttribute('aria-label','Jobs');
    const head=node('div',undefined,'section-title');head.append(node('h3','Jobs'),button('×',()=>{drawer.hidden=true;},'quiet'));
    const search=node('input');search.type='search';search.placeholder='Search jobs…';search.setAttribute('aria-label','Search jobs');
    const list=node('div',undefined,'jobs-drawer-list');
    function draw(){list.replaceChildren();for(const item of items.filter(i=>($('workspace-show-removed').checked?i.archived:!i.archived) && (i.title || i.id).toLowerCase().includes(search.value.toLowerCase()))){
      const row=button('',async()=>{if(await beforeLeave())openItem(item);},'job-row');row.append(node('strong',shortTitle(item.title || item.id)),node('span',item.archived?'Deleted':stateLabel(item.status),'job-state'));list.append(jobListEntry(item,row,draw));
    }}
    const removed=node('input');removed.type='checkbox';removed.checked=$('workspace-show-removed').checked || false;removed.setAttribute('aria-label','Recently deleted');
    const removedLabel=node('label',undefined,'hint');removedLabel.append(removed,node('span','Recently deleted'));
    removed.onchange=async()=>{$('workspace-show-removed').checked=removed.checked;await refreshJobs();draw();};
    const loading=node('p','Loading saved jobs…','hint');
    const footer=node('nav',undefined,'jobs-drawer-footer');footer.setAttribute('aria-label','App controls');
    footer.append(button('Telegram',async()=>{if(await beforeLeave())navigate('connections');},'quiet'),button('Settings',async()=>{if(await beforeLeave())navigate('settings');},'quiet'));
    search.oninput=draw;draw();drawer.append(head,button('Templates',()=>showTemplates(beforeLeave),'quiet'),button('Import workflow',async()=>{if(await beforeLeave())await importWorkflow();},'quiet'),button('New job',async()=>{if(await beforeLeave())editDraft(null,false,null,null,true);},'quiet'),search,removedLabel,loading,list,footer);body.append(drawer);
    refreshJobs().then(()=>{if(!drawer.isConnected)return;draw();const status=$('workspace-jobs-count').textContent;loading.textContent=status.startsWith('Could not')?status:items.length?'':'No saved jobs.';});
    return true;
  }
  async function showTemplates(beforeLeave) {
    const dialog=node('dialog',undefined,'workflow-template-dialog'),list=node('div'),note=node('p','Loading templates…','hint');
    const close=button('Close',()=>{dialog.close();dialog.remove();},'quiet');
    dialog.append(node('h3','Job templates'),node('p','Start with an editable copy. Review the nodes and connections, then choose Run when ready.','hint'),list,note,close);
    document.body.append(dialog);dialog.showModal();dialog.oncancel=e=>{e.preventDefault();close.onclick();};
    let creating=false;
    try {
      const catalog=await request('node-templates',{});if(!dialog.open)return;
      for(const template of catalog.items){
        const card=node('article',undefined,'section-card');
        const use=button('Use template',async()=>{
          if(creating)return;creating=true;use.disabled=true;
          try {
            if(!await beforeLeave())return;
            const selected=await request('node-template',{id:template.id});
            const record=await request('node-draft-save',{id:null,revision:null,title:selected.title,workflow:selected.workflow});
            close.onclick();await editDraft(record);jobsRenderKey=null;await refreshJobs();
          }catch(e){note.textContent=String(e);}finally{creating=false;use.disabled=false;}
        },'primary');
        card.append(node('h4',template.title),node('p',template.description),node('p',template.requirements,'hint'),use);list.append(card);
      }
      note.textContent=catalog.items.length?'':'No bundled templates available.';
    }catch(e){note.textContent=String(e);}
  }
  async function exportWorkflow(record) {
    const dialog=node('dialog',undefined,'workflow-transfer-dialog'),include=node('input');include.type='checkbox';include.checked=false;
    const label=node('label');label.append(include,node('span','Include input files'));
    const note=node('p','Shares this graph, prompts and model choices. Connections, API keys, results and history are not included. Review your prompts and input files before sharing.','hint');
    const feedback=node('p','','feedback');
    const cancel=button('Cancel',()=>{dialog.close();dialog.remove();},'quiet');
    const save=button('Export workflow',async()=>{
      save.disabled=true;
      try{
        const name=(record.title || 'Workflow').replace(/[^\p{L}\p{N} _-]/gu,'').slice(0,100) || 'Workflow';
        const path=await native.dialog.save({title:'Export workflow',defaultPath:name+'.relay.zip',filters:[{name:'Relay workflow',extensions:['zip']}]});
        if(!path)return;
        const result=await request('workflow-export',{source:{kind:record.canvas?'canvas':'draft',id:record.canvas || record.id,revision:record.revision},path,include_files:include.checked});
        feedback.textContent='Exported '+result.nodes+' nodes to '+result.path;save.hidden=true;cancel.textContent='Done';
      }catch(e){feedback.textContent=String(e);}finally{save.disabled=false;}
    },'primary');
    dialog.append(node('h3','Export workflow'),note,label,feedback,save,cancel);document.body.append(dialog);dialog.showModal();
    dialog.oncancel=e=>{e.preventDefault();cancel.onclick();};
  }
  async function importWorkflow() {
    try{
      const path=await native.dialog.open({title:'Import workflow',multiple:false,directory:false,filters:[{name:'Relay workflow',extensions:['zip']}]});if(!path)return;
      const preview=await request('workflow-import-preview',{path}),files={};
      // Omitted files are resolved explicitly before creating the new draft.
      for(const file of preview.missing_files){
        const chosen=await native.dialog.open({title:'Choose original input: '+file.name,multiple:false,directory:false});if(!chosen)return;files[file.id]=chosen;
      }
      const record=await request('workflow-import',{path,sha256:preview.sha256,files});
      await editDraft(record);jobsRenderKey=null;await refreshJobs();
    }catch(e){feedback('workspace-detail-feedback',String(e),true);}
  }
  async function editDraft(record=null,picker=false,runScope=null,selection=null,newJob=false){
    if(!window.RelayNodeEditor)return;
    editorSelection=record?{kind:record.canvas?'run':'draft',id:record.canvas || record.id}:null;selected=null;detailTicket++;navigate('detail');heading(record?.title || 'New job','Draft');document.body.classList.add('canvas-workspace');
    disposeWorkflow=window.RelayNodeEditor.mount($('workspace-detail-body'),{record,picker,runScope,selection,newJob,request,node,button,saved,stateLabel,outputThumbnail,openOutput,pickFiles:()=>native.dialog.open({multiple:true,directory:false,title:"Choose node input files"}),
      modelSettings:()=>{navigate('settings');$('model-settings').open=true;const control=$('model-text-model');control?.scrollIntoView({block:'center'});control?.focus({preventScroll:true});},
      connections:()=>navigate('connections'),trackRun:readRunningCanvas,renderResults:(task,panel,current,historical,view)=>nodeResults(task,panel,current,historical,view,(file,host)=>resultDraft(view,task,'input',file,host),file=>{resultChoices.set(view.name,file.id);workflowSelections.set(view.name,task.id);openItem({kind:'run',id:view.name});}),
      exportWorkflow, onRun:(run,scope)=>{if(scope && scope!=='all')workflowSelections.set(run,scope);return openItem({kind:'run',id:run},true);},leave:()=>navigate('jobs'),jobs:showJobs,fromHistory:picker, onSaved:record=>{editorSelection={kind:record.canvas?'run':'draft',id:record.canvas || record.id};jobsRenderKey=null;if(record.canvas)return;items=[{id:record.id,title:record.title,kind:'draft',status:'draft',channel:'desktop'},...items.filter(i=>!(i.kind==='draft' && i.id===record.id))];}});
  }
  function resultCommand(view,task,mode,file=null){
    return {run:task.execution_run || view.name,task:task.execution_task || task.id,attempt:file?.attempt || task.latest_attempt,mode,request_id:crypto.randomUUID(),
      artifact:file?.id || null,sha256:file?.sha256 || null,operation:null,question:''};
  }
  async function resultDraft(view,task,mode,file=null,panel=null){
    try{
      const command=resultCommand(view,task,mode,file);
      if(mode==='input'){
        const catalog=await request('node-catalog',{include_legacy:false});
        const media=task.planned_outputs?.find(p=>p.path===file.path)?.media_type;
        const choices=catalog.operations.filter(r=>!r.legacy && (r.id==='model' || Object.values(r.inputs).filter(p=>
          ['artifact','artifacts'].includes(p.kind) && (!p.accepts?.length || p.accepts.includes('*/*') || p.accepts.includes(media))).length===1));
        const picker=node('div',undefined,'result-operation-picker');picker.append(node('h4','Use result in…'));
        for(const r of choices)picker.append(button(r.title,async()=>{
          try{command.operation=r.id;await editDraft(await request('node-result-draft',command));}
          catch(e){feedback('workspace-detail-feedback',String(e),true);}
        },'quiet'));
        panel.append(picker);return;
      }
      await editDraft(await request('node-result-draft',command));
    }catch(e){feedback('workspace-detail-feedback',String(e),true);}
  }
  const nodePromptEdits=new Map();
  function nodePromptEditor(view,task,panel){
    const promptEnabled=task.operation==='model' || (!task.operation && !task.execution) ||
      typeof task.prompt==='string' || Object.hasOwn(task.execution?.parameters || {},'prompt');
    const key=JSON.stringify([view.name,task.id,task.latest_attempt]);
    let edit=nodePromptEdits.get(key);
    if(!edit || (view.canvas_document && !edit.dirty && edit.canvasRevision!==view.canvas_document.revision)){
      edit={prompt:task.prompt_draft?.prompt ?? task.prompt ?? (task.operation==='model'?task.objective:''),revision:task.prompt_draft?.revision,
        canvasRevision:view.canvas_document?.revision,dirty:false};nodePromptEdits.set(key,edit);
    }
    const field=node('textarea');field.value=edit.prompt;field.setAttribute('aria-label','Node prompt');field.maxLength=12000;
    const note=node('p','Only this node runs. Previous versions and other nodes stay unchanged.','hint');
    let check=node('div'),dismiss=()=>{};
    field.oninput=()=>{edit.prompt=field.value;edit.dirty=true;dismiss();};
    let pending=false;
    async function save(){
      let saved;
      if(view.canvas_document){
        const record=view.canvas_document,workflow=JSON.parse(JSON.stringify(record.workflow));
        const n=workflow.tasks.find(t=>t.id===task.id);
        if(n.operation==='model')n.objective=edit.prompt;else n.inputs.prompt={value:edit.prompt};
        saved=await request('node-canvas-save',{run:view.name,revision:record.revision,title:record.title,workflow});view.canvas_document=saved;
      }else saved=await request('node-prompt-save',{run:view.name,task:task.id,attempt:task.latest_attempt,prompt:edit.prompt});
      edit.revision=saved.revision;edit.canvasRevision=view.canvas_document?.revision;edit.dirty=false;note.textContent='Prompt saved on this canvas. Not executed.';
    }
    const saveButton=button('Save prompt',async()=>{if(pending)return;pending=true;try{await save();}catch(e){note.textContent=String(e);}finally{pending=false;}},'quiet');
    const runButton=button('Run this node',async(host,reset)=>{
      if(pending)return;pending=true;
      check=host || check;let cancelled=false;
      const cancel=button('Cancel',()=>{cancelled=true;reset?.();},'quiet');
      dismiss=()=>cancel.onclick();
      check.replaceChildren(node('p','Checking…','hint'),cancel);
      try{
        if(edit.dirty || (!view.canvas_document && !edit.revision))await save();
        const command=view.canvas_document?{canvas:view.name,scope:task.id,revision:view.canvas_document.revision,values:view.canvas_document.values || {},request_id:crypto.randomUUID()}:{run:view.name,task:task.id,attempt:task.latest_attempt,revision:edit.revision,request_id:crypto.randomUUID()};
        const preview=await request('node-run-preview',command);
        if(cancelled || !check.isConnected)return;
        check.replaceChildren();
        if(preview.blockers.length){check.append(node('p',preview.blockers.map(b=>b.message).join(' '),'feedback error'),cancel);return;}
        const paid=preview.paid_nodes.length>0;
        const hostApprovals=window.RelayWorkflow.hostCodeReview(check,preview,node);
        if(paid)check.append(node('p','Only this node will run. Paid API or account-credit use; price unavailable.','hint'));
        let submission;
        const confirm=button(hostApprovals.length?(paid?'Approve script & run · paid':'Approve script & run'):paid?'Run · paid':'Run',async()=>{
          if(confirm.disabled || cancelled || !check.isConnected)return;
          if(!submission && edit.dirty){check.replaceChildren(node('p','Prompt changed. Run again to check the current node.','hint'),cancel);return;}
          confirm.disabled=true;cancel.disabled=true;field.disabled=true;saveButton.disabled=true;runButton.disabled=true;
          if(!submission)submission={...command,fingerprint:preview.fingerprint,allow_paid:paid,...(hostApprovals.length?{approve_host_code:hostApprovals}:{})};
          try{confirm.textContent='Starting…';await request('node-run-start',submission);nodePromptEdits.delete(key);await openItem({kind:'run',id:view.name},true);}
          catch(e){check.append(node('p',String(e)+' Retrying checks the same submission.','feedback error'));confirm.textContent='Check same submission';}
          finally{confirm.disabled=false;cancel.disabled=false;}
        },'primary');check.append(confirm,cancel);
        if(!paid && !hostApprovals.length)await confirm.onclick();
      }catch(e){check.replaceChildren(node('p',String(e),'feedback error'),cancel);}finally{pending=false;}
    },'primary');
    if(promptEnabled)panel.append(node('h4','Prompt'),field,saveButton,note);
    return (host,reset)=>runButton.onclick(host,reset);
  }
  function resultChat(view,task){
    const panel=node('div');
    if(!task){panel.append(node('p','Select a completed node to discuss its result.','hint'));return panel;}
    const files=(view.latest_outputs || []).filter(f=>f.task===task.id);
    if(task.status!=='completed' || !files.length){panel.append(node('p','This node has no completed result to discuss.','hint'));return panel;}
    const choice=node('select');choice.setAttribute('aria-label','Result to discuss');
    files.forEach(f=>{const option=node('option',f.path);option.value=f.id;choice.append(option);});
    choice.value=files.some(f=>f.id===resultChoices.get(view.name))?resultChoices.get(view.name):files[0].id;
    const turns=node('div'),form=node('form'),question=node('textarea'),note=node('p','','hint');
    question.maxLength=12000;question.placeholder='Ask about this result…';question.setAttribute('aria-label','Question about selected result');
    const send=button('Send · Codex',()=>submit(),'primary');
    let pending=null;
    const storage=()=>`relay:result-chat:${view.name}:${choice.value}`;
    function draw(){
      resultChoices.set(view.name,choice.value);turns.replaceChildren();
      for(const t of (view.result_chats || []).filter(t=>t.task===task.id && t.artifact===choice.value)){
        turns.append(node('strong','You'),node('p',t.question),node('strong','Codex'),node('p',t.answer || stateLabel(t.status)),
          button('Open answer node',()=>openItem({kind:'run',id:t.run}),'quiet'));
      }
      try{pending=JSON.parse(localStorage.getItem(storage()) || 'null');}catch(e){note.textContent='Could not read the pending question. '+e;send.disabled=true;return;}
      question.value=pending?.question || resultQuestions.get(storage()) || '';
      question.disabled=!!pending;choice.disabled=!!pending;
      send.textContent=pending?'Check saved submission':'Send · Codex';
      note.textContent='Uses ChatGPT Codex with this exact result and previous completed answers. Each reply is an inspectable node run.';
    }
    async function submit(){
      if(busy || !question.value.trim())return;
      try{
        const file=files.find(f=>f.id===choice.value);
        if(!pending){pending={...resultCommand(view,task,'chat',file),question:question.value.trim()};localStorage.setItem(storage(),JSON.stringify(pending));}
        busy=true;send.disabled=true;question.disabled=true;choice.disabled=true;note.textContent='Saving question…';
        const receipt=await request('node-result-chat',pending);
        localStorage.removeItem(storage());resultQuestions.delete(storage());pending=null;
        await request('node-run-advance',{run:receipt.run});
        detailKey=null;busy=false;await openItem({kind:'run',id:view.name});
      }catch(e){note.textContent=String(e)+' The same submission identity is retained; check it before sending another question.';send.textContent='Check saved submission';}
      finally{busy=false;send.disabled=false;}
    }
    choice.onchange=draw;question.oninput=()=>resultQuestions.set(storage(),question.value);
    form.onsubmit=e=>{e.preventDefault();submit();};form.append(question,send,note);
    panel.append(node('h4','Discuss '+task.id),choice,turns,form);draw();return panel;
  }
  function renderPipeline(view) {
    const key=JSON.stringify({...view,stages:view.stages.map(stage=>({...stage,execution:stage.execution?{...stage.execution,captured_at:0}:null})),usage:{...view.usage,elapsed_seconds:Math.floor((view.usage?.elapsed_seconds || 0)/60)}});if(!changed(key))return;
    heading(view.title,`${view.status==='completed' && view.coverage?.shortfall?.length ? 'Completed with coverage gaps' : stateLabel(view.status)} · ${view.channel==='desktop'?'Relay':view.channel}`);
    const body=$('workspace-detail-body');body.replaceChildren();
    const overview=section('Job progress'),s=view.stats,u=view.usage;
    const now=section('Now'),live=view.activity?.attempts || [];
    const terminal=['completed','cancelled'].includes(view.status);
    const current=view.stages.filter(stage=>!['completed','skipped','cancelled','pending'].includes(stage.status));
    if(live.length)for(const a of live)now.append(node('p',`${readable(a.task)} · ${a.reviewer?'Reviewer':a.operation?'Connector':'Worker'} · ${a.telemetry?.activity ? readable(a.telemetry.activity) : stateLabel(a.state)}${a.current?'':' · Earlier run'}`));
    else if(terminal)now.append(node('p',`${stateLabel(view.status)}. No workers running.`));
    else if(view.status==='blocked')now.append(node('p',`${current.map(stage=>stage.id==='deck'?'Presentation':readable(stage.id)).join(', ') || 'Work'} paused. Your completed work is saved.`));
    else if(['paused','awaiting_choice'].includes(view.status))now.append(node('p',view.status==='awaiting_choice'?'Waiting for your choice.':'Paused. Your completed work is saved.'));
    else if(current.some(stage=>!stage.run && ['queued','running','sending'].includes(stage.plan_status || stage.status)))now.append(node('p',`Preparing ${current.filter(stage=>!stage.run).map(stage=>readable(stage.id)).join(', ')}. No execution worker has started.`));
    else now.append(node('p','No worker is currently running. Waiting for the controller to advance the job.'));
    const diagnostics=[];
    for(const stage of current){
      const owner=stage.lifecycle,reason=owner?.reason || stage.error || stage.plan_error;
      const held=stage.status==='blocked' || ['held','pending_external','owner_missing'].includes(owner?.phase);
      if(held){
        const message=owner?.recovery_code==='capacity_exhausted' || owner?.next_action==='partition_or_review_authorization'
          ? "Relay couldn't start a required correction within this job's limits."
          : owner?.phase==='pending_external' ? 'Relay needs to confirm the previous operation’s result before it can safely continue.'
          : owner?.phase==='owner_missing' ? 'Relay hit an internal problem and could not continue this stage.'
          : 'Relay could not finish this stage.';
        now.append(node('p',message));
      }
      if(reason)diagnostics.push(`${readable(stage.id)}: ${reason}`);
      if(owner?.next_action)diagnostics.push(`Recovery action: ${owner.next_action}${owner.remaining_recovery_cycles!=null ? ' · '+owner.remaining_recovery_cycles+' cycles remaining' : ''}`);
    }
    if(diagnostics.length)now.append(saved('Technical details',diagnostics.join('\n')));
    for(const delivery of view.delivery_holds || [])now.append(node('p','Delivery needs reconciliation: '+(delivery.error || 'The last send has no confirmed receipt.')+' No automatic resend.','feedback error'));
    if(view.coverage){const c=view.coverage;
      if(c.error)now.append(node('p','Coverage could not be verified: '+c.error,'feedback error'));
      else if(c.pending)now.append(node('p','Coverage pending: '+readable(c.pending),'hint'));
      else if(c.shortfall?.length)now.append(node('p',`Coverage gaps: ${new Set(c.shortfall.map(s=>s.item)).size} items below the requested option count${c.unresolved_items?.length ? '; '+c.unresolved_items.length+' with no options' : ''}. Execution completion does not mean all requested options were found.`,'feedback error'));
      else now.append(node('p','Requested option counts are present. Factual quality is assessed by the saved reviews.','hint'));
    }
    if(!terminal && view.activity && !view.activity.controller_fresh)now.append(node('p','Controller health is stale or unavailable. Saved status does not confirm progress.','feedback error'));
    if(view.activity?.last_event)now.append(node('p',`Last recorded update: ${new Date(view.activity.last_event.created*1000).toLocaleString()}`,'hint'));
    body.append(now);
    overview.append(node('p',`${s.stages_completed} of ${s.stages} stages completed · ${s.tasks_completed} of ${s.tasks} current tasks completed`));
    const stats=node('details');stats.append(node('summary','Attempts and usage'));
    stats.open=pipelineStatsExpanded.has(view.id);stats.addEventListener('toggle',()=>{if(stats.open)pipelineStatsExpanded.add(view.id);else pipelineStatsExpanded.delete(view.id);});
    stats.append(node('p',`${s.workers_created-s.reviewers_created} producer attempts · ${s.reviewers_created} reviewer attempts · ${s.operations_started} connector attempts`),
      node('p',`${s.running} running or stopping · ${s.uncertain} with uncertain outcomes`));
    const totals=u?.totals?.total_tokens;
    stats.append(node('p',`${Math.round((u?.elapsed_seconds || 0)/60)} minutes elapsed · ${totals?.reported?.toLocaleString() ?? 'Unknown'} reported tokens · ${totals?.unknown_records ?? 0} unknown usage records`),
      node('p','Attempt counts and usage include earlier corrections. Current progress uses each stage’s latest run. Elapsed time includes interruptions; reported tokens are not a bill.','hint'));
    overview.append(stats);
    body.append(overview);
    const outputs=section('Results');
    const finalStage=[...view.stages].reverse().find(s=>s.status==='completed' && view.outputs?.some(f=>f.stage===s.id))?.id;
    const earlier=node('details');earlier.append(node('summary','Earlier stage results'));
    const supporting=node('details');supporting.append(node('summary','Supporting files and reviews'));
    for(const file of view.outputs || []){const row=node('div',undefined,'file-row');row.append(node('span',file.stage+' · ','hint'),fileLink(file));(file.stage!==finalStage?earlier:/\.(pptx|pdf|docx|xlsx|mp4)$/i.test(file.path)?outputs:supporting).append(row);}
    if(supporting.children.length>1)outputs.append(supporting);
    if(earlier.children.length>1)outputs.append(earlier);
    if(!view.outputs?.length)outputs.append(node('p','No stage result files have been recorded yet.','muted'));
    body.append(outputs);
    const stages=section('Stages and current workers');
    for(const stage of view.stages){
      const card=node('details',undefined,'review-card'),stageKey=view.id+':'+stage.id;
      const done=stage.tasks.filter(t=>t.status==='completed').length;
      card.append(node('summary',`${readable(stage.id)} · ${stateLabel(stage.status)}${stage.tasks.length?' · '+done+'/'+stage.tasks.length+' tasks':''}`));
      card.open=pipelineStageExpanded.has(stageKey) || !['completed','skipped','pending','cancelled'].includes(stage.status);
      card.addEventListener('toggle',()=>{if(card.open)pipelineStageExpanded.add(stageKey);else pipelineStageExpanded.delete(stageKey);});
      if(stage.error)card.append(saved('Technical details',stage.error));
      if(stage.plan_status && !stage.run)card.append(node('p','Plan: '+stateLabel(stage.plan_status)));
      for(const task of stage.tasks){
        const role=task.review_of?'Reviewer of '+readable(task.review_of):task.operation?'Connector · '+task.operation:'Worker';
        const engine=[task.backend?.type,task.backend?.model].filter(Boolean).join(' · ');
        card.append(node('p',`${readable(task.id)} · ${role} · ${stateLabel(task.status)} · ${task.attempts} attempt(s)`),node('p',engine,'hint'));
      }
      if(!stage.tasks.length)card.append(node('p',stage.status==='pending'?'Workers will be created when this stage is admitted.':'No execution workers recorded for this stage.','hint'));
      if(stage.run)card.append(button('Inspect stage execution',()=>openItem({kind:'run',id:stage.run}),'quiet'));
      stages.append(card);
    }
    body.append(stages);
    const history=node('details');history.append(node('summary',`Execution history · ${view.attempts.length} attempts across ${s.runs} runs`));
    history.open=pipelineExpanded.has(view.id);history.addEventListener('toggle',()=>{if(history.open)pipelineExpanded.add(view.id);else pipelineExpanded.delete(view.id);});
    for(const attempt of view.attempts){
      const card=node('div',undefined,'review-card');
      card.append(node('strong',`${attempt.task} · ${attempt.reviewer?'Reviewer':attempt.operation?'Connector':'Worker'} · ${stateLabel(attempt.state)}`),
        node('p',`${attempt.current?'Current stage run':'Earlier run'} · ${attempt.run}`,'hint'),
        node('p',`${attempt.backend?.model || attempt.operation || attempt.backend?.type || 'Executor unrecorded'} · ${attempt.tool_calls ?? 'Unknown'} tool calls`));
      if(attempt.review_target)card.append(node('p','Reviewed candidate attempt: '+attempt.review_target,'hint'));
      if(attempt.error)card.append(node('p',attempt.error,'feedback error'));
      card.append(saved('Attempt identity',attempt));history.append(card);
    }
    for(const run of view.runs || [])history.append(button(`${run.current?'Current':'Earlier'} run · ${run.id}`,()=>openItem({kind:'run',id:run.id}),'quiet'));
    const planning=node('details');planning.append(node('summary',`Planning history · ${view.plans.length} plans`));
    for(const plan of view.plans)planning.append(button(`${shortTitle(plan.request)} · ${stateLabel(plan.status)}`,()=>openItem({kind:'plan',id:plan.id}),'row-link'));
    history.append(planning);body.append(history,saved('Original request',view.request));
    const management=section('Manage job');
    const remove=button('Delete job…',()=>deletePipeline(view,remove),'danger');management.append(remove,
      node('p','Deletion first checks the whole job and shows its scope. Running work, uncertain effects and shared records must be resolved before deletion. Exported deliverables are kept.','hint'));
    body.append(management);
    const canvas=node('div',undefined,'canvas-host'),archive=node('div'),status=node('div');
    status.append(now,overview);archive.append(stages,history,saved('Original request',view.request),management);
    const projection=window.RelayWorkflow?.pipelineGraph(view) || {tasks:[],missing:[]};
    returnPipeline=null;
    const show=canvasPage(body,'pipeline:'+view.id,canvas,outputs,archive,status,`${projection.tasks.length} saved nodes · ${stateLabel(view.status)}`,
      jobChat(view.request,(view.stages || []).flatMap(stage=>stage.execution?.messages || [])));
    if(projection.missing.length)status.append(node('p','No saved node graph for stages: '+projection.missing.join(', ')+'. Stage order is not shown as a connection.','hint'));
    if(window.RelayWorkflow)disposeWorkflow=window.RelayWorkflow.mount(canvas,projection,{node,button,saved,stateLabel,outputFile:fileLink,outputThumbnail,openOutput,
      renderResults:(task,panel,current,historical)=>nodeResults(task,panel,current,historical,projection),
      selection:workflowSelections.get(projection.name),select:id=>{workflowSelections.set(projection.name,id);if(id)show.inspector();},reveal:()=>show('canvas'),
      afterInspect:(task,panel)=>panel.append(button('Open saved execution',()=>{returnPipeline={kind:'pipeline',id:view.id,title:view.title};openItem({kind:'run',id:task.run});},'quiet'))});
  }

  function renderRequest(view) {
    if (!changed(window.RelayWorkflow.renderKey(view))) return;
    heading(view.entry_mode === 'node' ? 'Node request' : view.entry_mode === 'conversation' ? 'Orchestrator request' : 'Planning request', stateLabel(view.status));
    const body=$('workspace-detail-body'),canvas=node('div',undefined,'canvas-host'),results=node('div'),history=node('div'),status=node('div');
    status.append(node('p',stateLabel(view.status)));history.append(saved('Exact request',view.prompt));
    results.append(node('p',view.result || 'No saved result.'));
    canvasPage(body,'request:'+view.request_id,canvas,results,history,status,'No saved node graph',jobChat(view.prompt,[],view.result));
    disposeWorkflow=mountUnavailable(canvas,'request:'+view.request_id);
  }
  function renderChat(view) {
    if (!changed(window.RelayWorkflow.renderKey(view))) return;
    heading(shortTitle(view.prompt), `${stateLabel(view.flow?.status || view.status)} · ${view.channel === 'desktop' ? 'Relay' : view.channel}`);
    const body=$('workspace-detail-body');body.replaceChildren();
    const stages=view.flow?.stages || [];
    if(stages.length){
      const results=node('section'),workflow=node('section',undefined,'canvas-host'),history=node('section'),status=node('div');
      status.append(node('p','Saved conversation and outcomes. Opening this view does not resume work.'));
      const showPage=canvasPage(body,'conversation:'+view.id,workflow,results,history,status,`${stages.length} saved stages`,conversationChat(view));
      const switchView=key=>showPage(key==='workflow'?'canvas':key);
      const active=stages.filter(stage=>stage.mode!=='legacy_plan'),latest=active.at(-1) || stages.at(-1);
      for(const stage of active.filter(s=>s.execution?.canvas_document || s.execution?.workflow_export)){
        const record=stage.execution.canvas_document || stage.execution.workflow_export;
        body.querySelector('.canvas-action-island').append(button(active.filter(s=>s.execution?.canvas_document || s.execution?.workflow_export).length===1?'Export':'Export '+record.title,()=>exportWorkflow(record),'quiet'));
      }
      const show=requestId=>{
        conversationStages.set(view.id,requestId);
        results.replaceChildren();
        const stage=stages.find(item=>item.request_id===requestId);
        if(!stage){renderConversationContent(results,view);return;}
        renderStage(results,stage);
      };
      const renderStage=(target,stage)=>{
        target.append(node('h2',stage.mode==='research'?'Research result':stage.mode==='legacy_plan'?'Earlier preparation':'Selected outcome'),node('p',stateLabel(stage.status),'hint'));
        if(stage.mode==='research'){
          const reads=view.flow.tasks.filter(task=>task.stage_request_id===stage.request_id && task.id.startsWith('read:') && task.status==='completed');
          const searches=reads.filter(task=>task.objective.startsWith('Search: ')).length,pages=reads.filter(task=>task.objective.startsWith('Read: ')).length;
          target.append(node('p',`Recorded reads: ${searches} ${searches===1?'search':'searches'} · ${pages} ${pages===1?'page read':'page reads'}`,'hint'));
        }
        const content=node('div');target.append(content);
        if(stage.conversation)renderConversationContent(content,stage.conversation);
        if(stage.execution)renderRun(stage.execution,stage.plan,content);
        else if(stage.conversation){} // The reply above is the complete text-only stage.
        else if(stage.mode==='legacy_plan' && stage.plan?.status==='blocked'){
          content.append(node('p','This earlier preparation failed before work started. Its proposal was never executed.'));
          if(!active.some(item=>item.mode==='research'&&item.option_index===stage.option_index))content.append(button('Start research',()=>chooseConversationOption(view,stage.option_index),'primary'));
          const history=saved('Earlier preparation details',stage.plan.planner_attempts || []);
          if(stage.plan.rejected_proposal)history.append(saved('Unexecuted proposal',stage.plan.rejected_proposal));content.append(history);
        }
        else if(stage.plan)renderPlan(stage.plan,content);
        else content.append(node('p',stage.mode==='research'?'Research is queued here. No plan submission is needed.':'Preparing the selected outcome’s steps…'));
      };
      const original=section('Original conversation');renderConversationContent(original,view);history.append(original);
      stages.filter(stage=>stage.mode==='legacy_plan').forEach(stage=>{const retained=section('Earlier preparation history');renderStage(retained,stage);history.append(retained);});
      active.slice(0,-1).forEach(stage=>{const retained=section('Earlier result');renderStage(retained,stage);history.append(retained);});
      const historicIds=new Set(stages.filter(stage=>stage.mode==='legacy_plan').map(stage=>stage.request_id));
      const projection=window.RelayWorkflow.pipelineGraph({id:'conversation:'+view.id,stages:active});
      disposeWorkflow=window.RelayWorkflow.mount(workflow,projection,{node,button,saved,stateLabel,outputFile:fileLink,outputThumbnail,openOutput,
        renderResults:(task,panel,current,historical)=>nodeResults(task,panel,current,historical,projection),
        selection:workflowSelections.get(projection.name),
        select:id=>{workflowSelections.set(projection.name,id);showPage.inspector(!!id);}});
      if(projection.missing.length)status.append(node('p','Some conversation stages have no saved node graph. Their messages and source reads remain in Results and History.','hint'));
      if(historicIds.size)workflow.append(button('View earlier preparation in History',()=>switchView('history'),'quiet'));
      const selectedStage=conversationStages.get(view.id);
      show(stages.some(stage=>stage.request_id===selectedStage)?selectedStage:latest?.request_id);
      document.body?.classList.add('canvas-workspace');
      showPage(canvasTabs.get('conversation:'+view.id) || 'canvas');
    }else {
      const canvas=node('div',undefined,'canvas-host'),results=node('div'),history=node('div'),status=node('div');
      renderConversationContent(results,view);history.append(saved('Saved conversation',view));status.append(node('p',stateLabel(view.status)));
      canvasPage(body,'conversation:'+view.id,canvas,results,history,status,'No saved node graph',conversationChat(view));
      disposeWorkflow=mountUnavailable(canvas,'conversation:'+view.id);
    }
    if(view.can_delete){const history=section('Conversation history');history.append(button('Delete conversation…',()=>deleteConversation(view),'danger'));body.append(history);}
  }
  function renderConversationContent(body,view) {
    const answer=node('div',undefined,'conversation-answer');
    const sourceFeedback=node('p',undefined,'feedback error');sourceFeedback.hidden=true;sourceFeedback.setAttribute('role','status');
    const openSource=async url=>{sourceFeedback.hidden=true;try{await native.core.invoke('workspace_open_chat_source',{id:String(view.id),url});}catch(error){sourceFeedback.textContent='Could not open this recorded source. Try again; if it still fails, refresh the job to check its source record.';sourceFeedback.hidden=false;}};
    const text=view.display_answer ?? view.answer ?? 'Waiting for the orchestrator…';
    if(typeof renderMarkdown==='function')renderMarkdown(answer,presentationMarkdown(text),{
      linkAllowed:url=>(view.evidence?.sources || []).some(source=>source.url===url),openLink:openSource
    });else answer.textContent=text;
    body.append(sourceFeedback,answer);
    if (view.next_options?.length) {
      const choices=section('Want to take this further?');
      view.next_options.forEach((option,index)=>{
        const card=node('div',undefined,'review-card');
        if(view.can_continue){const choose=button(option.title,()=>chooseConversationOption(view,index));choose.disabled=!view.option_digests?.[index];card.append(choose);}
        else card.append(node('h3',option.title));
        card.append(node('p',option.outcome));
        const webOnly=option.tools?.length && option.tools.every(tool=>['operations:web_search','operations:web_fetch'].includes(tool));
        card.append(node('p',webOnly?'Starts public-source research here using your configured AI provider: up to 2 searches and 6 page downloads.':'Adds planning steps here. Execution waits for your Start approval.','hint'));
        choices.append(card);
      });
      body.append(choices);
    }
    if(view.source_summary?.visible)body.append(node('p',view.source_summary.label,'hint'));
    if (view.research_advice || view.evidence?.sources?.length || view.evidence?.partial || view.claims?.length) {
      const sources=node('details',undefined,'conversation-sources');sources.append(node('summary','Source details'));
      if(view.research_advice){sources.append(node('p',view.research_advice.reason));const questions=node('ul');view.research_advice.questions.forEach(question=>questions.append(node('li',question)));sources.append(questions);}
      (view.evidence?.sources || []).forEach(source=>{
        const link=node('a',source.title || source.url,'file-link');link.href=source.url;
        link.onclick=event=>{event.preventDefault();event.stopPropagation();return openSource(source.url);};
        sources.append(link,node('p',source.kind==='page'?'Page read recorded':'Search reference · page read not recorded','hint'));
      });
      if(view.claims?.length){sources.append(node('h3','Claim references'));view.claims.forEach(claim=>sources.append(node('p',claim.statement),node('p',({generated:'Generated · no source reference',page_linked:'Linked to a page read · support not independently verified',search_reference:'Search reference · page support not checked',unresolved:'Source support unresolved'})[claim.state] || 'Source support unresolved','hint')));}
      if(view.evidence?.partial)sources.append(node('p','Some source receipts are unavailable or changed.','hint'));
      body.append(sources);
    }
    body.append(saved('Exact request',view.prompt));
    body.append(saved('Exact saved reply',view.answer || ''));
  }
  async function chooseConversationOption(view,index) {
    if(busy)return;
    const digest=view.option_digests?.[index];if(!digest)return;
    const key='conversation-option:'+view.id+':'+digest;
    const savedKey=storageKey?storageKey+':'+key:null;
    try{
      let identity=actionIdentities.get(key);
      if(!identity && savedKey)identity=localStorage.getItem(savedKey);
      if(!identity){identity=crypto.randomUUID();if(savedKey)localStorage.setItem(savedKey,identity);}
      actionIdentities.set(key,identity);busy=true;
      const receipt=await request('conversation-followup',{id:String(view.id),index,digest,request_id:identity});
      conversationStages.set(receipt.root_id,receipt.request_id);
      conversationViews.set(receipt.root_id,'results');
      if(savedKey)localStorage.removeItem(savedKey);
      selected={kind:'chat',id:receipt.root_id};detailKey=null;
      await openItem(selected);await refreshJobs();
    }catch(error){feedback('workspace-detail-feedback',String(error)+' Refresh to inspect the saved selection; choosing it again uses the same identity.',true);}
    finally{busy=false;}
  }
  async function deleteConversation(view) {
    if(busy)return;
    try {
      const review=await request('conversation-delete-preview',{id:String(view.id)});
      if(review.blockers.length){feedback('workspace-detail-feedback','Deletion blocked: '+review.blockers.join(' '),true);return;}
      const approved=await window.RelaySavedWork.confirm(`Delete local conversation history for “${review.title}”?\n\nThe saved question, reply, advisory data and ${review.trace_files} private trace files will be removed. Submission and delivery identities remain to prevent replay. Frozen attachments, other jobs and messenger messages remain. This cannot be undone.`,'Delete conversation');
      if(!approved)return;
      busy=true;
      const result=await request('conversation-delete',{id:review.id,digest:review.digest});
      selected=null;navigate('jobs');await refreshJobs();
      if(result.status!=='complete')$('workspace-jobs-count').textContent='Conversation deleted. Trace cleanup needs recovery: '+result.error;
    } catch(error){feedback('workspace-detail-feedback',String(error),true);}
    finally{busy=false;}
  }
  async function planAction(plan, verb, controls) {
    if(verb==='archive' && !await window.RelaySavedWork.confirm('Remove this job from Jobs and Review? Files, decisions and recovery history are retained. Enable Show removed jobs to view or restore it.','Remove job'))return;
    if (busy) return; busy = true; controls.forEach(b => b.disabled = true);
    feedback('workspace-detail-feedback', verb === 'prepare' ? 'Preparing the exact review…' : 'Recording your decision…');
    try {
      const value={plan_id:plan.id,verb,review_digest:plan.review_digest};const key=JSON.stringify(value);
      if(!actionIdentities.has(key))actionIdentities.set(key,crypto.randomUUID());value.request_id=actionIdentities.get(key);
      const result = await request(verb === 'prepare' ? 'plan-prepare' : 'plan-decide', value);
      feedback('workspace-detail-feedback', result.message || 'The current plan is ready for review.');
      if(verb==='archive'){selected=null;navigate('jobs');}
    } catch (error) { feedback('workspace-detail-feedback', String(error) + ' Refresh to inspect the saved state before another decision.', true); }
    finally { busy = false; detailKey = null; if(selected)await openItem(selected, true); await refreshJobs(); }
  }
  function renderPlan(plan,container=null) {
    if(!container){
      if(!changed(JSON.stringify(plan)))return;heading(shortTitle(plan.request),`${stateLabel(plan.status)} · Relay`);
      const body=$('workspace-detail-body'),scope=node('div'),history=node('div'),canvas=node('div',undefined,'canvas-host'),status=node('div');
      renderPlan(plan,scope);
      const tasks=(plan.plan?.tasks || []).map(task=>({...task,status:'proposed',planned_inputs:task.inputs || [],planned_outputs:task.outputs || []}));
      history.append(saved('Exact request',plan.request),saved('Saved plan',plan.plan || null));
      status.append(node('p','This is a saved proposal. Viewing its canvas does not start work.'),button('Review scope & controls',()=>show('results'),'quiet'));
      const show=canvasPage(body,'plan:'+plan.id,canvas,scope,history,status,`${tasks.length} proposed steps · not executed`,jobChat(plan.request,[],plan.preview || plan.error));
      if(window.RelayWorkflow)disposeWorkflow=window.RelayWorkflow.mount(canvas,{name:'plan:'+plan.id,tasks},{node,button,saved,stateLabel,outputFile:fileLink,select:id=>{if(id)show.inspector();},legend:'Saved proposal · not executed'});
      return;
    }
    const body=container || $('workspace-detail-body');body.replaceChildren();
    body.append(saved('Exact request', plan.request));
    const preview = section('Proposed plan');preview.append(node('p',plan.plan?.brief || (plan.status==='blocked'?'Could not prepare the requested steps. No work has started.':plan.preview || 'Waiting for the planner. No execution has started.').split('\n')[0]),saved('Scope, tools and limits',plan.preview || plan.error || 'No executable plan is saved.'));body.append(preview);
    if(plan.planner_attempts?.length){const diagnostics=saved('Planning diagnostics',plan.planner_attempts);if(plan.rejected_proposal)diagnostics.append(saved('Rejected proposal — never executed',plan.rejected_proposal));preview.append(diagnostics);}
    renderSources(body,plan.research,null,plan);
    if (plan.channel !== 'desktop') body.append(node('p','You can review and start this saved plan here. Results keep their original '+plan.channel+' destination.','hint'));
    if (plan.channel === 'desktop' && ['needs_input','blocked','ready'].includes(plan.status)) body.append(button('Revise plan', () => newTask({parent_id:plan.id, project:plan.project || '',research_mode:plan.research_mode || 'suggest'}), 'quiet'));
    if(plan.archived)body.append(button('Restore to Jobs',()=>planAction(plan,'restore',[]),'primary'));
    else if(['discarded','superseded','blocked','needs_input'].includes(plan.status))body.append(button('Remove job…',()=>planAction(plan,'archive',[]),'danger'));
    if (plan.review_error) { body.append(node('p', plan.review_error, 'feedback error'));if(plan.status==='ready')body.append(button('Discard plan',()=>planAction(plan,'discard',[])));return; }
    if (plan.status !== 'ready') return;
    const actions = node('div',undefined,'actions'); const controls = [];
    if(plan.execution_blocker)body.append(node('p',plan.execution_blocker,'feedback error'));
    else if (plan.planning_only || plan.expired) {
      const prepare = button(plan.expired?'Renew plan review':'Review for Start', () => planAction(plan,'prepare',controls), 'primary'); controls.push(prepare); actions.append(prepare);
      body.append(node('p',plan.expired?'The old approval expired. Renew its review, then inspect the saved documents before Start. No workers start during renewal.':'This is a planning draft. Review for Start prepares the exact execution scope; it does not run workers.','hint'));
    } else {
      const docs = section('Plan documents'); const opened = new Set();
      const check = document.createElement('input'); check.type = 'checkbox'; check.disabled = (plan.documents || []).length > 0;
      const confirm = node('label',undefined,'revision-confirm'); confirm.append(check,node('span','I reviewed the plan, its limits and every attached document.'));
      for (const doc of plan.documents || []) {
        const d = saved(doc.filename, doc.content); d.addEventListener('toggle', () => { if (d.open) opened.add(doc.id); check.disabled = opened.size !== plan.documents.length; }); docs.append(d);
      }
      body.append(docs,node('p','Open each document to enable the final review confirmation.','hint'),confirm);
      const start = button('Start', () => planAction(plan,'start',controls), 'primary'); start.disabled = true;
      check.onchange = () => { start.disabled = !check.checked || busy; }; controls.push(start); actions.append(start);
    }
    const discard = button('Discard plan', () => planAction(plan,'discard',controls)); controls.push(discard); actions.append(discard);body.insertBefore(actions,preview);
  }
  function fileLink(file, text, onReveal) {
    let errorNote;
    const label=file.display_name || file.purpose || file.path.split('/').pop().replace(/\.[^.]+$/,'').replace(/[-_]/g,' ');
    const link=button(text || label,async () => {
      if(link.disabled) return;
      link.disabled=true;
      if(errorNote)errorNote.remove();
      try { await native.core.invoke('workspace_reveal_artifact',{artifact:file.id});await onReveal?.(); }
      catch(error) { errorNote=node('p',String(error),'feedback error'); errorNote.setAttribute('role','alert'); link.insertAdjacentElement('afterend',errorNote); }
      finally { link.disabled=false; }
    },'quiet file-link');
    link.setAttribute('aria-label',`Show ${file.path} in Finder · saved version ${file.sha256 || file.id}`);
    link.title=`Show exact saved file in Finder${file.sha256 ? ' · SHA-256 '+file.sha256 : ''}`;
    return link;
  }
  function outputFile(file, texts, versions) {
    const row = node('div',undefined,'file-row'); row.append(fileLink(file));
    if(/\.(png|jpe?g|webp|gif)$/i.test(file.path)){
      const preview=button('View image',async()=>{
        preview.disabled=true;
        try{
          const value=await imagePreview(file,true);
          if(!row.isConnected)return;
          const img=node('img',undefined,'artifact-image');img.src=value.data_url;img.alt=file.purpose || file.path;row.append(img);preview.remove();
          if(value.transformation && value.transformation!=='original')row.append(node('p',value.transformation,'hint'));
        }catch(error){row.append(node('p',String(error),'feedback error'));preview.disabled=false;}
      },'quiet');
      row.append(preview);
    }
    for(const change of versions?.changes || []) {
      const direct=change.old.id===file.id || change.new.id===file.id;
      const affected=(change.tasks || []).some(t=>t.task===file.task && t.attempt===file.attempt);
      if(direct || affected)row.append(versions.changeLink(change,direct ? change.kind==='external'?'Source changed':change.label : 'Earlier source version · '+change.old.path));
    }
    const text = texts?.find(t => t.path === file.path && t.attempt === file.attempt && t.task === file.task);
    if(isTextDocument(file) || /\.pdf$/i.test(file.path))row.append(outputDocumentPreview(file));
    else if (text) row.append(saved(text.truncated ? 'Read excerpt' : 'Read',text.text));
    return row;
  }
  const artifactLocations=new Map();
  function outputLocation(file){
    const row=node('div',undefined,'artifact-location'),folder=node('span','Loading folder…','artifact-folder');
    const key=JSON.stringify([file.id,file.sha256]);
    row.append(fileLink(file,'Show in Finder',()=>{artifactLocations.delete(key);return load();}),folder);
    async function load(){
      try{
        if(!artifactLocations.has(key)){
          const promise=request('workspace-artifact',{artifact:file.id,location:true});
          artifactLocations.set(key,promise);promise.catch(()=>artifactLocations.delete(key));
          if(artifactLocations.size>64)artifactLocations.delete(artifactLocations.keys().next().value);
        }
        const value=await artifactLocations.get(key);if(!row.isConnected)return;
        folder.textContent=value.path?value.path.replace(/[/\\][^/\\]+$/,''):value.folder;
        folder.title=folder.textContent+(value.published===false?' · Created when shown in Finder':'');
        if(value.published===false)folder.append(node('span',' · not exported yet','hint'));
      }catch(error){if(row.isConnected){folder.textContent='Folder unavailable';folder.title=String(error);}}
    }
    load();return row;
  }
  function nodeResults(task,panel,current,historical,view,chooseOutput,chat) {
    const previews=[];
    if(task.outdated)panel.append(node('p','Inputs changed since this result. Run this node to update it.','hint'));
    const publicFiles=current.filter(f=>f.result_role!=='technical');
    for(const file of publicFiles){
      const row=node('div',undefined,'node-result');
      row.append(node('h4',file.display_name || file.purpose || file.path.split('/').pop()));
      if(/\.(png|jpe?g|webp|gif)$/i.test(file.path)){
        const preview=outputThumbnail(file);previews.push(preview);row.append(preview);
      }else if(/\.html?$/i.test(file.path)){
        const preview=outputHtmlPreview(file);previews.push(preview);row.append(preview);
      }
      if(file.open_with){
        const open=button('Open in '+file.open_with,async()=>{
          open.disabled=true;
          try{await request('workspace-open-artifact',{artifact:file.id,sha256:file.sha256});}
          catch(error){row.append(node('p',String(error),'feedback error'));}
          finally{open.disabled=false;}
        },'primary');row.append(open);
      }
      row.append(outputLocation(file));
      const text=view.output_texts?.find(t=>t.path===file.path && t.attempt===file.attempt && t.task===file.task);
      if(isTextDocument(file) || /\.pdf$/i.test(file.path)){const preview=outputDocumentPreview(file);previews.push(preview);row.append(preview);}
      else if(text)row.append(saved(text.truncated?'Read excerpt':'Read',text.text));
      panel.append(row);
    }
    if(view.canvas_run && task.status==='completed' && publicFiles.length){
      const actions=node('div',undefined,'result-actions'),choices=node('div');
      const choose=callback=>{
        choices.replaceChildren();
        if(publicFiles.length===1){callback(publicFiles[0],choices);return;}
        for(const file of publicFiles)choices.append(button(file.display_name || file.path,()=>{
          choices.replaceChildren();callback(file,choices);
        },'quiet'));
      };
      actions.append(button('Use output…',()=>choose(chooseOutput),'quiet'),
        button('Chat about result',()=>choose(chat),'quiet'),choices);panel.append(actions);
    }
    if(task.versions?.length){
      const versions=saved('Versions ('+task.versions.length+')','');versions.querySelector('pre').remove();
      task.versions.forEach((v,i)=>{
        versions.append(node('h4','Version '+(i+1)+' · '+stateLabel(v.status)));
        if(v.error)versions.append(node('p',v.error,'feedback error'));
        if(v.prompt)versions.append(saved('Prompt',v.prompt));
        for(const file of v.files)versions.append(outputFile(file));
      });panel.append(versions);
    }else if(historical.length){
      const older=saved('Previous results','');older.querySelector('pre').remove();
      historical.forEach(file=>older.append(outputFile(file)));panel.append(older);
    }
    return ()=>previews.forEach(p=>p.disposeThumbnail?.());
  }
  function renderFileChanges(body,view,plan) {
    let scan=sourceScans.get(view.name);
    if(scan && scan.revision!==view.revision) {sourceScans.delete(view.name);scan=null;}
    const changes=[...(view.file_changes?.items || []),...(scan?.changes || [])];
    const panel=node('details',undefined,'detail-section file-versions');panel.append(node('summary',`File changes${changes.length?' ('+changes.length+')':''}`));
    const tools=node('div',undefined,'actions');
    const note=node('p',scan ? `Sources checked ${new Date(scan.checked_at*1000).toLocaleString()}.` : 'Checks for edits to the original attachments.','hint');
    const check=button('Check source files',async()=>{
      check.disabled=true;note.textContent='Checking the recorded original file locations…';
      try {
        const result=await request('workspace-source-changes',{run:view.name});
        if(!panel.isConnected)return;
        if(result.revision!==view.revision) {note.textContent='The job changed during inspection. Refresh this stage and check again.';return;}
        sourceScans.set(view.name,result);detailKey=null;renderRun(view,plan);
      } catch(error) {note.textContent=String(error);note.classList.add('error');}
      finally {check.disabled=!view.file_changes?.original_count;}
    },'quiet');
    check.disabled=!view.file_changes?.original_count;tools.append(check);
    panel.append(tools,note);
    if(!view.file_changes?.original_count)note.textContent='Original file locations were not recorded for this stage. Saved revisions and replacements can still be inspected.';
    if(scan) {
      for(const original of scan.originals || []) panel.append(node('p',`${original.name} · ${original.status==='changed'?'Source updated':original.status==='unchanged'?'Matches saved version':'Could not check'}${original.reason?' · '+original.reason:''}`,'hint'));
      if(scan.partial)panel.append(node('p','Only the first ten saved original files were checked. Other files remain unchecked.','hint'));
    }
    const openers=new Map();
    for(const change of changes) {
      const card=node('details',undefined,'version-change');card.open=openChanges.has(change.id);
      const title=node('summary');title.append(node('span',`${change.label} · ${change.old.path}`));card.append(title);
      card.addEventListener('toggle',()=>{if(card.open)openChanges.add(change.id);else openChanges.delete(change.id);});
      const versions=node('div',undefined,'version-pair');
      for(const [label,file] of [['Earlier saved version',change.old],[change.kind==='external'?'Edited original · not imported':'Recorded newer version',change.new]]) {
        const column=node('div');column.append(node('h3',label),file.id?fileLink(file):node('p',file.path,'path'),node('p',`${file.bytes} bytes · SHA-256 ${file.sha256.slice(0,12)}`,'hint'));versions.append(column);
      }
      card.append(versions);
      if(change.incomplete)card.append(node('p','Dependency evidence is incomplete. Some affected steps may be missing.','hint'));
      const result=node('div');result.setAttribute('aria-live','polite');
      const compare=button('Compare versions',async()=>{
        if(compare.disabled)return;compare.disabled=true;result.replaceChildren(node('p','Comparing these exact versions…','hint'));
        try {
          const value=await request('workspace-compare',{run:view.name,change:change.id,new_sha256:change.kind==='external'?change.new.sha256:null});
          if(!result.isConnected)return;
          result.replaceChildren(node('p',value.preview_note,'hint'));
          if(value.diff)result.append(node('pre',value.diff,'version-diff'));
          if(value.truncated)result.append(node('p','Text comparison truncated; the complete files remain unchanged.','hint'));
        }catch(error){result.replaceChildren(node('p',String(error),'feedback error'));}
        finally{compare.disabled=false;}
      },'quiet');
      card.append(compare,result);panel.append(card);
      openers.set(change.id,()=>{panel.open=true;card.open=true;openChanges.add(change.id);card.scrollIntoView({block:'nearest'});compare.onclick();});
    }
    if(changes.length)panel.append(node('p',view.file_changes?.note || 'Recorded input dependencies do not prove semantic use. Inspection does not authorize reruns.','hint'));
    return {panel,tools,note,changes,changeLink:(change,label)=>button(label,()=>openers.get(change.id)?.(),'quiet version-change-link')};
  }
  async function runAction(view, verb, controls, group=null, note='') {
    if(verb==='archive' && !await window.RelaySavedWork.confirm('Remove this job from Jobs and Review? Files, decisions and recovery history are retained. Enable Show removed jobs to view or restore it.','Remove job'))return;
    if (busy) return; busy = true; controls.forEach(b=>b.disabled=true);
    const value = {run:view.name, verb, review_digest:view.review_digest, group, note};
    const key = JSON.stringify(value); if (!actionIdentities.has(key)) actionIdentities.set(key,crypto.randomUUID()); value.request_id = actionIdentities.get(key);
    try {
      const result = await request('workspace-decide',value); feedback('workspace-detail-feedback',result.message);
      if(verb==='archive'){selected=null;navigate('jobs');}
    } catch(error) { feedback('workspace-detail-feedback',String(error)+' Refresh to inspect the current state and action receipt.',true); }
    finally { busy=false; detailKey=null; if(selected)await openItem(selected, true); await refreshJobs(); }
  }
  function renderRun(view, plan,container=null) {
    const key = JSON.stringify({view:{...view,captured_at:0},plan});if(!container){if (!changed(key)) return;heading(shortTitle(view.brief),`${stateLabel(view.status)} · ${view.channel === 'desktop' ? 'Relay' : view.channel}`);}
    const body=container || $('workspace-detail-body'); body.replaceChildren();
    body.append(button('Manage / delete job…',()=>window.RelaySavedWork.open('runs',view.name),'danger'));
    const terminal=['completed','cancelled'].includes(view.status);
    const attention=terminal ? [] : (view.tasks || []).filter(t=>['blocked','uncertain'].includes(t.status));
    const controls=[];
    const status=node('div',undefined,'job-summary');
    if(view.source_warning)status.append(node('p',view.source_warning,'feedback error'));
    const messages={cancelled:'This job was cancelled. Its saved files and history remain available.',completed:'Work finished. Your results are saved below.',paused:'Work is paused.',awaiting_user:view.controllable || view.local?'Review the result below to continue.':'Review this result through its saved workflow.',uncertain:'Check what happened before continuing this job.',blocked:'A step needs attention before work can continue.'};
    status.append(node('p',messages[view.status] || 'Relay is working through the steps below.'));
    if(attention.length) {
      const task=attention[0];if(task.error)status.append(node('p',task.error,'feedback error'));status.append(button('Inspect step',()=>disposeWorkflow.showStep?.(task.id),'primary'));
      if(view.status==='blocked' && view.controllable && plan && !attention.some(t=>t.status==='uncertain'))status.append(button('Plan a new attempt',()=>{
        newTask({goal:plan.request,project:plan.project || '',research_mode:plan.research_mode || 'suggest',constraints:'New attempt after stopped job '+view.name+'. Original files and history stay saved. No prior outputs are selected or reused automatically.\nRecorded failure: '+task.error});
        $('workspace-compose-title').textContent='Plan a new attempt';$('workspace-compose-context').textContent='This proposes a separate workflow. Attach any required source files; review its scope before Start. The stopped job and its outputs stay saved.';
        $('workspace-constraints').closest('details').open=true;
      },'quiet'));
    } else if(view.controls?.includes('resume')) {
      const resume=button('Resume work',()=>runAction(view,'resume',controls),'primary');controls.push(resume);status.append(resume);
    } else if(view.local && view.status==='completed') {
      status.append(button(view.node ? 'Continue node' : 'Plan next step',()=>newTask({previous_run:view.name,entry_mode:view.node ? 'node' : 'plan',project:plan?.project || '',research_mode:plan?.research_mode || 'suggest'}),'primary'));
    }
    if(view.control_error)status.append(node('p',view.control_error,'hint'));
    if(view.remove_blocker)status.append(node('p',view.remove_blocker,'hint'));
    for(const verb of (view.controls || []).filter(v=>['cancel','archive','restore'].includes(v))) {
      const b=button({cancel:view.controllable===false?'Cancel this stage':'Cancel job',archive:'Remove job…',restore:'Restore to Jobs'}[verb],()=>runAction(view,verb,controls),verb==='restore'?'primary':'danger');controls.push(b);status.append(b);
    }
    body.append(status);
    if (view.node) {
      const spec=section('Node');
      const doc=view.node.document;
      spec.append(node('p',`${doc.id} · ${doc.operation || doc.content?.family || 'registered operation'}`));
      spec.append(saved('Node file',doc),saved('Node specification',view.node.schema));
      if(view.node.operation) spec.append(saved('Operation definition',view.node.operation));
      body.append(spec);
    }
    const versions=renderFileChanges(body,view,plan);
    let revealCanvas=()=>{},revealHistory=()=>{},revealInspector=()=>{},revealChat=()=>{};
    const chatContent=node('div',undefined,'job-chat-messages');
    const drawChat=id=>chatContent.replaceChildren(view.canvas_run?resultChat(view,view.tasks.find(t=>t.id===id)):jobChat(plan?.request || view.brief,view.messages || []));
    drawChat(workflowSelections.get(view.name));
    const originalChangeLink=versions.changeLink;
    versions.changeLink=(change,label)=>{const link=originalChangeLink(change,label),action=link.onclick;link.onclick=()=>{revealHistory();action();};return link;};
    const fileRow=(file,texts)=>outputFile(file,texts,versions);
    const results=section('Results');const reviewed=new Set();
    for(const binding of view.delivered_outputs || [])results.append(node('p',`${binding.port} · ${binding.review_status}`,'hint'));
    for(const group of view.selection_groups || []) {
      const card=node('div',undefined,'review-card result-review');card.append(node('p',group.purpose,'review-purpose'));
      for(const member of group.members) {
        reviewed.add(member.id);const file=(view.latest_outputs || []).find(f=>f.id===member.id) || member;card.append(fileRow(file,view.output_texts));
      }
      const review=node('details',undefined,'result-decision');review.open=openSelections.has(group.id);
      review.append(node('summary','Review result'));
      review.addEventListener('toggle',()=>{if(review.open)openSelections.add(group.id);else openSelections.delete(group.id);});
      if(group.concerns)review.append(saved('Independent review',group.concerns));
      const label=node('label','Decision note');const note=document.createElement('textarea');note.id='selection-note-'+group.id;label.htmlFor=note.id;note.maxLength=12000;note.value=selectionNotes.get(group.id) || '';
      const check=document.createElement('input');check.type='checkbox';const confirmation=node('label',undefined,'revision-confirm');confirmation.append(check,node('span','I inspected these exact outputs and their review, and select this complete set.'));
      const accept=button('Select this output set',()=>runAction(view,'select',controls,group.id,note.value),'primary');accept.disabled=true;
      const enable=()=>{accept.disabled=busy || !check.checked || !note.value.trim();};check.onchange=enable;note.oninput=()=>{selectionNotes.set(group.id,note.value);enable();};controls.push(accept);
      review.append(label,note,confirmation,accept);card.append(review);results.append(card);
    }
    const files=window.RelayWorkflow.resultFiles(view,reviewed);
    files.primary.forEach(file=>results.append(fileRow(file,view.output_texts)));
    if(!view.latest_outputs?.length)results.append(node('p',view.historical_outputs?.length?'Earlier results are saved under Details.':terminal?'No result files were saved.':'Results will appear here as work completes.','muted'));
    if(files.other.length) {const other=saved('More files ('+files.other.length+')','');other.querySelector('pre').remove();files.other.forEach(file=>other.append(fileRow(file,view.output_texts)));results.append(other);}
    if(view.file_changes?.original_count){versions.tools.append(versions.note);results.append(versions.tools);}
    body.append(results);
    renderSources(body,view.research,view,plan);
    const canvasHost=node('div',undefined,'canvas-host'),nodeRunActions=new Map();
    if(!container)disposeWorkflow=window.RelayWorkflow.mount(canvasHost,view,{node,button,saved,stateLabel,outputFile:fileRow,fileLink,outputThumbnail,openOutput,...versions,
      runNode:view.canvas_run?(task,host,reset)=>nodeRunActions.get(task.id)?.(host,reset):null,
      reveal:()=>revealCanvas(),selection:workflowSelections.get(view.name),select:(id,prefs)=>{workflowSelections.set(view.name,id);drawChat(id);if(id && prefs?.reveal!==false)revealInspector();},
      renderResults:(task,panel,current,historical)=>nodeResults(task,panel,current,historical,view,
        (file,host)=>resultDraft(view,task,'input',file,host),
        file=>{resultChoices.set(view.name,file.id);drawChat(task.id);revealChat();}),
      afterInspect:(task,panel,panes)=>{
        if(task.reused_source && !view.canvas_document){
          panel.append(node('p','Completed source · exact saved result. This node was not rerun.','hint'),
            button('Open original run',()=>openItem({kind:'run',id:task.run}),'quiet'));return;
        }
        if(!view.canvas_run || !['completed','blocked','draft'].includes(task.status))return;
        const actions=node('div',undefined,'result-actions');
        if(view.canvas_document || task.prompt || !task.execution)nodeRunActions.set(task.id,nodePromptEditor(view,task,actions));
        else actions.append(button('Edit and rerun',()=>resultDraft(view,task,'edit'),'quiet'));
        if(view.canvas_document)actions.append(button('Edit inputs & setup',()=>editDraft({...view.canvas_document,display:view},false,null,task.id),'quiet'));
        panes.inputPane.insertBefore(actions,panes.inputPane.children[0] || null);
      },
      expanded:workflowExpanded.get(view.name),expand:value=>workflowExpanded.set(view.name,value)});
    if(versions.changes.length || view.file_changes?.original_count)body.append(versions.panel);
    const details=saved('Details','');details.classList.add('job-details');details.querySelector('pre').remove();details.open=openJobDetails.has(view.name);
    details.addEventListener('toggle',()=>{if(details.open)openJobDetails.add(view.name);else openJobDetails.delete(view.name);});
    details.append(saved('Original request',plan?.request || view.brief),saved('Job identity',{run:view.name,status:view.status,channel:view.channel}),saved('File records',{current:view.latest_outputs || [],previous:view.historical_outputs || []}));
    if(view.historical_outputs?.length){const old=saved('Previous results','');old.querySelector('pre').remove();view.historical_outputs.forEach(file=>old.append(fileRow(file)));details.append(old);}
    if(!versions.changes.length && !view.file_changes?.original_count)details.append(versions.panel);
    const history=saved('Activity','');history.querySelector('pre').remove();history.className='message-history';(view.messages || []).forEach(event=>history.append(node('pre',event.text)));details.append(history,saved('Action receipts',view.receipts || []));body.append(details);
    const options=saved('Job options','');options.querySelector('pre').remove();const actions=node('div',undefined,'actions');
    for(const verb of view.controls || []) {
      if(['cancel','archive','restore'].includes(verb) || (verb==='resume' && !attention.length))continue;const b=button({pause:'Pause work',resume:'Resume work'}[verb],()=>runAction(view,verb,controls));controls.push(b);actions.append(b);
    }
    options.append(actions);
    if(view.controls?.length)options.append(node('p','Pause stops new steps from starting. A running step may still finish after cancellation.','hint'));body.append(options);
    if(!container){
      const historyHost=node('div'),resultsHost=node('div');
      for(const child of [...body.children])if(child!==results && child!==status)historyHost.append(child);
      resultsHost.append(results);
      const show=canvasPage(body,view.name,canvasHost,resultsHost,historyHost,status,`${view.tasks?.length || 0} steps · ${stateLabel(view.status)}`,chatContent,view.canvas_document?{...view.canvas_document,display:view}:null);
      if(view.workflow_export && !view.canvas_document)body.querySelector('.canvas-action-island').append(button('Export',()=>exportWorkflow(view.workflow_export),'quiet'));
      revealInspector=()=>show.inspector();
      revealChat=()=>show.chat();
      if(workflowSelections.get(view.name))show.inspector();
      revealCanvas=()=>show('canvas');
      revealHistory=()=>show('history');
    }

  }
  function renderTask(view) {
    if (document.activeElement?.id === 'workspace-task-instruction') return;
    if(!changed(window.RelayWorkflow.renderKey(view))) return;
    heading(shortTitle(view.task.title || view.task.id), `${view.task.backend} · ${stateLabel(view.task.status)}`);
    const body=$('workspace-detail-body');body.replaceChildren();
    body.append(button('Manage / delete task…',()=>window.RelaySavedWork.open('tasks',view.task.id),'danger'));
    if(view.approvals?.length)body.append(button('Review pending requests',()=>{$('review-decisions').click();},'primary'));
    const history=section('Conversation');for(const event of view.messages || []){const card=node('div',undefined,'review-card');card.append(node('strong',event.role==='user'?'You':'Relay'),node('pre',event.text),node('p',[event.channel,event.status].filter(Boolean).join(' · '),'hint'));history.append(card);}body.append(history,node('p',view.history_note,'hint'));
    const form=node('form');const label=node('label','Follow-up instruction');const input=document.createElement('textarea');input.id='workspace-task-instruction';label.htmlFor=input.id;input.required=true;
    const send=node('button','Send instruction','primary');send.type='submit';send.disabled=!view.can_send;
    const taskKey = storageKey ? storageKey + ':instruction:' + view.task.id : null;
    let pending=null;
    try { pending = taskKey ? JSON.parse(localStorage.getItem(taskKey) || 'null') : null; } catch (_) {}
    if (pending) input.value = pending.text;
    form.onsubmit=async event=>{event.preventDefault();if(busy || !view.can_send || !input.value.trim())return;if(pending && pending.text!==input.value){feedback('workspace-detail-feedback','The previous instruction is unconfirmed. Refresh its receipt before sending different text.',true);return;}
      pending ||= {request_id:crypto.randomUUID(),task_id:view.task.id,text:input.value};busy=true;send.disabled=true;
      try{if(!taskKey)throw Error('Relay history is not connected yet.');localStorage.setItem(taskKey,JSON.stringify(pending));const result=await request('task-send',pending);feedback('workspace-detail-feedback',result.message);if(result.status!=='uncertain'){localStorage.removeItem(taskKey);pending=null;input.value='';}}catch(error){feedback('workspace-detail-feedback',String(error)+' Retry unchanged text to use the same receipt identity.',true);}finally{busy=false;send.disabled=!view.can_send;}
    };
    form.append(label,input,send);body.append(form);
    if(!view.can_send)body.append(node('p','Wait for this task to be ready before sending another instruction.','hint'));
    if(view.can_stop)body.append(button('Stop current work',async()=>{try{const result=await request('task-stop',{task_id:view.task.id});feedback('workspace-detail-feedback',result.message);detailKey=null;await openItem(selected,true);}catch(error){feedback('workspace-detail-feedback',String(error),true);}},'danger'));
    const details=saved('Details','');details.querySelector('pre').remove();details.append(saved('Job identity',view.task),saved('Submission receipts',view.commands || []));body.append(details);
    const canvas=node('div',undefined,'canvas-host'),archive=node('div'),results=node('div'),status=node('div'),chat=node('div');
    for(const child of [...body.children])archive.append(child);
    chat.append(history,form);
    status.append(node('p',stateLabel(view.task.status)));
    results.append(node('p','This legacy task has no saved workflow definition. Its conversation and receipts remain available.'));
    canvasPage(body,'task:'+view.task.id,canvas,results,archive,status,'No saved node graph',chat);
    disposeWorkflow=mountUnavailable(canvas,'task:'+view.task.id);

  }
  document.querySelectorAll('[data-destination]').forEach(b=>b.onclick=()=>navigate(b.dataset.destination));
  $('settings-back-canvas').onclick=backToCanvas;
  $('connections-back-canvas').onclick=backToCanvas;
  $('workspace-new').onclick=()=>editDraft(null,false,null,null,true);
  $('workspace-jobs-toggle').onclick=()=>showJobs($('workspace-content'));
  $('workspace-compose-back').onclick=()=>navigate('jobs');$('workspace-detail-back').onclick=()=>navigate('jobs');
  $('workspace-search').oninput=renderJobs;$('workspace-jobs-more').onclick=()=>refreshJobs(true);
  $('workspace-catalog-search').oninput=renderCatalog;

  $('workspace-show-removed').onchange=()=>refreshJobs();
  $('workspace-create-form').onsubmit=submitPlan;
  $('workspace-attach').onclick=async()=>{try{const picked=await native.dialog.open({multiple:true,directory:false,title:'Choose task inputs'});if(picked){const paths=Array.isArray(picked)?picked:[picked];const combined=[...new Set([...attachments,...paths])];if(combined.length>10)return feedback('workspace-compose-feedback','Select at most ten files.',true);attachments=combined;renderAttachments();}}catch(error){feedback('workspace-compose-feedback',String(error),true);}};
  $('workspace-project-pick').onclick=async()=>{try{const picked=await native.dialog.open({multiple:false,directory:true,title:'Choose project folder'});if(typeof picked==='string')$('workspace-project').value=picked;}catch(error){feedback('workspace-compose-feedback',String(error),true);}};
  $('workspace-detail-refresh').onclick=()=>{if(selected && !busy)openItem(selected,true);};
  $('refresh').addEventListener('click',()=>{refreshJobs();if(destination==='detail' && selected && !busy)openItem(selected,true);});
  window.RelayWorkspace={navigate,newTask,refreshJobs};
  if(native){if(window.RelayNodeEditor)editDraft();else navigate('jobs',false);setInterval(()=>{if(document.hidden || busy)return;if(['jobs','reviews'].includes(destination))refreshJobs();if(destination==='detail' && selected)openItem(selected,true);},8000);}
})();
