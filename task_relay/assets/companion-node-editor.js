/* Author the existing workflow document. Validation and persistence use the shared node contract. */
(() => {
  const copy=v=>JSON.parse(JSON.stringify(v));
  function mount(container,o){
    const {node,button,request,saved,stateLabel}=o;
    let display=o.record?.display,runTimer=null,tracking=false,renderPending=false,disposeInspector=()=>{};
    const canvasIdentity=o.record?.canvas || 'editor:'+(o.record?.id || crypto.randomUUID());
    const inspectorTabs=new Map();
    let record=o.record,document=copy(record?.workflow || {schema_version:1,kind:'workflow',inputs:{},tasks:[]});
    let rows=[],selected=o.selection || (record?.origin?document.tasks[0]?.id:null),dispose=()=>{},closed=false,dirty=false,pending=false;
    const toolbar=node('div',undefined,'canvas-toolbar'),project=node('div',undefined,'canvas-project-island job-titlebar'),actions=node('div',undefined,'canvas-action-island');
    const title=node('input');title.value=record?.title || 'Untitled job';title.maxLength=180;title.setAttribute('aria-label','Job title');title.oninput=()=>{dirty=true;};
    // Editor-only history: never rewinds executed attempts, artifacts or authority.
    const undoStack=[],redoStack=[];
    let committedTitle=title.value;
    const snapshot=()=>({workflow:copy(document),title:committedTitle,selection:selected});
    const sameGraph=(a,b)=>JSON.stringify(a.workflow)===JSON.stringify(b.workflow) && a.title===b.title;
    function retain(stack,value){stack.push(value);while(stack.length>50 || (stack.length>1 && JSON.stringify(stack).length>8_000_000))stack.shift();}
    function historyState(){undo.disabled=pending || !undoStack.length;redo.disabled=pending || !redoStack.length;}
    function rememberEdit(before){if(sameGraph(before,snapshot()))return;retain(undoStack,before);redoStack.length=0;historyState();}
    function changed(){dirty=!record || title.value.trim()!==record.title || JSON.stringify(document)!==JSON.stringify(record.workflow);status.textContent=dirty?'Unsaved':record.canvas?'Saved':'Saved draft';notice.textContent='';}
    title.onchange=()=>{const before=snapshot();committedTitle=title.value;rememberEdit(before);changed();};
    const status=node('span',record?.canvas?'Saved workflow':'Draft','job-status-label'),notice=node('p','Add nodes, configure them in the inspector, then Run.','editor-notice');notice.setAttribute('role','status');
    const canvas=node('div',undefined,'canvas-host inspector-hidden'),library=node('aside',undefined,'node-library');library.hidden=true;library.setAttribute('aria-label','Node library');
    async function saveDraft(){
      if(pending)return false;title.value=window.RelayWorkflow.jobTitle(title.value,'',document);if(committedTitle!==title.value)title.onchange();pending=true;save.disabled=true;historyState();
      try{record=record?.canvas?await request('node-canvas-save',{run:record.canvas,revision:record.revision,title:title.value.trim(),workflow:document}):await request('node-draft-save',{id:record?.id || null,revision:record?.revision || null,title:title.value.trim(),workflow:document});if(closed)return;dirty=false;status.textContent=record.canvas?'Saved':'Saved draft';notice.textContent=!document.tasks.length?'Saved empty workflow. Add a step when you’re ready.':record.missing_inputs.length?'Saved. Some inputs still need values.':'Saved. Run uses this exact graph.';saveChatScope();o.onSaved?.(record);return true;}
      catch(e){notice.textContent=String(e);return false;}finally{pending=false;save.disabled=false;historyState();}
    }
    const save=button('Save',saveDraft,'primary');
    async function restoreEdit(from,to){
      if(pending || !from.length || closed)return;
      pending=true;save.disabled=true;historyState();
      const target=from.at(-1),before=snapshot();
      try{
        if(target.workflow.tasks.length)await request('node-validate',{workflow:target.workflow,...(record?.canvas?{canvas:record.canvas}:{})});
        if(closed)return;
        from.pop();retain(to,before);document=copy(target.workflow);title.value=committedTitle=target.title;
        selected=target.selection;changed();render();
      }catch(e){notice.textContent=String(e);}finally{pending=false;save.disabled=false;historyState();}
    }
    const undo=button('Undo',()=>restoreEdit(undoStack,redoStack),'quiet');undo.title='Undo (⌘Z / Ctrl+Z)';
    const redo=button('Redo',()=>restoreEdit(redoStack,undoStack),'quiet');redo.title='Redo (⇧⌘Z / Ctrl+Shift+Z)';historyState();
    const historyKeydown=event=>{
      const target=event.target,tag=target?.tagName?.toLowerCase();
      // Native text undo owns the focused field, including the chat composer.
      if(['input','textarea','select'].includes(tag) || target?.isContentEditable || target?.closest?.('[contenteditable="true"]'))return;
      if(event.defaultPrevented || event.altKey || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase()!=='z')return;
      event.preventDefault();event.stopPropagation();
      if(event.shiftKey)restoreEdit(redoStack,undoStack);else restoreEdit(undoStack,redoStack);
    };
    // Deleting a focused node/control can move focus to body; keep the shortcut
    // bound to this mounted editor rather than only its remaining descendants.
    window.addEventListener('keydown',historyKeydown);
    const nativeHistory=action=>action==='undo'?restoreEdit(undoStack,redoStack):action==='redo'?restoreEdit(redoStack,undoStack):undefined;
    window.RelayNodeEditor.history=nativeHistory;
    const exportButton=button('Export',async()=>{if((!record || dirty) && !await saveDraft())return;await o.exportWorkflow?.(record);},'quiet');
    project.append(button('Jobs',()=>o.jobs?o.jobs(container,async()=>!dirty || await saveDraft()):o.leave(),'quiet'),title,status,window.RelayWorkflow.connectionIndicators({node,button,open:async()=>{if(!dirty || await saveDraft())o.connections?.();}}));
    if(record?.origin){
      project.append(button('Original result',()=>o.onRun(record.origin.source_run),'quiet'));
      notice.textContent='New draft from the exact saved node version. The original run stays unchanged; Run reviews execution separately.';
    }
    const runButton=button('Run',()=>showRun('all'),'primary');
    actions.append(button('+ Step',()=>openLibrary(),'quiet'),undo,redo,save,...(o.exportWorkflow?[exportButton]:[]),runButton);toolbar.append(project,actions);container.replaceChildren(toolbar,canvas,library,notice);
    const chat=node('aside',undefined,'job-chat-panel');chat.setAttribute('aria-label','Workflow chat');chat.hidden=!!document.tasks.length;
    const chatToggle=button('Chat',()=>{chat.hidden=!chat.hidden;chatToggle.setAttribute('aria-pressed',String(!chat.hidden));},'quiet');chatToggle.setAttribute('aria-pressed',String(!chat.hidden));actions.insertBefore(chatToggle,save);container.append(chat);
    const chatHeader=node('div',undefined,'section-title'),question=node('textarea'),chatNote=node('p','','hint'),proposal=node('div');
    question.rows=2;question.placeholder='Ask a question or describe a workflow…';question.maxLength=10000;question.setAttribute('aria-label','Describe your workflow');
    const unsavedChatKey='relay:workflow-composition:current-unsaved';
    let chatKey;
    if(record?.canvas || record?.id)chatKey='relay:workflow-composition:'+(record.canvas || record.id);
    else {
      chatKey=o.newJob?null:localStorage.getItem(unsavedChatKey);
      // Restore a legacy unsaved conversation only on reopening, never on New job.
      if(!chatKey && !o.newJob && !localStorage.getItem(unsavedChatKey+':migrated') && (localStorage.getItem('relay:workflow-composition') || localStorage.getItem('relay:workflow-composition:history')))chatKey='relay:workflow-composition';
      if(!chatKey)chatKey='relay:workflow-composition:unsaved:'+crypto.randomUUID();
      localStorage.setItem(unsavedChatKey,chatKey);
      localStorage.setItem(unsavedChatKey+':migrated','1');
    }
    let historyKey=chatKey+':history';
    const send=button('Send',()=>compose(),'primary');
    let composition=null,chatBusy=false,chatTimer=null,chatChoice=null,chatOverride=false,chatHistory=[];
    const chatSettings=node('details',undefined,'workflow-chat-settings'),modelSummary=node('summary','Choose a model'),settingsBody=node('div');chatSettings.append(modelSummary,settingsBody);
    const transcript=node('div',undefined,'job-chat-messages workflow-chat-transcript');transcript.setAttribute('aria-label','Conversation');transcript.setAttribute('aria-live','polite');
    const modelRow=node('div',undefined,'workflow-chat-model-row');
    const sharedSettings=button('',()=>o.modelSettings?.(),'quiet');sharedSettings.title='Conversation model settings · shared with Telegram and Messages';sharedSettings.setAttribute('aria-label',sharedSettings.title);sharedSettings.append(window.RelayWorkflow.icon('operation'));
    modelRow.append(sharedSettings,chatSettings);
    const composer=node('div',undefined,'workflow-chat-composer');composer.append(modelRow,question,send);
    chatHeader.append(node('h3','Chat'));window.RelayWorkflow.panelWidth(chat,chatHeader,canvasIdentity+':chat','Chat',{button});chatHeader.append(button('×',()=>{chat.hidden=true;chatToggle.setAttribute('aria-pressed','false');},'quiet'));
    chat.append(chatHeader,transcript,composer);
    function chatLabel(){const m=composition?.model || chatChoice;return m?`${m.provider==='codex'?'Codex':m.provider} · ${m.id}${composition?'':chatOverride?' · This chat':' · Shared'}`:'Set conversation model in Settings';}
    function chatState(){
      question.disabled=!!composition;send.textContent='Send';send.disabled=chatBusy || !!composition || !chatChoice?.id;
      for(const c of settingsBody.querySelectorAll('select,input'))c.disabled=!!composition;
      modelSummary.textContent=chatLabel();
    }
    function bubble(role,text){const box=node('div',undefined,'job-chat-message '+role);box.append(node('strong',role==='user'?'You':'Relay'),node('p',text));return box;}
    function drawConversation(){
      transcript.replaceChildren();
      if(!chatHistory.length && !composition)transcript.append(node('p','What would you like to do?','hint'));
      for(const turn of chatHistory){
        transcript.append(bubble('user',turn.question));const answer=bubble('assistant',turn.message);
        if(turn.workflow){
          answer.append(node('p',turn.workflow.tasks.map(t=>t.objective+' · '+t.operation).join('\n'),'hint'));
          if(turn.applied)answer.append(node('p','Added to canvas','hint'));
          else answer.append(button('Apply to canvas',async()=>{
            if(turn.applied)return;
            if(JSON.stringify(document)!==JSON.stringify(turn.base)){chatNote.textContent='The canvas changed. Ask for an updated proposal using your current graph.';answer.append(node('p',chatNote.textContent,'hint'));return;}
            const proposed=copy(turn.workflow);await edit(w=>{for(const key of Object.keys(w))delete w[key];Object.assign(w,proposed);});
            if(JSON.stringify(document)===JSON.stringify(proposed)){turn.applied=true;saveHistory();drawConversation();}
          },'primary'));
        }
        transcript.append(answer);
      }
      if(composition){transcript.append(bubble('user',composition.question));const answer=bubble('assistant','');answer.append(chatNote,proposal);transcript.append(answer);}
      transcript.lastElementChild?.scrollIntoView?.({block:'nearest'});
    }
    function saveChatScope(){
      const next='relay:workflow-composition:'+ (record.canvas || record.id);if(next===chatKey)return;
      if(composition)localStorage.setItem(next,JSON.stringify(composition));
      const override=localStorage.getItem(chatKey+':model');if(override)localStorage.setItem(next+':model',override);localStorage.removeItem(chatKey+':model');
      localStorage.setItem(next+':history',JSON.stringify(chatHistory));
      if(localStorage.getItem(unsavedChatKey)===chatKey)localStorage.removeItem(unsavedChatKey);
      localStorage.removeItem(chatKey);localStorage.removeItem(historyKey);chatKey=next;historyKey=next+':history';
    }
    function saveHistory(){localStorage.setItem(historyKey,JSON.stringify(chatHistory));}
    function previewKey(){return 'relay:workflow-preview:'+composition.request_id;}
    function previewState(){try{return JSON.parse(localStorage.getItem(previewKey()) || 'null');}catch{return null;}}
    async function applyReplyGraph(result){
      if(!result.workflow || result.error)return false;
      const prior=previewState(),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      // The submitted request stays immutable. Preview revisions live separately.
      if(!same(document,prior?.workflow || composition.workflow))return false;
      const proposed=copy(result.workflow);
      if(!same(document,proposed))await edit(w=>{for(const key of Object.keys(w))delete w[key];Object.assign(w,proposed);});
      if(!same(document,proposed))return false;
      localStorage.setItem(previewKey(),JSON.stringify({workflow:proposed,preview:result.preview || null}));return true;
    }
    async function finishReply(result){
      const hadPreview=!!previewState();
      const message=result.error?('I couldn’t finish the workflow. '+result.error+(hadPreview?' The last saved preview remains on the canvas.':' The previous canvas is unchanged.')+' You can send a follow-up message.'):
        result.message || (result.workflow?'Your workflow is ready.':hadPreview?'This request stopped. The last saved preview remains on the canvas.':'This request stopped before a reply was saved. Your canvas is unchanged.');
      let turn=chatHistory.find(t=>t.id===composition.request_id);
      if(!turn){turn={id:composition.request_id,question:composition.question,message,model:composition.model || chatChoice,base:composition.workflow,...(result.workflow?{workflow:result.workflow}:{})};chatHistory.push(turn);}
      if(result.workflow && !result.error){
        turn.applied=await applyReplyGraph(result);
        if(!turn.applied)turn.message+=' The canvas changed while I was working, so I kept your edits. Ask me to update the current graph.';
      }
      localStorage.removeItem(previewKey());
      saveHistory();localStorage.removeItem(chatKey);composition=null;question.value='';proposal.replaceChildren();receiveChatDefaults(setup);chatState();drawConversation();
    }
    async function inspectComposition(){
      const result=await request('node-compose-result',{request_id:composition.request_id});if(closed)return;
      if(['completed','blocked','cancelled'].includes(result.status)){await finishReply(result);return;}
      const building=['active','settling'].includes(result.status);
      const applied=result.preview && await applyReplyGraph(result);
      chatNote.textContent=building?(result.preview?(applied?`Building workflow… ${result.workflow?.tasks.length || 0} nodes on the canvas. ${result.message || ''}`:'Still working. Your canvas edits are preserved; further updates will not overwrite them.'):'Thinking and building your workflow…'):(result.error || stateLabel(result.status));
      proposal.replaceChildren();
      if(['active','settling'].includes(result.status)){
        await request('node-run-advance',{run:result.run});
        if(!closed)chatTimer=setTimeout(()=>checkComposition(),2000);
      }else if(result.status==='not_submitted'){chatNote.textContent='This message has not been sent.';proposal.append(button('Send message',()=>resumeComposition(),'primary'));}
      else proposal.append(button('Check status',()=>checkComposition(),'quiet'));
    }
    async function checkComposition(){
      if(chatBusy || !composition || closed)return;chatBusy=true;chatState();
      try{await inspectComposition();}catch(e){chatNote.textContent='Connection interrupted. Your saved request is preserved. '+String(e);proposal.replaceChildren(button('Retry status',()=>checkComposition(),'quiet'));}
      finally{chatBusy=false;chatState();}
    }
    async function submitComposition(){
      if(composition.submission){await request('node-run-start',composition.submission);await inspectComposition();return;}
      if(!composition.model){await inspectComposition();return;} // Historical requests are observed, never relaunched.
      proposal.replaceChildren();const checked=await request('node-compose-preview',composition);if(closed)return;
      if(checked.blockers.length){await finishReply({error:checked.blockers.map(b=>b.message).join('\n')});return;}
      const paid=checked.paid_nodes.length>0,exact=composition;
      async function submit(){
        if(composition!==exact || closed)return;
        if(!exact.submission){exact.submission={...checked.command,fingerprint:checked.fingerprint,allow_paid:paid};localStorage.setItem(chatKey,JSON.stringify(exact));}
        chatNote.textContent='Thinking and building your workflow…';proposal.replaceChildren();
        await request('node-run-start',exact.submission);await inspectComposition();
      }
      if(paid){
        chatNote.textContent=chatLabel()+': send your message, conversation and current graph to this provider? Paid API use; price unavailable. Only the reply/proposal runs.';
        proposal.replaceChildren(button('Send · paid',async()=>{if(chatBusy)return;chatBusy=true;chatState();try{await submit();}catch(e){showChatError(e);}finally{chatBusy=false;chatState();}},'primary'),button('Cancel',()=>{if(chatBusy)return;finishReply({message:'Not sent. No paid request was started.'});},'quiet'));
      }else await submit();
    }
    function showChatError(e){
      chatNote.textContent='I couldn’t complete this request. '+String(e);
      proposal.replaceChildren(button(composition?.submission?'Retry status':'Retry',()=>resumeComposition(),'quiet'));
      if(!composition?.submission)proposal.append(button('Edit message',()=>{const old=composition;localStorage.removeItem(chatKey);composition=null;question.value=old.question;chatState();drawConversation();},'quiet'));
    }
    async function resumeComposition(){if(chatBusy || !composition || closed)return;chatBusy=true;chatState();try{await submitComposition();}catch(e){showChatError(e);}finally{chatBusy=false;chatState();}}
    async function compose(){
      if(chatBusy || pending || composition || !question.value.trim())return;
      if(!chatOverride){
        chatBusy=true;chatState();
        try{await loadSetup();receiveChatDefaults(setup);}catch(e){chatChoice=null;chatNote.textContent=String(e);}
        finally{chatBusy=false;chatState();}
        if(closed || composition || !chatChoice?.id)return;
      }
      if(!chatChoice?.id)return;
      title.value=window.RelayWorkflow.jobTitle(title.value,question.value.trim(),document);if(committedTitle!==title.value)title.onchange();
      const messages=chatHistory.slice(-20).flatMap(t=>[{role:'user',text:t.question},{role:'assistant',text:t.message}]);
      const next={request_id:crypto.randomUUID(),question:question.value.trim(),workflow:copy(document),title:title.value.trim(),model:copy(chatChoice),messages};
      try{localStorage.setItem(chatKey,JSON.stringify(next));composition=next;question.value='';chatSettings.open=false;chatNote.textContent='Preparing your request…';drawConversation();chatState();await resumeComposition();}
      catch(e){chatNote.textContent=String(e);}
    }
    question.onkeydown=e=>{if(e.key==='Enter' && !e.shiftKey){e.preventDefault();compose();}};
    try{chatHistory=JSON.parse(localStorage.getItem(historyKey) || '[]');composition=JSON.parse(localStorage.getItem(chatKey) || 'null');const override=JSON.parse(localStorage.getItem(chatKey+':model') || 'null');if(override?.provider && typeof override.id==='string'){chatChoice=override;chatOverride=true;}}
    catch(e){chatNote.textContent='Could not restore saved chat: '+e;}
    if(composition){const savedPreview=previewState();if(savedPreview && JSON.stringify(document)===JSON.stringify(composition.workflow)){document=copy(savedPreview.workflow);dirty=true;}}
    drawConversation();
    let setup=null;const modelDrafts=new Map();let localFiles=[];
    async function loadSetup(){setup=await request('node-setup',{});return setup;}
    function receiveChatDefaults(settings){
      if(closed || composition || chatOverride)return;
      const text=settings?.capabilities?.find(r=>r.capability==='text'),selected=text?.selected;
      chatChoice=text?.selected_available && selected?.provider && selected?.model?{provider:selected.provider,id:selected.model}:null;
      chatState();
    }
    window.RelayNodeEditor.updateChatDefaults=receiveChatDefaults;
    async function drawChatSetup(){
      try{
        if(!setup)await loadSetup();if(closed)return;
        receiveChatDefaults(setup);
        const existing=composition?composition.model:chatChoice;
        chatChoice=existing;settingsBody.replaceChildren();
        const provider=select([['','Choose a provider'],...setup.text.map(p=>[p.provider,p.provider==='codex'?'Codex · ChatGPT login':p.provider])],existing?.provider || '',p=>{chatOverride=true;chatChoice=p?{provider:p,id:''}:null;localStorage.setItem(chatKey+':model',JSON.stringify(chatChoice));drawChatSetup();});
        settingsBody.append(node('p','Shared with Telegram and Messages. Choose a different model for this chat only.','hint'),field('Chat provider',provider));
        settingsBody.append(button('Use shared model',async()=>{chatOverride=false;localStorage.removeItem(chatKey+':model');await loadSetup();await drawChatSetup();chatSettings.open=false;},'quiet'));
        if(existing?.provider){
          const p=setup.text.find(p=>p.provider===existing.provider),names=[...new Set([...(p?.models || []),...(existing.id?[existing.id]:[])])];
          const custom=node('details');custom.append(node('summary','Custom model'));
          const id=node('input');id.value=existing.id;id.spellcheck=false;id.autocomplete='off';id.setAttribute('autocorrect','off');id.setAttribute('autocapitalize','none');
          const choose=m=>{chatOverride=true;chatChoice={provider:existing.provider,id:m,...(existing.provider==='codex'?{reasoning:'high'}:{})};localStorage.setItem(chatKey+':model',JSON.stringify(chatChoice));chatState();};
          const models=select([['','Choose a model'],...names.map(m=>[m,m]),['__custom','Custom model…']],existing.id,m=>{if(m==='__custom'){custom.open=true;id.focus();}else {id.value=m;choose(m);}});
          id.onchange=()=>choose(id.value.trim());settingsBody.append(field('Chat model',models));custom.append(field('Chat model ID',id));settingsBody.append(custom);
          settingsBody.append(node('p',existing.provider==='codex'?'Uses your existing ChatGPT Codex login.':p?.connected?'Uses your saved connection. Paid sends require confirmation.':'No saved connection. Configure this provider in a model node before sending.','hint'));
        }
        chatState();
      }catch(e){chatNote.textContent=String(e);send.disabled=true;}
    }
    chatSettings.ontoggle=()=>{if(chatSettings.open && !composition)loadSetup().then(drawChatSetup).catch(e=>{chatNote.textContent=String(e);});};
    drawChatSetup().then(()=>{if(composition){chatNote.textContent='Restoring your saved request…';checkComposition();}});
    function setupInspector(task,panel){
      const section=node('section',undefined,'node-setup');panel.append(section);
      async function draw(){
        try{if(!setup)await loadSetup();if(closed || !section.isConnected)return;
          section.replaceChildren();
          const spec=setup.operations[task.operation] || {},worker=spec.worker;
          if(spec.connection==='managed_browser'){
            const render=task.operation==='xfigura.render',b=setup.browser || {},connection=node('section',undefined,'node-connection');
            section.append(connection);connection.append(node('h4',render?'xFigura · browser account':'Perplexity · browser account'));
            connection.append(node('p',b.error || (!b.available?'Google Chrome is required.':!b.enabled?'Enable browser use to connect your account.':b.manual_sign_in?'Finish signing in in Chrome.':'Saved browser profile enabled. Sign-in is checked when this node runs.'),'hint'));
            connection.append(node('p',render?'Select an empty render node in xFigura and paste its URL below. Generation may spend credits; Run asks for confirmation. Setup does not generate.':'Uses ordinary Perplexity Search, not Research mode or an API key. Account allowances apply. No search is submitted during setup.','hint'));
            if(!render)connection.append(node('p','Completed answers are kept even if source-link collection fails. The answer and Sources output disclose missing links.','hint'));
            async function changeBrowser(action,value){try{const result=await request(action,value);notice.textContent=result.message;await loadSetup();if(!closed && section.isConnected)await draw();}catch(e){notice.textContent=String(e);}}
            if(b.available){
              if(!b.enabled)connection.append(button('Enable browser & sign in',()=>changeBrowser('browser-configure',{enabled:true}),'quiet'));
              else if(b.manual_sign_in)connection.append(node('p',render?'In Chrome, open https://app.xfigura.ai and sign in.':'In Chrome, open https://www.perplexity.ai, sign in and select ordinary Search.','hint'),button('Done signing in',()=>changeBrowser('browser-sign-in-done',{}),'quiet'));
              else connection.append(button('Open browser / sign in',()=>changeBrowser('browser-open',{}),'quiet'));
            }
            connection.append(button('Refresh setup',async()=>{await loadSetup();if(!closed && section.isConnected)await draw();},'quiet'));return;
          }
          let provider=worker?(modelDrafts.get(task.id)?.provider ?? task.model?.provider):spec.provider;
          let model=worker?(modelDrafts.get(task.id)?.model ?? task.model?.id):(task.inputs.model?.value || definition(task)?.inputs.model?.default || '');
          if(worker){
            section.append(field('Provider',select([['','Choose a provider'],...setup.text.map(p=>[p.provider,p.provider==='codex'?'Codex · ChatGPT login':p.provider])],provider || '',p=>{
              modelDrafts.set(task.id,{provider:p,model:''});edit(w=>{delete w.tasks.find(t=>t.id===task.id).model;});
            })));
          }
          const controls=node('div');section.append(controls);
          function build(){
            controls.replaceChildren();if(!provider){controls.append(node('p',worker?'Choose a provider for this node.':'This node uses local tools or public reads. Run checks availability.','hint'));return;}
            const capability=worker?'text':task.operation.endsWith('.image')?'image':task.operation.endsWith('.video')?'video':task.operation.endsWith('.mesh')?'mesh':'text';
            const options=[...new Set([...(worker?setup.text.filter(p=>p.provider===provider).flatMap(p=>p.models || []):[]),...setup.capabilities.filter(c=>c.capability===capability).flatMap(c=>c.options.filter(p=>p.provider===provider).flatMap(p=>p.models || []))])];
            if(worker || Object.hasOwn(inputs(task),'model')){
              const custom=node('details');custom.append(node('summary','Custom model & settings'));
              const choices=[...new Set([...options,...(model?[model]:[])])];
              const suggested=select([['','Choose a model'],...choices.map(m=>[m,m]),['__custom','Custom model…']],model,m=>{if(m==='__custom'){custom.open=true;id.focus();}else if(m){id.value=m;commit();}});
              const id=node('input');id.value=model;id.placeholder='Exact model ID';id.spellcheck=false;id.setAttribute('autocorrect','off');id.setAttribute('autocapitalize','none');id.autocomplete='off';
              const reasoning=select(['low','medium','high','xhigh','max','ultra'].map(v=>[v,v]),task.model?.reasoning || 'high',()=>commit());
              const tools=select([['files','Files & images'],['python','Local Python · isolated']],task.model?.tools || 'files',()=>commit());
              function commit(){model=id.value.trim();if(worker)modelDrafts.set(task.id,{provider,model});edit(w=>{const t=w.tasks.find(t=>t.id===task.id);if(!model){if(worker)delete t.model;else delete t.inputs.model;return;}if(worker)t.model={provider,id:model,...(provider==='codex'?{reasoning:reasoning.value}:{}),...(tools.value==='python'?{tools:'python'}:{})};else t.inputs.model={value:model};});}
              id.onchange=commit;controls.append(field('Model',suggested));custom.append(field('Model ID',id));if(worker && provider==='codex')custom.append(field('Reasoning',reasoning));controls.append(custom);
              if(worker)custom.append(field('Tools',tools),node('p','Local Python can create files such as audio and spreadsheets. It runs on assigned files with network and subprocess access denied. Code and document tools must be verified in Settings.','hint'));
            }
            const connection=node('details');connection.append(node('summary',provider==='codex'?'Connection · ChatGPT login':'Connection'));controls.append(connection);
            if(provider==='codex')connection.append(node('p','Uses your existing ChatGPT Codex login.','hint'),button('Select qualified Codex runtime',async()=>{
              try{const picked=await o.pickFiles?.();if(!picked)return;const paths=Array.isArray(picked)?picked:[picked];if(paths.length!==1)throw Error('Choose one qualified.json receipt.');const r=await request('node-codex-runtime',{path:paths[0]});notice.textContent=r.message;}catch(e){notice.textContent=String(e);}
            },'quiet'));
            else {
              const status=setup.capabilities.flatMap(c=>c.options).find(p=>p.provider===provider);
              connection.querySelector('summary').textContent=status?.connected?'Connection · connected':'Connection · setup needed';
              connection.open=!status?.connected;
              connection.append(node('p',status?.connected?'Saved credential is ready to use. You do not need to enter it again.':'Add this provider’s key once. All nodes using this provider share it.','hint'));
              const key=node('input');key.type='password';key.autocomplete='new-password';key.placeholder=provider==='higgsfield'?'ID:SECRET':'API key';
              const form=node('div');
              const save=button('Save connection',async()=>{
                if(!key.value.trim()){notice.textContent='Enter a new API key to save. Existing credentials are unchanged.';return;}
                const secret=key.value;key.value='';try{const result=await request('node-connect',{provider,key:secret,model:model || task.inputs.model?.value || definition(task)?.inputs.model?.default || ''});notice.textContent=result.message;await loadSetup();draw();}catch(e){notice.textContent=String(e);}
              },'quiet');
              save.disabled=true;key.oninput=()=>{save.disabled=!key.value.trim();};
              form.append(field('API key',key),save);
              if(status?.connected){
                form.hidden=true;connection.append(button('Replace saved API key',()=>{form.hidden=!form.hidden;if(!form.hidden)key.focus();},'quiet'));
              }
              connection.append(form,node('p','Keys are stored locally in '+setup.credential_file+' and never enter the workflow.','hint'));
            }
            if(worker)connection.append(button('Check connection',async()=>{try{notice.textContent='Checking connection…';const r=await request('node-model-verify',{provider,model});notice.textContent=r.message;}catch(e){notice.textContent=String(e);}},'quiet'));
          }
          build();
        }catch(e){section.replaceChildren(node('p',String(e),'feedback error'));}
      }
      draw();
    }
    async function showRun(scope='all',inline=null,reset=null){
      if(pending){reset?.();return;}if(!record || dirty){if(!await saveDraft()){reset?.();return;}}
      const host=inline || library;
      let cancelled=false,generation=0,submitting=false;
      const close=()=>{if(submitting)return;cancelled=true;generation++;if(inline)reset?.();else library.hidden=true;};
      if(!inline)library.hidden=false;
      host.replaceChildren(...(inline?[]:[node('h3',scope==='all'?'Run workflow':'Run this node')]));
      const fields={},values=copy(record?.values || {});
      const form=node('div'),result=node('div');
      const continueButton=button('Continue',()=>validate(),'primary');continueButton.hidden=true;
      function changed(){generation++;result.replaceChildren();continueButton.hidden=false;}
      for(const [name,p] of Object.entries(document.inputs)){
        if(Object.hasOwn(p,'default') && !Object.hasOwn(values,name))values[name]=copy(p.default);
        if(p.type==='artifact'){
          const label=node('span',values[name]?'Saved file selected':'No file chosen');form.append(node('h4',p.label || name),label,button('Choose run file',async()=>{
            try{const picked=await o.pickFiles?.();if(!picked)return;const paths=Array.isArray(picked)?picked:[picked];if(paths.length!==1)throw Error('Choose one file.');const result=await request('node-file-import',{paths});values[name]={artifact:result.files[0].artifact};label.textContent=result.files[0].name;changed();}catch(e){notice.textContent=String(e);}
          },'quiet'));
        }else{const input=literalControl(p,values[name],v=>{values[name]=v;changed();},p.label || name);fields[name]=input;form.append(field(p.label || name,input));}
      }
      host.append(form,result,continueButton,button('Cancel',close,'quiet'));
      async function validate(){
        if(cancelled || submitting)return;const ticket=++generation;
        continueButton.hidden=true;result.replaceChildren(node('p','Checking…','hint'));
        try{
          const command=record.canvas?{canvas:record.canvas,revision:record.revision,scope,values:copy(values),request_id:crypto.randomUUID()}:{id:record.id,revision:record.revision,scope,values:copy(values),request_id:crypto.randomUUID()};
          const checked=await request('node-run-preview',command);
          if(cancelled || closed || !host.isConnected || ticket!==generation)return;
          result.replaceChildren();
          if(checked.blockers.length){for(const b of checked.blockers)result.append(node('p',b.node+': '+b.message,'feedback error'));return;}
          const paid=checked.paid_nodes.length>0;
          const hostApprovals=window.RelayWorkflow.hostCodeReview(result,checked,node);
          const uncertain=checked.uncertain_attempts || [];
          if(uncertain.length)result.append(node('p','The previous request may have completed or incurred a charge. Confirm a separate new attempt with the current prompt. The uncertain attempt stays in history.','feedback warning'));
          if(paid)result.append(node('p',scope==='all'?`${checked.plan.tasks.length} nodes will run. Paid API or account-credit use; price unavailable.`:'Only this node will run. Paid API or account-credit use; price unavailable.','hint'));
          let submission=null;
          const start=button(uncertain.length?(paid?'Confirm new paid attempt':'Confirm new attempt'):hostApprovals.length?(paid?'Approve script & run · paid':'Approve script & run'):paid?'Run · paid':'Run',async()=>{
            if(start.disabled || cancelled || closed || !host.isConnected)return;
            if(!submission && (dirty || record.revision!==command.revision || ticket!==generation)){result.replaceChildren(node('p','Inputs changed. Run again to check the current node.','hint'));return;}
            start.disabled=true;submitting=true;
            // Retrying an uncertain bridge response uses the exact same command identity.
            if(!submission)submission={...command,fingerprint:checked.fingerprint,allow_paid:paid,...(hostApprovals.length?{approve_host_code:hostApprovals}:{}),...(uncertain.length?{acknowledge_uncertain:uncertain}:{})};
            form.hidden=true;
            try{start.textContent='Starting…';const receipt=await request('node-run-start',submission);if(!closed){if(o.trackRun){library.hidden=true;await trackExecution(receipt.canvas_run || receipt.run);}else await o.onRun?.(receipt.canvas_run || receipt.run,scope);}}
            catch(e){result.append(node('p',String(e)+' Retrying checks the same submission.','feedback error'));start.textContent='Check same submission';}
            finally{start.disabled=false;submitting=false;}
          },'primary');result.append(start);
          if(!paid && !uncertain.length && !hostApprovals.length)await start.onclick();
        }catch(e){if(!cancelled && ticket===generation)result.replaceChildren(node('p',String(e),'feedback error'));}
      }
      await validate();
    }

    function definition(task){return rows.find(r=>r.id===task.operation);}
    function outputs(task){return task.operation==='model'?Object.fromEntries(task.outputs.map(p=>[p.name,{...p,label:p.purpose}])):(definition(task)?.outputs || {});}
    function inputs(task){return task.operation==='model'?Object.fromEntries(Object.entries(task.input_definitions).map(([k,v])=>[k,{...v,kind:v.type==='artifact'?'artifact':'value',schema:v}])):(definition(task)?.inputs || {});}
    function rawRefs(binding){if(binding?.task || binding?.artifact)return [binding];if(Array.isArray(binding?.value))return binding.value.filter(v=>v?.task || v?.artifact);if(binding?.value?.artifact)return [binding.value];return [];}
    function sources(){return (record?.completed_sources || []).filter(s=>document.tasks.some(t=>Object.values(t.inputs).flatMap(rawRefs).some(r=>r.artifact===s.file.id)));}
    function refs(binding){return rawRefs(binding).flatMap(r=>{
      if(r.task)return [r];const s=sources().find(s=>s.file.id===r.artifact);
      return s?[{task:s.node.id,output:s.file.path}]:[];
    });}
    function projection(){
      const tasks=document.tasks.map(task=>{
        const old=display?.tasks?.find(t=>t.id===task.id);
        return {...old,id:task.id,operation:task.operation,objective:task.objective,status:old?.status || 'draft',
          prompt:typeof task.inputs.prompt?.value==='string'?task.inputs.prompt.value:undefined,
          backend:task.model?{type:task.model.provider+'-agent',model:task.model.id}:typeof task.inputs.model?.value==='string'?{model:task.inputs.model.value}:undefined,
          planned_inputs:Object.entries(inputs(task)).filter(([name,p])=>p.kind==='artifact'||p.kind==='artifacts'||refs(task.inputs[name]).length).flatMap(([name,p])=>{
            const links=refs(task.inputs[name]);return links.length?links.map(r=>({path:name,purpose:p.label,from_task:r.task,output:r.output})):[{path:name,purpose:p.label}];}),
          planned_outputs:Object.entries(outputs(task)).map(([name,p])=>({path:name,output_port:name,purpose:p.label})),
          dependencies:[...new Set(Object.values(task.inputs).flatMap(refs).map(r=>r.task))].map(task=>({task}))};
      });
      return {...display,name:canvasIdentity+':'+JSON.stringify(document.tasks.map(t=>[t.id,Object.values(t.inputs).flatMap(refs)])),
        tasks:[...sources().map(s=>s.node),...tasks],executing_runs:display?.executing_runs || [],latest_outputs:display?.latest_outputs || sources().map(s=>s.file)};
    }
    async function trackExecution(run){
      if(tracking || closed)return;tracking=true;if(runTimer)clearTimeout(runTimer);
      runButton.disabled=true;
      const paint=view=>{
        if(closed || !view.canvas_document)return;
        const previous=window.RelayWorkflow.renderKey(display);display=view;
        const done=completedResult(view);
        if(done && done.key!==completionSeen){selected=done.task;inspectorTabs.set(selected,'results');completionSeen=done.key;renderPending=true;}
        record={...view.canvas_document};saveChatScope();o.onSaved?.(record);
        status.textContent=stateLabel(view.status);runButton.disabled=!!view.executing_runs?.length;
        renderPending ||= previous!==window.RelayWorkflow.renderKey(view);
        if(renderPending && !canvas.querySelector('input:focus,textarea:focus,select:focus')){render();renderPending=false;}
      };
      try{paint(await o.trackRun(run,paint,()=>!closed));}
      catch(e){notice.replaceChildren(node('span','Run started, but its status could not be refreshed: '+String(e)),button('Refresh status',()=>trackExecution(run),'quiet'));}
      finally{tracking=false;if(!closed && (renderPending || display?.executing_runs?.length || ['active','settling'].includes(display?.status) || display?.canvas_pending))runTimer=setTimeout(()=>trackExecution(run),2000);}
    }
    function completedResult(view){
      if(view?.status!=='completed' || view.executing_runs?.length)return null;
      const files=window.RelayWorkflow.resultFiles(view).primary.filter(f=>f.result_role!=='technical');
      return files.length?{task:files[0].task,key:JSON.stringify(files.map(f=>[f.id,f.sha256]))}:null;
    }
    let completionSeen=completedResult(display)?.key;
    if(!selected && completionSeen){selected=completedResult(display).task;inspectorTabs.set(selected,'results');}
    async function edit(change,choose=selected){
      if(pending)return;pending=true;save.disabled=true;historyState();const next=copy(document),before=snapshot();
      try{change(next);if(next.tasks.length)await request('node-validate',{workflow:next,...(record?.canvas?{canvas:record.canvas}:{})});if(closed)return;document=next;selected=choose;rememberEdit(before);changed();render();}
      catch(e){notice.textContent=String(e);render();}finally{pending=false;save.disabled=false;historyState();}
    }
    function field(label,control){const wrap=node('label',undefined,'node-field');wrap.append(node('span',label),control);control.setAttribute('aria-label',label);return wrap;}
    function select(options,value,change){const s=node('select');for(const [v,label] of options){const p=node('option',label);p.value=v;s.append(p);}s.value=value;s.onchange=()=>change(s.value);return s;}
    function inspect(projected,panel){
      disposeInspector();disposeInspector=()=>{};
      if(['uncertain','blocked'].includes(projected.status) && projected.error)panel.append(node('p',projected.error,'feedback error'));
      if(projected.status==='uncertain')panel.append(node('p',projected.can_start_new_attempt?'Edit the prompt, then Run to confirm a separate new attempt. The previous outcome stays unknown and remains in history. Editing does not retry.':'You can edit inputs for later. Run is blocked until the worker has stopped and a separate attempt can be confirmed. Editing does not retry.','hint'));
      const current=(display?.latest_outputs || []).filter(f=>f.task===projected.id),historical=(display?.historical_outputs || []).filter(f=>f.task===projected.id);
      if(!current.length && !historical.length && !projected.versions?.length){inspectInputs(projected,panel);return;}
      const inputPane=node('div'),resultPane=node('div'),tabs=node('div',undefined,'inspector-tabs');
      const choose=tab=>{inspectorTabs.set(projected.id,tab);inputPane.hidden=tab!=='inputs';resultPane.hidden=tab!=='results';inputsButton.setAttribute('aria-pressed',String(tab==='inputs'));resultsButton.setAttribute('aria-pressed',String(tab==='results'));};
      const inputsButton=button('Inputs',()=>choose('inputs'),'quiet'),resultsButton=button('Results',()=>choose('results'),'quiet');tabs.append(inputsButton,resultsButton);panel.append(tabs,inputPane,resultPane);
      inspectInputs(projected,inputPane);disposeInspector=o.renderResults?.(projected,resultPane,current,historical,display) || (()=>{});
      choose(inspectorTabs.get(projected.id) || (projected.status==='completed'?'results':'inputs'));
    }
    function inspectInputs(projected,panel){
      if(projected.reused_source){
        selected=projected.id;
        panel.append(node('p','Completed source · exact saved result. This node will not run again.','hint'));
        if(projected.prompt)panel.append(node('h4','Original prompt'),node('p',projected.prompt));
        panel.append(button('Open original run',()=>o.onRun(projected.run),'quiet'));
        return;
      }
      const task=document.tasks.find(t=>t.id===projected.id);selected=task.id;
      const heading=panel.querySelector('h3');if(heading)heading.textContent=task.operation==='model'?'AI task':task.objective;
      const optional=node('details');optional.append(node('summary','Advanced'));
      const objective=node(task.operation==='model'?'textarea':'input');objective.value=task.objective;objective.onchange=()=>edit(w=>{w.tasks.find(t=>t.id===task.id).objective=objective.value;});(task.operation==='model'?panel:optional).append(field(task.operation==='model'?'Prompt':'Step name',objective));
      if(task.operation==='model'){
        const choices=[];
        for(const source of document.tasks.filter(t=>t.id!==task.id))for(const [output,port] of Object.entries(outputs(source))){
          if(Object.values(task.inputs).flatMap(rawRefs).some(r=>r.task===source.id && r.output===output))continue;
          choices.push([JSON.stringify({task:source.id,output}),`${source.objective} → ${port.label || output}`]);
        }
        if(choices.length){
          panel.append(field('Connect node output',select([['','Choose an output…'],...choices],'',value=>{
            if(!value)return;
            const ref=JSON.parse(value),source=document.tasks.find(t=>t.id===ref.task),port=outputs(source)[ref.output];
            edit(w=>{
              const t=w.tasks.find(t=>t.id===task.id);
              const base=('input-'+ref.output).toLowerCase().replace(/[^a-z0-9_-]/g,'-').slice(0,58);
              let key=base,n=2;while(Object.hasOwn(t.input_definitions,key))key=base+'-'+n++;
              t.input_definitions[key]={type:'artifact',label:port.label || ref.output,media_type:port.media_type || '*/*',required:true};
              t.inputs[key]=ref;
            });
          })),node('p','Choose a result from another node. Relay adds the input and connects it.','hint'));
        }
      }
      const ordered=Object.entries(inputs(task)).sort(([a],[b])=>(a==='prompt'?-2:a==='files'?-1:0)-(b==='prompt'?-2:b==='files'?-1:0));
      for(const [name,p] of ordered){
        if(name==='model' && definition(task)?.inputs.model)continue;
        const binding=task.inputs[name],rule=p.schema || p,label=p.label || name;
        const group=node('div',undefined,'node-input'),settings=node('details');settings.append(node('summary',label+' options'));
        const set=b=>edit(w=>{const t=w.tasks.find(t=>t.id===task.id);if(b===undefined)delete t.inputs[name];else t.inputs[name]=b;});
        if(p.kind==='artifact'||p.kind==='artifacts'){
          group.append(node('h4',label));
          if(binding?.workflow)group.append(node('p','Choose a file when this workflow runs.','hint'));
          else sourcePicker(group,task,name,p,set);
          if(p.kind==='artifact')settings.append(button('Ask for file when run',()=>edit(w=>{const key=task.id+'-'+name;w.inputs[key]={type:'artifact',media_type:'*/*',label,required:!!p.required};w.tasks.find(t=>t.id===task.id).inputs[name]={workflow:key};}),'quiet'));
          if((rule.anyOf || []).some(r=>r.type==='null'))settings.append(button('No '+label,()=>set({value:null}),'quiet'));
        }else if(task.operation==='review' && name==='candidate'){
          group.append(field('Task to review',select([['','Choose a node'],...document.tasks.filter(t=>t.id!==task.id).map(t=>[t.id,t.objective])],binding?.value || '',v=>set(v?{value:v}:undefined))));
        }else {
          const mode=binding?.workflow?'workflow':'value';
          settings.append(field(label+' source',select([['value','Value'],['workflow','Ask when run']],mode,m=>{
            if(m==='value')return set(undefined);
            if(!rule.type)return notice.textContent='Choose a value for this input first.';
            edit(w=>{const key=task.id+'-'+name;w.inputs[key]={type:rule.type,label,required:!!p.required};w.tasks.find(t=>t.id===task.id).inputs[name]={workflow:key};});
          })));
          if(mode==='workflow'){
            const key=binding.workflow,source=document.inputs[key] || {};
            const value=record?.values?.[key] ?? source.default ?? p.default;
            group.append(field(label,literalControl(rule,value,v=>edit(w=>{
              w.tasks.find(t=>t.id===task.id).inputs[name]={value:v};
              const uses=value=>value && typeof value==='object' && (value.workflow===key || Object.values(value).some(uses));
              if(!w.tasks.some(t=>uses(t.inputs)))delete w.inputs[key];
            }),label)),node('p','Workflow input · editing here saves a value for this node’s next run.','hint'));
          }
          else group.append(field(label,literalControl(rule,binding?.value ?? p.default,v=>set({value:v}),label)));
        }
        if(binding)settings.append(button('Clear '+label,()=>set(undefined),'quiet'));
        if(settings.children.length>1)optional.append(settings);
        (p.required || binding || p.kind==='artifact' || p.kind==='artifacts' || name==='prompt' || name==='aspect_ratio'?panel:optional).append(group);
      }
      setupInspector(task,panel);
      if(task.operation==='model'){
        const add=node('details');add.append(node('summary','+ Input'));const name=node('input');name.placeholder='article';
        const media=node('input');media.value='*/*';const type=select([['string','Text'],['artifact','File / from another step'],['number','Number'],['boolean','Boolean']], 'string',()=>{media.parentElement.hidden=type.value!=='artifact';});
        const addInput=button('Add input',()=>{
          const key=name.value.trim();
          if(!/^[a-z][a-z0-9_-]{0,63}$/.test(key)){notice.textContent='Enter an input name starting with a lowercase letter; use letters, numbers, hyphens or underscores.';return;}
          edit(w=>{const t=w.tasks.find(t=>t.id===task.id);if(Object.hasOwn(t.input_definitions,key))throw Error('That input already exists');t.input_definitions[key]={type:type.value,label:key,required:true,...(type.value==='artifact'?{media_type:media.value}:{})};});
        },'quiet');
        addInput.disabled=true;name.oninput=()=>{addInput.disabled=!/^[a-z][a-z0-9_-]{0,63}$/.test(name.value.trim());};
        add.append(field('Input name',name),field('Input type',type),field('Accepted media type',media),addInput);panel.append(add);media.parentElement.hidden=true;
      }
      optional.append(node('h4','Outputs'));
      for(const [name,p] of Object.entries(outputs(task)))optional.append(node('p',`${p.label || name} · ${p.media_type}`,'hint'));
      if(task.operation==='model'){
        const output=node('details');output.append(node('summary','Edit outputs'));
        task.outputs.forEach((port,index)=>{
          const row=node('div');
          for(const [key,label] of [['name','Output name'],['media_type','Output format'],['purpose','Output label']]){
            const input=key==='media_type'?select([...new Map([['text/markdown','Markdown'],['text/plain','Plain text'],['application/json','JSON'],['image/png','PNG image'],['application/zip','ZIP bundle'],[port.media_type,port.media_type]]).entries()],port[key],v=>change(v)):node('input');
            function change(v){edit(w=>{w.tasks.find(t=>t.id===task.id).outputs[index][key]=v;});}
            if(key!=='media_type'){input.value=port[key];input.onchange=()=>change(input.value.trim());}
            row.append(field(label,input));
          }
          if(task.outputs.length>1)row.append(button('Remove output',()=>edit(w=>{w.tasks.find(t=>t.id===task.id).outputs.splice(index,1);}), 'quiet'));
          output.append(row);
        });
        output.append(button('Add output',()=>edit(w=>{const t=w.tasks.find(t=>t.id===task.id);let i=2;while(t.outputs.some(p=>p.name==='result'+i))i++;t.outputs.push({name:'result'+i,media_type:'text/plain',purpose:'Result '+i});}),'quiet'));panel.append(output);
      }
      optional.append(node('p',task.operation,'hint'),button('Remove step',()=>edit(w=>{if(record && w.tasks.length===1)throw Error('A saved workflow needs at least one step.');if(w.tasks.some(t=>Object.values(t.inputs).flatMap(refs).some(r=>r.task===task.id)))throw Error('Disconnect this step’s outputs first.');w.tasks=w.tasks.filter(t=>t.id!==task.id);},null),'quiet'));panel.append(optional);
    }
    function compatible(p,port){
      const accepted=p.accepts || (p.media_type?[p.media_type]:[]);
      return !accepted.length || accepted.includes('*/*') || accepted.includes(port.media_type);
    }
    function sourcePicker(group,task,name,p,set){
      const many=p.kind==='artifacts',rule=p.schema || p,batch=many && rule.minItems>1;
      let chosen=copy(many?(task.inputs[name]?.value || []):(task.inputs[name] && !('value' in task.inputs[name])?[task.inputs[name]]:[]));
      const identity=r=>r.task?JSON.stringify([r.task,r.output]):JSON.stringify([r.artifact]);
      function caption(r){
        const step=document.tasks.find(t=>t.id===r.task);
        if(step)return `${step.objective} → ${outputs(step)[r.output]?.label || r.output}`;
        const source=(record?.completed_sources || []).find(s=>s.file.id===r.artifact);
        if(source)return `${source.node.objective} → ${source.file.path.split('/').pop()} (saved file)`;
        return r.artifact?'Saved file: '+(localFiles.find(f=>f.artifact===r.artifact)?.name || r.artifact.slice(0,8)):r.task+' → '+r.output;
      }
      function commit(next){
        if(pending)return;
        if(next.length>(rule.maxItems || 100)){notice.textContent='This input accepts up to '+rule.maxItems+' files.';return;}
        if(batch){chosen=next;draw();return;}
        set(next.length?(many?{value:next}:next[0]):undefined);
      }
      function add(items){
        if(pending)return;
        const next=many?copy(chosen):[];
        for(const item of items)if(!next.some(r=>identity(r)===identity(item)))next.push(item);
        if(many && next.length===chosen.length){notice.textContent='That output or file is already connected.';return;}
        commit(next);
      }
      const refs=[];
      for(const t of document.tasks.filter(t=>t.id!==task.id))for(const [key,port] of Object.entries(outputs(t)))if(compatible(p,port))refs.push([JSON.stringify({task:t.id,output:key}),`${t.objective} → ${port.label || key}`]);
      for(const s of record?.completed_sources || [])if(compatible(p,s.node.planned_outputs[0]))
        refs.push([JSON.stringify({artifact:s.file.id}),`${s.node.objective} / ${s.file.path.split('/').pop()} (completed)`]);
      if(batch)group.append(node('p','Choose at least '+rule.minItems+' files, then connect them.','hint'));
      const list=node('div');group.append(list);
      function draw(){
        list.replaceChildren();if(!chosen.length)list.append(node('p','No reference connected.','hint'));
        chosen.forEach((r,i)=>{
          const label=caption(r),row=node('div');
          row.append(node('span',label),button('Remove '+label,()=>commit(chosen.filter((_,n)=>n!==i)),'quiet'));
          if(!r.task)row.append(node('p','Fixed saved file','hint'));
          if(chosen.slice(0,i).some(x=>identity(x)===identity(r)))row.append(node('p','Duplicate connection. Remove this extra entry.','hint'));
          if(many && i)row.append(button('Move up '+label,()=>{const next=copy(chosen);[next[i-1],next[i]]=[next[i],next[i-1]];commit(next);},'quiet'));list.append(row);
        });
      }
      const picker=select([['','Choose an output to connect'],...refs],!many&&chosen[0]?.task?JSON.stringify({task:chosen[0].task,output:chosen[0].output}):'',v=>{if(!v)return;add([JSON.parse(v)]);});
      group.append(field((p.label || name)+' from step',picker));
      if(!refs.length)group.append(node('p','No compatible outputs in this graph. Choose a file instead.','hint'));
      const files=node('details');files.append(node('summary','Or use an uploaded / saved file'));group.append(files);
      const remembered=localFiles.filter(f=>compatible(p,f));if(remembered.length)files.append(field('Saved file',select([['','Choose a saved file'],...remembered.map(f=>[f.artifact,f.name])],'',v=>{if(v)add([{artifact:v}]);})));
      files.append(button('Choose '+(many?'files':'file'),async()=>{
        try{const picked=await o.pickFiles?.();if(!picked)return;const paths=Array.isArray(picked)?picked:[picked];if(!many&&paths.length!==1)throw Error('Choose one file for this input.');
          const response=await request('node-file-import',{paths});localFiles.push(...response.files);
          if(response.files.some(f=>!compatible(p,f)))throw Error('A selected file has an incompatible format. Choose a compatible file.');
          add(response.files.map(f=>({artifact:f.artifact})));
        }catch(e){notice.textContent=String(e);}
      },'quiet'));
      if(batch)group.append(button('Connect files',()=>{
        if(chosen.length<rule.minItems){notice.textContent='Choose at least '+rule.minItems+' files.';return;}
        set({value:chosen});
      },'quiet'));
      draw();
    }
    function literalControl(rule,value,change,label){
      if(rule.enum)return select([['','Choose…'],...rule.enum.map(v=>[JSON.stringify(v),String(v)])],value===undefined?'':JSON.stringify(value),v=>{if(v!=='')change(JSON.parse(v));});
      if(rule.type==='null'){const p=node('span','None');if(value!==null)p.append(button('Set none',()=>change(null),'quiet'));return p;}
      if(rule.type==='boolean')return select([['','Choose…'],['true','Yes'],['false','No']],value===undefined?'':String(value),v=>{if(v)change(v==='true');});
      if(rule.type==='number'||rule.type==='integer'){
        const input=node('input');input.type='number';input.value=value===undefined?'':String(value);if(rule.minimum!==undefined)input.min=rule.minimum;if(rule.maximum!==undefined)input.max=rule.maximum;input.step=rule.type==='integer'?'1':'any';
        input.onchange=()=>{if(input.value!=='')change(Number(input.value));};return input;
      }
      if(rule.type==='array' && ['string','integer','number'].includes(rule.items?.type)){
        const input=node('textarea');input.value=(value || []).join('\n');input.placeholder='One item per line';input.onchange=()=>change(input.value.split('\n').map(v=>v.trim()).filter(Boolean).map(v=>rule.items.type==='string'?v:Number(v)));return input;
      }
      if(rule.type==='object' && rule.properties || rule.type==='array' && rule.items?.type==='object'){
        const container=node('div');let local=copy(value ?? (rule.type==='array'?[]:{}));const body=node('div');
        function draw(){body.replaceChildren();const items=Array.isArray(local)?local:[local];items.forEach((item,index)=>{
          const group=node('div'),properties=rule.type==='array'?rule.items.properties:rule.properties;
          for(const [k,r] of Object.entries(properties || {}))group.append(field(k,literalControl(r,item[k],v=>{item[k]=v;},k)));
          if(Array.isArray(local))group.append(button('Remove item',()=>{local.splice(index,1);draw();},'quiet'));body.append(group);
        });}
        container.append(body);if(Array.isArray(local))container.append(button('Add item',()=>{local.push({});draw();},'quiet'));
        container.append(button('Apply '+label,()=>change(local),'quiet'));draw();return container;
      }
      const input=node(rule.type==='string'?(label.toLowerCase().includes('prompt')?'textarea':'input'):'textarea');input.value=value===undefined?'':rule.type==='string'?value:JSON.stringify(value,null,2);
      input.placeholder=rule.type==='string'?'Enter '+label.toLowerCase():'JSON object (custom fields)';
      input.onchange=()=>{try{change(rule.type==='string'?input.value:JSON.parse(input.value));}catch(e){notice.textContent='Enter a valid '+label+': '+e;}};return input;
    }
    function render(){disposeInspector();disposeInspector=()=>{};dispose();canvas.replaceChildren();dispose=window.RelayWorkflow.mount(canvas,projection(),{node,button,saved,stateLabel,outputFile:()=>node('span'),outputThumbnail:o.outputThumbnail,openOutput:o.openOutput,selection:selected,select:(id,prefs)=>{selected=id;if(id && prefs?.reveal!==false)canvas.classList.remove('inspector-hidden');},runNode:(task,host,reset)=>showRun(task.id,host,reset),inspect,emptyMessage:'Add a step to start composing your job.',legend:'Connect inputs using “From step” in the inspector.'});}
    async function openLibrary(){
      library.hidden=false;library.replaceChildren(node('p','Loading nodes…'));
      try{if(!rows.length)rows=(await request('node-catalog',{include_legacy:false})).operations.filter(r=>!r.legacy);if(closed)return;
        const header=node('div',undefined,'section-title');header.append(node('h3','Add a step'),button('×',()=>{library.hidden=true;},'quiet'));const search=node('input');search.type='search';search.placeholder='Search nodes…';search.setAttribute('aria-label','Search nodes');const list=node('div',undefined,'node-picker-list');library.replaceChildren(header,search,list);
        if(o.fromHistory)library.append(node('p','This creates a new draft. The saved run stays unchanged.','hint'));
        function draw(){
          list.replaceChildren();
          const matches=rows.filter(r=>[r.title,r.id,r.family,r.category].join(' ').toLowerCase().includes(search.value.trim().toLowerCase()))
            .sort((a,b)=>(a.category_order??99)-(b.category_order??99) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
          let category=null,group;
          for(const r of matches){
            const label=r.category || 'Other';
            if(label!==category){category=label;group=node('section',undefined,'node-picker-group');group.setAttribute('aria-label',label);group.append(node('h4',label));list.append(group);}
            const b=button('',()=>{
              const base=r.id.replace(/[^a-z0-9_-]/g,'-');let id=base,n=2;while(document.tasks.some(t=>t.id===id))id=base+'-'+n++;
              edit(w=>{const t={schema_version:3,id,operation:r.id,objective:r.title,inputs:{}};if(r.id==='model'){t.input_definitions={};t.outputs=[{name:'result',media_type:'text/markdown',purpose:'Result'}];if(chatChoice?.id)t.model=copy(chatChoice);}w.tasks.push(t);},id);
              library.hidden=true;
            },'node-choice');
            const copy=node('span',undefined,'node-choice-copy');copy.append(node('strong',r.title),node('span',r.family,'hint'));
            b.append(window.RelayWorkflow.operationIcon(r.id),copy);group.append(b);
          }
          if(!matches.length)list.append(node('p','No matching nodes.'));
        }
        search.oninput=draw;draw();search.focus();
      }catch(e){library.replaceChildren(node('p',String(e)));}
    }
    request('node-files',{}).then(result=>{localFiles=result.files || [];}).catch(()=>{});
    request('node-catalog',{include_legacy:false}).then(result=>{if(closed)return;rows=result.operations.filter(r=>!r.legacy);render();if(o.picker)openLibrary();if(o.runScope)showRun(o.runScope);else if(o.trackRun && record?.canvas && (display?.executing_runs?.length || ['active','settling'].includes(display?.status) || display?.canvas_pending))trackExecution(record.canvas);}).catch(e=>{notice.textContent=String(e);});
    return ()=>{closed=true;if(window.RelayNodeEditor.updateChatDefaults===receiveChatDefaults)delete window.RelayNodeEditor.updateChatDefaults;window.removeEventListener('keydown',historyKeydown);if(window.RelayNodeEditor.history===nativeHistory)delete window.RelayNodeEditor.history;if(chatTimer)clearTimeout(chatTimer);if(runTimer)clearTimeout(runTimer);undoStack.length=0;redoStack.length=0;disposeInspector();dispose();};
  }
  window.RelayNodeEditor={mount};
})();
