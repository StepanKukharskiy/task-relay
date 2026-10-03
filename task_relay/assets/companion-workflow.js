/* Read-only projection of committed task dependencies. No scheduling authority. */
((root) => {
  function layout(tasks) {
    const ids = new Set(tasks.map(t => t.id)), placed = new Set(), layers = [], edges = [], issues = [];
    const dependencies = new Map();
    for (const task of tasks) {
      const deps = [...new Set((task.dependencies || []).map(d => typeof d === 'string' ? d : d.task))];
      dependencies.set(task.id, deps);
      for (const dep of deps) {
        if (ids.has(dep)) edges.push({from:dep, to:task.id});
        else issues.push(`Step ${task.id} refers to unavailable prerequisite ${dep}.`);
      }
    }
    while (placed.size < ids.size) {
      const ready = tasks.filter(t => !placed.has(t.id) && dependencies.get(t.id).every(d => !ids.has(d) || placed.has(d)));
      if (!ready.length) {
        issues.push('Some recorded dependencies cannot be arranged. Inspect the steps below.');
        layers.push(tasks.filter(t => !placed.has(t.id))); break;
      }
      layers.push(ready); ready.forEach(t => placed.add(t.id));
    }
    return {layers, edges, issues, sequential:layers.every(layer => layer.length === 1) && edges.length === Math.max(0,tasks.length-1) && !issues.length};
  }
  function toolLabel(task) {
    const backend = task.backend || {}, tools = task.tools || [];
    const provider = backend.type ? backend.type.split('-')[0] : '';
    const names = {openai:'OpenAI',gemini:'Gemini',codex:'Codex',qwen:'Qwen',deepseek:'DeepSeek',openrouter:'OpenRouter'};
    const tool = task.execution?.capability || (tools.includes('computer') ? 'Safari' : tools.includes('browser') ? 'Browser' : tools.includes('python') ? 'Python' : tools.includes('shell') ? 'Shell' : 'Files');
    return [tool,names[provider] || provider,backend.model].filter(Boolean).join(' · ');
  }
  function stepLabel(task) { return (task.objective || task.id).split('\n')[0].slice(0,96); }
  function resultFiles(view, reviewed=new Set()) {
    const files=(view.latest_outputs || []).filter(f=>!reviewed.has(f.id));
    const selected=new Set((view.selections || []).filter(s=>files.some(f=>f.id===s.artifact && f.sha256===s.sha256)).map(s=>s.artifact));
    const ordered=layout(view.tasks || []).layers.flat();
    const last=[...ordered].reverse().find(t=>!t.review_of && files.some(f=>f.task===t.id)) || [...ordered].reverse().find(t=>files.some(f=>f.task===t.id));
    return {primary:files.filter(f=>selected.size ? selected.has(f.id) : !reviewed.size && f.task===last?.id),
      other:files.filter(f=>selected.size ? !selected.has(f.id) : reviewed.size || f.task!==last?.id)};
  }
  function mount(container, view, options) {
    const {node, button, saved, stateLabel, outputFile, select, selection} = options;
    const tasks = view.tasks || [], graph = layout(tasks), buttons = new Map(), cards = new Map();
    const changesFor=task=>(options.changes || []).filter(c=>(c.tasks || []).some(t=>t.task===task.id && t.attempt===task.latest_attempt));
    const revisionsFor=task=>(options.changes || []).filter(c=>c.kind==='revision' && c.revised_task===task.id && c.new.attempt===task.latest_attempt);
    const panel = node('section',undefined,'detail-section workflow-section'); panel.append(node('h2','Workflow'));
    panel.append(node('p','Select a step to see what it does and its files.','hint'));
    if (!tasks.length) { panel.append(node('p','No saved steps available.','muted')); container.append(panel); return () => {}; }
    graph.issues.forEach(issue => panel.append(node('p',issue,'feedback error')));
    const split = node('div',undefined,'workflow-split'), map = node('div',undefined,'workflow-map'), inspector = node('aside',undefined,'workflow-inspector');
    map.setAttribute('aria-label','Recorded workflow dependencies'); inspector.setAttribute('aria-label','Selected workflow step'); inspector.setAttribute('aria-live','polite');
    inspector.hidden=true;
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.classList.add('workflow-lines'); svg.setAttribute('aria-hidden','true'); map.append(svg);
    let selected = tasks.find(t => t.id === selection) || null;
    const prefix = [];
    for (const layer of graph.layers) { if (layer.some(t => t.status !== 'completed')) break; prefix.push(...layer); }
    const collapsible = prefix.length >= 4 && prefix.length < tasks.length;
    const collapsed = new Set(collapsible ? prefix.map(t => t.id) : []);
    let showCompleted = !collapsible || collapsed.has(selected?.id) || options.expanded === true;
    let toggle;
    function draw() {
      if (!map.isConnected) return;
      svg.replaceChildren(); const box = map.getBoundingClientRect(); svg.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);
      for (const edge of graph.edges) {
        const a = cards.get(edge.from), b = cards.get(edge.to);
        if (!a?.getClientRects().length || !b?.getClientRects().length) continue;
        const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
        const x1 = ar.x+ar.width/2-box.x, y1 = ar.bottom-box.y, x2 = br.x+br.width/2-box.x, y2 = br.top-box.y;
        // Invalid ordering is described in text, never drawn as a plausible flow.
        if (y2 <= y1) continue;
        const middle = (y1+y2)/2, path = document.createElementNS('http://www.w3.org/2000/svg','path');
        const fromLayer=graph.layers.findIndex(layer=>layer.some(t=>t.id===edge.from)), toLayer=graph.layers.findIndex(layer=>layer.some(t=>t.id===edge.to));
        // Long prerequisites run beside the intervening steps, rather than
        // disappearing underneath a node and implying an invented handoff.
        const gutter=box.width-3;
        path.setAttribute('d',toLayer-fromLayer>1 ? `M ${x1} ${y1} L ${x1} ${y1+10} L ${gutter} ${y1+10} L ${gutter} ${y2-10} L ${x2} ${y2-10} L ${x2} ${y2}` : `M ${x1} ${y1} C ${x1} ${middle}, ${x2} ${middle}, ${x2} ${y2}`); svg.append(path);
      }
    }
    function choose(task) {
      selected = task; select(task.id);inspector.hidden=false;
      for (const [id,b] of buttons) b.setAttribute('aria-pressed',String(id === task.id));
      const close=button('Close step',()=>{const origin=buttons.get(selected?.id);inspector.hidden=true;selected=null;select(null);buttons.forEach(b=>b.setAttribute('aria-pressed','false'));origin?.focus();},'quiet');
      const heading=node('div',undefined,'section-title');heading.append(node('h3',stepLabel(task)),close);
      inspector.replaceChildren(heading,node('p',stateLabel(task.status),'hint'));
      for(const change of revisionsFor(task))inspector.append(options.changeLink(change,change.label));
      for(const change of changesFor(task))inspector.append(options.changeLink(change,'Earlier source version · '+change.old.path));
      if (task.error) inspector.append(node('p',task.error,'feedback error'));
      if (task.review_of) inspector.append(node('p','Checks: '+(tasks.find(t=>t.id===task.review_of)?.objective || task.review_of),'hint'));
      if (task.quality_review) inspector.append(saved('Recorded review concerns',task.quality_review));
      const conversational=options.conversationView && (task.id.startsWith('conversation:') || task.id.startsWith('read:') || task.conversation_response);
      const inputs = node('div'); inputs.append(node('h4',task.latest_attempt ? 'Inputs' : 'Planned inputs'));
      const rows = task.latest_attempt ? task.recorded_inputs || [] : task.planned_inputs || [];
      for (const input of rows) {
        if (input.file) inputs.append(outputFile({...input.file,purpose:input.purpose}));
        else inputs.append(node('p',[input.path,input.from_task ? 'from '+(tasks.find(t=>t.id===input.from_task)?.objective || input.from_task) : '',task.latest_attempt ? 'Saved file unavailable' : 'Planned file'].filter(Boolean).join(' · '),'path'));
      }
      if (!rows.length) inputs.append(node('p',task.latest_attempt ? 'No input versions recorded for this attempt.' : 'No declared inputs.','hint'));
      if(!conversational)inspector.append(inputs);
      const current = (view.latest_outputs || []).filter(f => f.task === task.id), historical = (view.historical_outputs || []).filter(f => f.task === task.id);
      if(!conversational)inspector.append(node('h4','Results'));
      for (const file of current) inspector.append(outputFile(file,view.output_texts));
      if(conversational){
        if(task.id.startsWith('read:'))inspector.append(node('p',task.objective));
        else inspector.append(button('Open saved answer',()=>options.openConversation(task),'quiet'));
      }else if (!current.length) inspector.append(node('p',historical.length ? 'Outputs from this attempt are retained, not current.' : 'No current outputs recorded.','hint'));
      if (historical.length) { const old=saved('Retained outputs — not current',''); old.querySelector('pre').remove(); historical.forEach(f=>old.append(outputFile(f))); inspector.append(old); }
      if (!task.latest_attempt && task.planned_outputs?.length) inspector.append(saved('Planned outputs',task.planned_outputs));
      const details=saved('Details','');details.querySelector('pre').remove();
      details.append(node('p',toolLabel(task),'hint'),node('p',`${task.attempts || 0}/${task.max_attempts || '—'} attempts`,'hint'),node('p',task.instruction || 'No instruction recorded.','workflow-instruction'));
      details.append(saved('Full objective',task.objective || task.id));
      if(task.user_gate)details.append(saved('Decision scope',task.user_gate));
      details.append(saved('Input records',rows));
      details.append(saved('Output records',{current,previous:historical}));
      if (task.review_target) details.append(saved('Exact review target',task.review_target));
      if (task.activity) details.append(saved('Recorded activity',task.activity));
      details.append(saved('Saved identity',{step:task.id,attempt:task.latest_attempt || null,attempt_state:task.attempt_state || null,output_is_current:task.output_is_current || false}));inspector.append(details);
    }
    if (collapsible) {
      toggle=button('',()=>{showCompleted=!showCompleted; options.expand?.(showCompleted); applyCollapse();},'quiet workflow-collapse'); map.append(toggle);
    }
    const layers = [];
    for (const layer of graph.layers) {
      const row=node('div',undefined,'workflow-layer');
      for (const task of layer) {
        const card=node('div',undefined,'workflow-node'); cards.set(task.id,card);
        const b=button('',()=>choose(task),'workflow-step'); b.setAttribute('aria-pressed',String(task.id===selected?.id));
        b.append(node('strong',stepLabel(task)),node('span',task.status === 'queued' && !task.runnable ? 'Waiting' : stateLabel(task.status),'workflow-status '+(['blocked','uncertain','awaiting_user'].includes(task.status)?'attention':task.status==='completed'?'done':'')));
        buttons.set(task.id,b); card.append(b);
        for(const change of revisionsFor(task))card.append(options.changeLink(change,change.label));
        for(const change of changesFor(task))card.append(options.changeLink(change,'Earlier source version'));
        row.append(card);
      }
      layers.push({row,layer}); map.append(row);
    }
    function applyCollapse() {
      for (const {row,layer} of layers) row.hidden = !showCompleted && layer.every(t=>collapsed.has(t.id));
      if (toggle) { toggle.textContent=`${showCompleted?'Hide':'Show'} ${prefix.length} completed steps`; toggle.setAttribute('aria-expanded',String(showCompleted)); }
      requestAnimationFrame(draw);
    }
    split.append(map,inspector); panel.append(split); container.append(panel); if(selected)choose(selected); applyCollapse();
    const observer = new ResizeObserver(draw); observer.observe(map); cards.forEach(card=>observer.observe(card));
    const dispose=()=>observer.disconnect();dispose.showStep=id=>{const task=tasks.find(t=>t.id===id);if(task){choose(task);inspector.scrollIntoView({block:'nearest'});}};return dispose;
  }
  const api={layout,toolLabel,resultFiles,mount}; if(typeof module!=='undefined' && module.exports) module.exports=api; else root.RelayWorkflow=api;
})(typeof window==='undefined' ? {} : window);
