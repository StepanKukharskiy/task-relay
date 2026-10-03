/* Main workspace; all authorization and receipt checks belong to the shared runtime. */
(() => {
  const $ = id => document.getElementById(id);
  const native = window.__TAURI__;
  const request = (path, value = {}) => native.core.invoke('relay_request', {path, value});
  const routes = {jobs:'workspace-jobs', compose:'workspace-compose', detail:'workspace-detail', reviews:'workspace-reviews', connections:'workspace-connections', settings:'workspace-settings', saved:'saved-work-panel', sessions:'computer-sessions-panel', 'agent-reviews':'review', revisions:'revisions'};
  const labels = {jobs:'Jobs', compose:'Jobs / New task', detail:'Jobs / Job', reviews:'Review', connections:'Connections', settings:'Settings', saved:'Jobs / Saved records', sessions:'Jobs / Safari sessions', 'agent-reviews':'Review / Agent requests', revisions:'Review / Revision candidates'};
  let destination = 'jobs', items = [], next = null, jobsTicket = 0, detailTicket = 0, selected = null, detailKey = null;
  let canPlan = false, busy = false, attachments = [], parent = null, previousRun = null, entryMode = 'conversation', researchMode = 'suggest', pendingPlan = null, storageKey = null, jobsRenderKey = null;
  const actionIdentities = new Map();
  const selectionNotes = new Map();
  const workflowSelections = new Map();
  const workflowExpanded = new Map();
  const openSelections = new Set();
  const sourceScans = new Map();
  const openChanges = new Set();
  const openJobDetails = new Set();
  let disposeWorkflow = () => {};
  const conversationStages=new Map();
  const conversationViews=new Map();
  function node(tag, value, className) { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; if (className) n.className = className; return n; }
  function button(label, action, className = '') { const b = node('button', label, className); b.type = 'button'; b.onclick = action; return b; }
  function feedback(id, value, error = false) { const n = $(id); n.textContent = value; n.hidden = !value; n.classList.toggle('error', error); }
  function saved(label, value) { const d = node('details'); d.append(node('summary', label), node('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); return d; }
  function section(title) { const s = node('section', undefined, 'detail-section'); s.append(node('h2', title)); return s; }
  function shortTitle(value) { return (value || 'Job').split('\n')[0].slice(0,180); }
  function stateLabel(status) { return ({awaiting_user:'Needs review', needs_input:'Needs input', ready:'Plan ready', sending:'Thinking', answered:'Answered', failed:'Failed', queued:'Queued', active:'In progress', running:'In progress', launching:'Starting', waiting:'Waiting', paused:'Paused', idle:'Ready', accepted:'Saved', uncertain:'Needs inspection', discarded:'Discarded', completed:'Completed', cancelled:'Cancelled', blocked:'Blocked', rejected:'Rejected',proposed:'Proposed · not run'})[status] || status; }
  function navigate(route, focus = true) {
    if (!routes[route]) route = 'jobs';
    destination = route;
    document.querySelectorAll('.workspace-view').forEach(n => { n.hidden = n.id !== routes[route]; });
    $('workspace-breadcrumb').textContent = labels[route];
    const primary = ['compose','detail','saved','sessions'].includes(route) ? 'jobs' : ['agent-reviews','revisions'].includes(route) ? 'reviews' : route;
    document.querySelectorAll('[data-destination]').forEach(b => { if (b.dataset.destination === primary) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current'); });
    if (focus) { $(routes[route]).querySelector('h1,h2')?.focus({preventScroll:true}); window.scrollTo(0,0); }
    if (route === 'jobs' || route === 'reviews') refreshJobs();
  }
  function renderJobs() {
    const term = $('workspace-search').value.trim().toLowerCase();
    const key=JSON.stringify({term,items:items.map(({stamp,...item})=>item)});if(key===jobsRenderKey)return;jobsRenderKey=key;
    const filtered = items.filter(i => `${i.title} ${i.status} ${i.channel} ${i.id}`.toLowerCase().includes(term));
    const list = $('workspace-job-list'); list.replaceChildren();
    for (const item of filtered) {
      const row = button('', () => openItem(item), 'job-row');
      row.setAttribute('aria-label',`${shortTitle(item.title || item.id)} · ${stateLabel(item.status)} · saved job ${item.id}`);row.title=item.title || item.id;
      const copy = node('span', undefined, 'job-copy'); copy.append(node('strong', shortTitle(item.title || item.id)), node('span', `${item.channel === 'desktop' ? 'Relay' : item.channel === 'shared' ? 'Shared' : item.channel} · ${['task','chat','request'].includes(item.kind) && !item.conversation_flow ? 'Conversation' : 'Workflow'}`, 'hint'));
      row.append(copy, node('span', item.archived?'Removed · '+stateLabel(item.status):stateLabel(item.status), 'job-state' + (['ready','awaiting_user','needs_input','blocked','uncertain','rejected'].includes(item.status) ? ' attention' : ''))); list.append(row);
    }
    if (!filtered.length) {
      const empty = node('div', undefined, 'empty-state'); empty.append(node('h2', term ? 'No matching jobs' : 'Start something new'), node('p', term ? 'Try another search or load more saved jobs.' : 'Describe a task, attach your files and review the proposed plan.'));
      list.append(empty);
    }
    const reviewItems = items.filter(i => !i.archived && ['ready','awaiting_user','needs_input','blocked','uncertain'].includes(i.status));
    const reviews = $('workspace-review-list'); reviews.replaceChildren();
    for (const [label,states] of [['Ready for review',['ready','awaiting_user']],['Needs attention',['needs_input','blocked','uncertain']]]) {
      const group=reviewItems.filter(i=>states.includes(i.status));if(!group.length)continue;reviews.append(node('h2',label));
      for(const item of group){const row=button(`${shortTitle(item.title || item.id)} · ${stateLabel(item.status)}`,()=>openItem(item),'row-link');row.setAttribute('aria-label',`${shortTitle(item.title || item.id)} · ${stateLabel(item.status)} · saved job ${item.id}`);reviews.append(row);}
    }
    if (!reviewItems.length) reviews.append(node('p', 'No plans or job decisions in the loaded history.', 'muted'));
    $('workspace-review-count').textContent = reviewItems.length; $('workspace-review-count').hidden = !reviewItems.length;
  }
  async function refreshJobs(more = false) {
    const ticket = ++jobsTicket;
    try {
      const result = await request('workspace-jobs', {offset:more ? next : 0,include_archived:$('workspace-show-removed').checked || false});
      if (ticket !== jobsTicket) return;
      items = more ? [...items, ...result.items] : result.items; next = result.next_offset; canPlan = result.can_plan;
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
    entryMode = value.entry_mode || (parent || previousRun ? 'plan' : 'conversation');
    $('workspace-create').textContent = entryMode === 'plan' ? 'Preview plan' : 'Send to orchestrator';
    $('workspace-compose-title').textContent = parent ? 'Revise plan' : previousRun ? 'Plan next step' : 'New task';
    $('workspace-compose-context').textContent = parent ? 'Your original request and plan remain saved.' : previousRun ? `Follow-up to ${previousRun}. Review and Start approve a new bounded stage.` : 'Ask a question or describe an outcome. Relay can answer, suggest useful options or prepare a plan.';
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
  async function openItem(item, automatic = false) {
    if (busy && automatic) return;
    selected = {kind:item.kind, id:item.id};
    const ticket = ++detailTicket;
    if (!automatic) { detailKey = null; navigate('detail'); $('workspace-detail-body').replaceChildren(node('p','Reading saved job…','muted')); feedback('workspace-detail-feedback',''); }
    try {
      if (item.kind === 'request') {
        const result = await request('workspace-request', {request_id:item.id});
        if (ticket !== detailTicket) return;
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
        const view = await request('workspace-detail', {run:item.id}); if (ticket === detailTicket) renderRun(view);
      }
    } catch (error) { if (ticket === detailTicket) feedback('workspace-detail-feedback', String(error), true); }
  }
  function changed(key) { if (key === detailKey) return false; disposeWorkflow(); disposeWorkflow = () => {}; detailKey = key; return true; }
  function heading(title, detail) { $('workspace-detail-title').textContent = title; $('workspace-detail-meta').textContent = detail; }
  function renderRequest(view) {
    if (!changed(JSON.stringify(view))) return;
    heading(view.entry_mode === 'conversation' ? 'Orchestrator request' : 'Planning request', stateLabel(view.status));
    $('workspace-detail-body').replaceChildren(node('p', view.result || (view.entry_mode === 'conversation' ? 'Waiting for the orchestrator…' : 'Waiting for the local planner. No execution has started.')), saved('Exact request', view.prompt));
  }
  function renderChat(view) {
    if (!changed(JSON.stringify(view))) return;
    heading(shortTitle(view.prompt), `${stateLabel(view.flow?.status || view.status)} · ${view.channel === 'desktop' ? 'Relay' : view.channel}`);
    const body=$('workspace-detail-body');body.replaceChildren();
    const stages=view.flow?.stages || [];
    if(stages.length){
      const tabs=node('nav',undefined,'conversation-tabs');tabs.setAttribute('aria-label','Job views');
      const results=node('section',undefined,'conversation-results'),workflow=node('section'),history=node('section');
      const panes={results,workflow,history},controls={};
      const switchView=key=>{conversationViews.set(view.id,key);Object.entries(panes).forEach(([name,pane])=>{pane.hidden=name!==key;controls[name].setAttribute('aria-pressed',String(name===key));});};
      for(const [key,label] of [['results','Results'],['workflow','Workflow'],['history','History']]){controls[key]=button(label,()=>switchView(key),'quiet');tabs.append(controls[key]);}
      body.append(tabs,results,workflow,history);
      const active=stages.filter(stage=>stage.mode!=='legacy_plan'),latest=active.at(-1) || stages.at(-1);
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
        else if(stage.execution)renderRun(stage.execution,stage.plan,content);
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
      const tasks=view.flow.tasks.filter(task=>!historicIds.has(task.stage_request_id));
      const visibleIds=new Set(tasks.map(task=>task.id));
      const projection={...view.flow,tasks:tasks.map(task=>({...task,dependencies:(task.dependencies || []).filter(dep=>visibleIds.has(typeof dep==='string'?dep:dep.task))}))};
      if(window.RelayWorkflow){
        disposeWorkflow=window.RelayWorkflow.mount(workflow,projection,{node,button,saved,stateLabel,outputFile:fileLink,
          selection:null,conversationView:true,select:()=>{},
          openConversation:task=>{show(task.stage_request_id || null);switchView('results');}});
      }else{
        workflow.append(node('h2','Workflow'));
        tasks.forEach(task=>workflow.append(button(task.objective+' · '+stateLabel(task.status),()=>{show(task.stage_request_id);switchView('results');})));
      }
      workflow.append(node('p',view.flow.note,'hint'));
      if(historicIds.size)workflow.append(button('View earlier preparation in History',()=>switchView('history'),'quiet'));
      show(conversationStages.has(view.id)?conversationStages.get(view.id):latest?.request_id);
      switchView(conversationViews.get(view.id) || 'results');
    }else renderConversationContent(body,view);
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
    if(view.can_continue)body.append(button('Continue this conversation',()=>newTask({constraints:'Original request:\n'+view.prompt,project:view.project,files:view.files || []})));
    else if(view.channel==='telegram')body.append(button('Continue in Telegram',()=>native.core.invoke('companion_open',{target:'conversation'})));
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
    if(!container){if (!changed(JSON.stringify(plan))) return;heading(shortTitle(plan.request), `${stateLabel(plan.status)} · Relay`);}
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
  function fileLink(file) {
    let errorNote;
    const link=button(file.path,async () => {
      if(link.disabled) return;
      link.disabled=true;
      if(errorNote)errorNote.remove();
      try { await native.core.invoke('workspace_reveal_artifact',{artifact:file.id}); }
      catch(error) { errorNote=node('p',String(error),'feedback error'); errorNote.setAttribute('role','alert'); link.insertAdjacentElement('afterend',errorNote); }
      finally { link.disabled=false; }
    },'quiet file-link');
    link.setAttribute('aria-label',`Show ${file.path} in Finder · saved version ${file.sha256 || file.id}`);
    link.title=`Show exact saved file in Finder${file.sha256 ? ' · SHA-256 '+file.sha256 : ''}`;
    return link;
  }
  function outputFile(file, texts, versions) {
    const row = node('div',undefined,'file-row'); row.append(fileLink(file));
    for(const change of versions?.changes || []) {
      const direct=change.old.id===file.id || change.new.id===file.id;
      const affected=(change.tasks || []).some(t=>t.task===file.task && t.attempt===file.attempt);
      if(direct || affected)row.append(versions.changeLink(change,direct ? change.kind==='external'?'Source changed':change.label : 'Earlier source version · '+change.old.path));
    }
    const text = texts?.find(t => t.path === file.path && t.attempt === file.attempt && t.task === file.task);
    if (text) row.append(saved(text.truncated ? 'Preview excerpt' : 'Preview',text.text));
    return row;
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
      status.append(button('Plan next step',()=>newTask({previous_run:view.name,project:plan?.project || '',research_mode:plan?.research_mode || 'suggest'}),'primary'));
    }
    if(view.control_error)status.append(node('p',view.control_error,'hint'));
    if(view.remove_blocker)status.append(node('p',view.remove_blocker,'hint'));
    for(const verb of (view.controls || []).filter(v=>['cancel','archive','restore'].includes(v))) {
      const b=button({cancel:view.controllable===false?'Cancel this stage':'Cancel job',archive:'Remove job…',restore:'Restore to Jobs'}[verb],()=>runAction(view,verb,controls),verb==='restore'?'primary':'danger');controls.push(b);status.append(b);
    }
    body.append(status);
    const versions=renderFileChanges(body,view,plan);
    const fileRow=(file,texts)=>outputFile(file,texts,versions);
    const results=section('Results');const reviewed=new Set();
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
    if(!container)disposeWorkflow=window.RelayWorkflow.mount(body,view,{node,button,saved,stateLabel,outputFile:fileRow,fileLink,...versions,
      selection:workflowSelections.get(view.name),select:id=>workflowSelections.set(view.name,id),
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
  }
  function renderTask(view) {
    if (document.activeElement?.id === 'workspace-task-instruction') return;
    if(!changed(JSON.stringify(view))) return;
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

  }
  document.querySelectorAll('[data-destination]').forEach(b=>b.onclick=()=>navigate(b.dataset.destination));
  $('workspace-new').onclick=()=>newTask();
  $('workspace-compose-back').onclick=()=>navigate('jobs');$('workspace-detail-back').onclick=()=>navigate('jobs');
  $('workspace-search').oninput=renderJobs;$('workspace-jobs-more').onclick=()=>refreshJobs(true);
  $('workspace-show-removed').onchange=()=>refreshJobs();
  $('workspace-create-form').onsubmit=submitPlan;
  $('workspace-attach').onclick=async()=>{try{const picked=await native.dialog.open({multiple:true,directory:false,title:'Choose task inputs'});if(picked){const paths=Array.isArray(picked)?picked:[picked];const combined=[...new Set([...attachments,...paths])];if(combined.length>10)return feedback('workspace-compose-feedback','Select at most ten files.',true);attachments=combined;renderAttachments();}}catch(error){feedback('workspace-compose-feedback',String(error),true);}};
  $('workspace-project-pick').onclick=async()=>{try{const picked=await native.dialog.open({multiple:false,directory:true,title:'Choose project folder'});if(typeof picked==='string')$('workspace-project').value=picked;}catch(error){feedback('workspace-compose-feedback',String(error),true);}};
  $('workspace-detail-refresh').onclick=()=>{if(selected && !busy)openItem(selected,true);};
  $('refresh').addEventListener('click',()=>{refreshJobs();if(destination==='detail' && selected && !busy)openItem(selected,true);});
  window.RelayWorkspace={navigate,newTask,refreshJobs};
  if(native){navigate('jobs',false);setInterval(()=>{if(document.hidden || busy)return;if(['jobs','reviews'].includes(destination))refreshJobs();if(destination==='detail' && selected)openItem(selected,true);},8000);}
})();
