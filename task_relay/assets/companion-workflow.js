/* Read-only projection of committed task dependencies. No scheduling authority. */
((root) => {
  function hostCodeReview(container,checked,node) {
    const reviews=checked.host_reviews || [];
    for(const review of reviews){
      container.append(node('p',`${review.node}: Run this exact script in ${review.operation.split('.')[0]}? It has access to your Mac with your app permissions; it is not sandboxed. Approval applies only to these saved inputs and this script version.`,'feedback warning'));
      for(const file of review.documents){
        const details=node('details');details.append(node('summary','Review '+file.path.split('/').pop()),node('p','SHA-256 '+file.sha256,'hint'),node('pre',file.text));container.append(details);
      }
    }
    if(checked.deferred_host_nodes?.length)container.append(node('p','These script nodes will wait for exact-script approval after their inputs finish: '+checked.deferred_host_nodes.join(', ')+'. Then use Run on each node.','hint'));
    return reviews.map(r=>({node:r.node,digest:r.digest}));
  }
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
  function isModel(task) { return !task.review_of && !task.execution && (task.operation==='model' || (!task.operation && task.backend?.type?.endsWith('-agent'))); }
  function stepLabel(task) { return isModel(task) ? 'AI model' : (task.objective || task.id).split('\n')[0].slice(0,96); }
  function modelLabel(task) {
    const op=task.execution?.capability || task.operation || '';
    const names={codex:'Codex',gemini:'Gemini',openai:'OpenAI',openrouter:'OpenRouter',qwen:'Qwen',deepseek:'DeepSeek'};
    const provider=names[op.split('.')[0]] || names[task.backend?.type?.split('-')[0]];
    return [provider,task.backend?.model].filter(Boolean).join(' · ');
  }
  function promptValue(task) { return isModel(task) ? task.objective : task.prompt; }
  function resultFiles(view, reviewed=new Set()) {
    const files=(view.latest_outputs || []).filter(f=>!reviewed.has(f.id));
    const selected=new Set((view.selections || []).filter(s=>files.some(f=>f.id===s.artifact && f.sha256===s.sha256)).map(s=>s.artifact));
    const delivered=new Set((view.delivered_outputs || []).filter(s=>files.some(f=>f.id===s.artifact && f.sha256===s.sha256)).map(s=>s.artifact));
    if(delivered.size)return {primary:files.filter(f=>delivered.has(f.id)),other:files.filter(f=>!delivered.has(f.id))};
    const ordered=layout(view.tasks || []).layers.flat();
    const last=[...ordered].reverse().find(t=>!t.review_of && files.some(f=>f.task===t.id)) || [...ordered].reverse().find(t=>files.some(f=>f.task===t.id));
    return {primary:files.filter(f=>selected.size ? selected.has(f.id) : !reviewed.size && f.task===last?.id),
      other:files.filter(f=>selected.size ? !selected.has(f.id) : reviewed.size || f.task!==last?.id)};
  }
  // Shared local icon presentation for the canvas, picker and catalog. No runtime authority.
  function icon(kind) {
    const paths={chat:['M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z'],history:['M3 12a9 9 0 1 0 2.6-6.4L3 8','M3 3v5h5','M12 7v5l4 2'],web:['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z','M3 12h18','M12 3a17 17 0 0 1 0 18 17 17 0 0 1 0-18Z'],review:['M9 12l2 2 4-4','M12 3l8 4v5c0 5-8 9-8 9S4 17 4 12V7l8-4Z'],model:['m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z'],file:['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z','M14 2v6h6','M8 13h8M8 17h6']};
    Object.assign(paths,{
      image:['M4 3h16v18H4Z','m4 16 5-5 4 4 3-3 4 4','M8 7h.01'],
      crop:['M7 3v14h14','M3 7h14v14'],
      download:['M12 3v12m-5-5 5 5 5-5','M4 16v5h16v-5'],
      gallery:['M3 3h7v7H3Zm11 0h7v7h-7ZM3 14h7v7H3Zm11 0h7v7h-7Z'],
      slides:['M3 4h18v13H3Z','M12 17v4m-5 0h10','M7 8h6m-6 4h10'],
      collection:['M8 3h13v13','M3 8h13v13H3Z','M6 12h7m-7 4h7'],
      merge:['M4 3v4c0 5 8 2 8 7v7m8-18v4c0 5-8 2-8 7','m8 17 4 4 4-4'],
      layout:['M3 3h18v18H3Z','M3 9h18M9 9v12'],
      video:['M3 5h13v14H3Z','m16 10 5-4v12l-5-4'],
      mesh:['m12 2 9 5v10l-9 5-9-5V7Z','m3 7 9 5 9-5M12 12v10'],
      text:['M4 5h16M12 5v15m-4 0h8'],
      operation:['M4 4h16v16H4Z','M8 8h8v8H8Z','M8 1v3m8-3v3M8 20v3m8-3v3M1 8h3m-3 8h3M20 8h3m-3 8h3']
    });
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    for(const [name,value] of Object.entries({viewBox:'0 0 24 24',width:'16',height:'16',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(name,value);
    for(const d of paths[kind] || paths.file){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);svg.append(path);}return svg;
  }
  function operationVisual(task) {
    const op=typeof task==='string'?task:(task.execution?.capability || task.operation || (task.review_of?'review':'model'));
    const family=op.split('.')[0];
    // Only explicit operation/backend identity determines software. An objective
    // mentioning an app, or a browser tool grant, does not establish its use.
    const brand={perplexity:['Perplexity','perplexity','web'],higgsfield:['Higgsfield','higgsfield','video'],runway:['Runway','runway','video'],blender:['Blender','blender','mesh'],rhino:['Rhino','rhinoceros','mesh'],rhino3dm:['Rhino 3DM','rhinoceros','mesh'],sketchup:['SketchUp','sketchup','mesh'],gemini:['Gemini','googlegemini','model'],openrouter:['OpenRouter','openrouter','model']}[family];
    if(brand)return {label:brand[0],logo:brand[1],kind:brand[2]};
    if(['web.sources','web.sources.coverage','web.sources.prepared'].includes(op))return {label:'Gemini search',logo:'googlegemini',kind:'web'};
    if(op.endsWith('.codex'))return {label:'Codex search',kind:'model'};
    if(family==='model' && typeof task!=='string'){
      const provider=task.backend?.type?.split('-')[0];
      if(provider==='gemini')return {label:'Gemini',logo:'googlegemini',kind:'model'};
      if(provider==='openrouter')return {label:'OpenRouter',logo:'openrouter',kind:'model'};
      if(provider)return {label:provider==='codex'?'Codex':provider==='openai'?'OpenAI':provider,kind:'model'};
    }
    const exact={'workflow.proposal':'layout','xfigura.render':'image','images.crop':'crop','images.fetch':'download','images.gallery':'gallery','images.merge':'merge','images.pptx':'slides','collection.slides':'slides','document.layout':'layout','records.merge':'merge'};
    const families={web:'web',images:'image',collection:'collection',document:'file',pptx:'slides',text:'text',media:'video',hyperframes:'video',meshy:'mesh',review:'review',model:'model',openai:'model',higgsfield:op.endsWith('.image')?'image':'video',runway:op.endsWith('.image')?'image':'video'};
    const kind=exact[op] || families[family] || 'operation';
    const names={web:'Web',images:'Images',collection:'Collection',document:'Document',pptx:'PowerPoint file',text:'Text',media:'Media',hyperframes:'HyperFrames',meshy:'Meshy',review:'Review',model:'AI task',openai:'OpenAI',higgsfield:'Higgsfield',runway:'Runway'};
    return {label:names[family] || op,kind};
  }
  function operationIcon(task) {
    const v=operationVisual(task),wrap=document.createElement('span');
    wrap.className='operation-icon';wrap.setAttribute('data-icon',v.logo || v.kind);wrap.setAttribute('aria-hidden','true');wrap.title=v.label;
    if(v.logo){const img=document.createElement('img');img.src='node-icons/'+v.logo+(['higgsfield','runway'].includes(v.logo)?'.png':'.svg');img.alt='';img.width=22;img.height=22;img.onerror=()=>{wrap.replaceChildren(icon(v.kind));};wrap.append(img);}
    else wrap.append(icon(v.kind));
    return wrap;
  }
  let connectionSnapshot=null;
  function channelStatus(info,channel){
    if(!info)return {state:'unknown',label:'Status unavailable'};
    const paired=channel==='telegram'?info.setup?.telegram?.paired:info.messages?.paired;
    const service=channel==='telegram'?info.service:info.messages,policy=info.channels?.policy;
    if(!paired)return {state:'off',label:'Not connected'};
    if(service?.error || info.channels?.error)return {state:'attention',label:'Needs attention'};
    if(policy?.paused)return {state:'off',label:'Messaging paused'};
    if(policy?.enabled?.[channel]===false)return {state:'off',label:'Turned off'};
    if(!service?.healthy)return {state:service?.loaded?'attention':'off',label:service?.loaded?'Checking connection':'Stopped'};
    if(!policy || !info.channels?.runtime?.[channel])return {state:'attention',label:'Waiting for service confirmation'};
    return {state:'connected',label:'Connected'};
  }
  function paintChannel(control,info){
    const channel=control.dataset.relayChannel,status=channelStatus(info,channel),name=channel==='telegram'?'Telegram':'Messages';
    control.dataset.state=status.state;control.title=name+' · '+status.label;
    control.setAttribute('aria-label',control.title+' · Open Connections');
  }
  function updateConnectionStatus(info){
    connectionSnapshot=info;
    for(const control of document.querySelectorAll('[data-relay-channel]'))paintChannel(control,info);
  }
  function connectionIndicators({node,button,open}){
    const group=node('div',undefined,'canvas-connections');group.setAttribute('aria-label','Messenger connections');
    for(const channel of ['telegram','messages']){
      const control=button('',()=>open?.(), 'canvas-connection');control.dataset.relayChannel=channel;
      if(channel==='messages'){
        const logo=document.createElementNS('http://www.w3.org/2000/svg','svg');logo.setAttribute('viewBox','0 0 24 24');logo.setAttribute('aria-hidden','true');
        const tile=document.createElementNS('http://www.w3.org/2000/svg','rect');
        for(const [key,value] of Object.entries({width:24,height:24,rx:6,fill:'currentColor'}))tile.setAttribute(key,value);
        const bubble=document.createElementNS('http://www.w3.org/2000/svg','path');bubble.setAttribute('d','M12 5C6 5 3.5 8 3.5 11.5c0 2.1 1.3 4 3.5 5l-1 2.6 4-1.5c7.3.8 10.5-2.5 10.5-6.1C20.5 8 18 5 12 5Z');bubble.setAttribute('fill','white');logo.append(tile,bubble);control.append(logo);
      }
      else {
        const logo=document.createElementNS('http://www.w3.org/2000/svg','svg');logo.setAttribute('viewBox','0 0 24 24');logo.setAttribute('aria-hidden','true');
        const circle=document.createElementNS('http://www.w3.org/2000/svg','circle');circle.setAttribute('cx','12');circle.setAttribute('cy','12');circle.setAttribute('r','12');circle.setAttribute('fill','currentColor');
        const plane=document.createElementNS('http://www.w3.org/2000/svg','path');plane.setAttribute('d','M5 11.5 19 6l-2.6 12-4.1-3.1-2.4 2 .5-3.9 6.2-5-7.8 4.4Z');plane.setAttribute('fill','white');logo.append(circle,plane);control.append(logo);
      }
      const dot=node('span',undefined,'connection-dot');dot.setAttribute('aria-hidden','true');control.append(dot);paintChannel(control,connectionSnapshot);group.append(control);
    }
    return group;
  }
  const canvasViews=new Map();
  const expandedPanels=new Map();
  // View state only: remounts/polling must not collapse a reader's panel.
  function panelWidth(panel,heading,key,label,{button}){
    const control=button('',()=>{expandedPanels.set(key,!expandedPanels.get(key));paint();},'quiet');
    function paint(){
      const expanded=!!expandedPanels.get(key);
      panel.classList.toggle('panel-expanded',expanded);
      control.textContent=expanded?'↙':'↗';
      control.title=expanded?'Restore '+label+' width':'Expand '+label+' to full width';
      control.setAttribute('aria-label',control.title);control.setAttribute('aria-pressed',String(expanded));
    }
    heading.append(control);paint();
    if(expandedPanels.size>100)expandedPanels.delete(expandedPanels.keys().next().value);
    return control;
  }
  function jobTitle(current,question,workflow){
    if(current?.trim() && current.trim().toLowerCase()!=='untitled job')return current;
    const task=workflow?.tasks?.[0];
    const prompt=task?.inputs?.prompt;
    const text=String(question || (typeof prompt?.value==='string'?prompt.value:'') || task?.objective || '').replace(/\s+/g,' ').trim();
    if(!text)return current || 'Untitled job';
    const short=text.length>72?text.slice(0,69).replace(/\s+\S*$/,'')+'…':text;
    return short.charAt(0).toUpperCase()+short.slice(1);
  }
  const portName=path=>String(path || '').split('/').pop();
  function taskPorts(task){
    const imageOperation=(task.execution?.capability || task.operation || '').endsWith('.image');
    const image=p=>p.media_type?.startsWith('image/') || /\.(png|jpe?g|webp|gif)$/i.test(p.path || '');
    return {inputs:(task.planned_inputs || []).map((p,i)=>({id:p.path || String(i),label:p.name || (imageOperation && (image(p) || ['files','result'].includes(p.path))?'Reference image':p.purpose || portName(p.path) || 'Input')})),
      outputs:(task.planned_outputs || []).map((p,i)=>({output_port:p.output_port,id:p.path || String(i),label:p.label || p.name || (image(p) || imageOperation?'Generated image':p.purpose || portName(p.path) || 'Output')}))};
  }
  function canvasEdges(tasks){
    const byId=new Map(tasks.map(t=>[t.id,t])),edges=[],seen=new Set(),pairs=new Set();
    for(const task of tasks)for(const input of task.planned_inputs || []){
      const from=byId.get(input.from_task);
      if(!from || !input.output || !(from.planned_outputs || []).some(o=>o.path===input.output))continue;
      const key=JSON.stringify([from.id,task.id,input.output,input.path]);if(seen.has(key))continue;seen.add(key);pairs.add(JSON.stringify([from.id,task.id]));
      edges.push({from:from.id,to:task.id,output:input.output,input:input.path,kind:'binding'});
    }
    for(const edge of layout(tasks).edges)if(!pairs.has(JSON.stringify([edge.from,edge.to])))edges.push({...edge,kind:'dependency'});
    return edges;
  }
  // Compose only saved execution graphs. Never turn stage order or messages
  // into dependencies. IDs are namespaced because runs reuse task names.
  function pipelineGraph(view) {
    const tasks=[],latest_outputs=[],historical_outputs=[],missing=[],seen=new Set();
    const identity=(run,id)=>JSON.stringify([run,id]);
    for(const stage of view.stages || []){
      const execution=stage.execution;
      if(!execution?.tasks?.length){missing.push(stage.id || stage.request_id);continue;}
      if(seen.has(execution.name))continue;seen.add(execution.name);
      for(const task of execution.tasks)tasks.push({...task,id:identity(execution.name,task.id),original_id:task.id,run:execution.name,stage_id:stage.id || stage.request_id,
        dependencies:(task.dependencies || []).map(dep=>({...(typeof dep==='string'?{}:dep),task:identity(execution.name,typeof dep==='string'?dep:dep.task)})),
        review_of:task.review_of?identity(execution.name,task.review_of):null,
        planned_inputs:(task.planned_inputs || []).map(input=>({...input,from_task:input.from_task?identity(execution.name,input.from_task):undefined}))});
      for(const [key,target] of [['latest_outputs',latest_outputs],['historical_outputs',historical_outputs]])
        for(const file of execution[key] || [])target.push({...file,task:identity(execution.name,file.task)});
    }
    // Cross-run wires require exact committed artifact identity AND hash.
    // A path or stage position is never enough. Retained versions stay in the
    // inspector; they must not be relabeled as a current node output.
    for(const task of tasks)for(const input of task.recorded_inputs || []){
      const matches=latest_outputs.filter(file=>file.id===input.artifact && file.sha256===input.sha256 && file.task!==task.id);
      if(matches.length!==1)continue;const file=matches[0],producer=tasks.find(t=>t.id===file.task);
      if(!producer || producer.run===task.run || !(producer.planned_outputs || []).some(p=>p.path===file.path))continue;
      const port=task.planned_inputs.find(p=>p.path===input.path);
      if(!port || port.from_task)continue;
      port.from_task=file.task;port.output=file.path;
      task.dependencies.push({task:file.task});
    }
    return {name:'pipeline:'+view.id,tasks,latest_outputs,historical_outputs,missing};
  }
  function withCompletedSources(view){
    const sources=view.completed_sources || [];
    const files=[...(view.latest_outputs || []),...sources.map(s=>s.file)];
    const tasks=[...sources.map(s=>s.node),...(view.tasks || []).map(t=>({...t,
      dependencies:[...(t.dependencies || [])],
      planned_inputs:(t.planned_inputs || []).map(input=>{
        if(view.canvas_document)return input;
        const exact=(t.recorded_inputs || []).find(r=>r.path===input.path) || input;
        const file=files.find(f=>f.task!==t.id && f.id===exact.artifact && (!exact.sha256 || f.sha256===exact.sha256));
        return file?{...input,from_task:file.task,output:file.path}:input;
      })}))];
    for(const t of tasks)for(const input of t.planned_inputs || [])if(input.from_task && !t.dependencies?.some(d=>(d.task || d)===input.from_task))
      t.dependencies=[...(t.dependencies || []),{task:input.from_task}];
    return {...view,tasks,latest_outputs:files.map(f=>({...f,display_name:f.display_name || (/\.(png|jpe?g|webp|gif)$/i.test(f.path)?'Generated image':f.purpose || portName(f.path))}))};
  }
  function mount(container, view, options) {
    view=withCompletedSources(view);
    const {node, button, saved, stateLabel, outputFile, select, selection} = options;
    const tasks = view.tasks || [], graph = layout(tasks), buttons = new Map(), cards = new Map(), thumbnails=[];
    const changesFor=task=>(options.changes || []).filter(c=>(c.tasks || []).some(t=>t.task===task.id && t.attempt===task.latest_attempt));
    const revisionsFor=task=>(options.changes || []).filter(c=>c.kind==='revision' && c.revised_task===task.id && c.new.attempt===task.latest_attempt);
    const panel = node('section',undefined,'detail-section workflow-section');

    graph.issues.forEach(issue => panel.append(node('p',issue,'feedback error')));
    const split=node('div',undefined,'workflow-split'), map=node('div',undefined,'workflow-map'), world=node('div',undefined,'workflow-world'), inspector=node('aside',undefined,'workflow-inspector');
    map.setAttribute('aria-label',options.label || 'Workflow canvas. Drag the background to pan; use zoom controls.'); map.tabIndex=0;
    inspector.setAttribute('aria-label','Selected workflow step'); inspector.setAttribute('aria-live','polite'); inspector.hidden=false;
    inspector.append(node('h3','Inspector'),node('p',tasks.length?'Select a node to inspect its saved inputs, outputs and status.':'No saved node definition is available.','hint'));
    if(!tasks.length)map.append(node('p',options.emptyMessage || 'No saved workflow graph. This job has no saved node definitions; its chat and history remain available.','canvas-empty'));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('workflow-lines');svg.setAttribute('aria-hidden','true');world.append(svg);map.append(world);
    const key=view.name || view.id;
    const remembered=key ? canvasViews.get(key) : null;
    const inspectorTabs={...remembered?.inspectorTabs};
    const inspectorScroll={...remembered?.inspectorScroll};
    const positions=new Map(), portRows=new Map();
    let wireStyle=remembered?.wireStyle || 'bezier';
    let selected=tasks.find(t=>t.id===selection) || null, camera={x:50,y:90,scale:1}, disposed=false, dragging=null, suppressClick=false, fitted=!!remembered;
    const pictures=task=>(view.latest_outputs || []).filter(f=>f.task===task.id && f.id && f.sha256 && /\.(png|jpe?g|webp|gif)$/i.test(f.path));
    function arrange(savedPositions={}){graph.layers.forEach((layer,x)=>{let y=0;for(const task of layer){positions.set(task.id,savedPositions[task.id] || {x:x*270,y});const ports=taskPorts(task);y+=240+24*(ports.inputs.length+ports.outputs.length)+(options.outputThumbnail && pictures(task).length?130:0);}});}
    arrange(remembered?.positions);
    if(remembered)camera={...remembered.camera};
    function remember(){if(key){canvasViews.delete(key);canvasViews.set(key,{camera:{...camera},positions:Object.fromEntries(positions),wireStyle,inspectorTabs,inspectorScroll});if(canvasViews.size>30)canvasViews.delete(canvasViews.keys().next().value);}}
    function paint(){
      world.style.transform=`translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`;
      // Decorative world-aligned grid. Thin it by powers of two at low zoom,
      // retaining the same origin without adding hit targets or snapping.
      const stride=24*Math.pow(2,Math.max(0,Math.ceil(Math.log2(14/(24*camera.scale)))));
      const spacing=stride*camera.scale,radius=Math.max(.65,.85*camera.scale);
      map.style.backgroundImage=`radial-gradient(circle, rgba(116,128,148,.25) ${radius}px, transparent ${radius+.25}px)`;
      map.style.backgroundSize=`${spacing}px ${spacing}px`;
      map.style.backgroundPosition=`${camera.x-spacing/2}px ${camera.y-spacing/2}px`;
      zoom.textContent=Math.round(camera.scale*100)+'%';
    }
    function zoomAt(scale,x=map.clientWidth/2,y=map.clientHeight/2){const next=Math.min(1.8,Math.max(.25,scale)),ratio=next/camera.scale;camera={x:x-(x-camera.x)*ratio,y:y-(y-camera.y)*ratio,scale:next};paint();remember();}
    function fit(readable=false){
      if(!tasks.length || !map.clientWidth || !map.clientHeight)return;fitted=true;
      const ps=[...positions.values()],left=Math.min(...ps.map(p=>p.x)),top=Math.min(...ps.map(p=>p.y));
      const width=Math.max(...tasks.map(t=>positions.get(t.id).x+174))-left;
      const height=Math.max(...tasks.map(t=>positions.get(t.id).y+(cards.get(t.id)?.offsetHeight || 180)))-top;
      camera.scale=Math.min(1,Math.max(.25,Math.min((map.clientWidth-100)/width,(map.clientHeight-230)/height)));
      camera.x=(map.clientWidth-width*camera.scale)/2-left*camera.scale;camera.y=Math.max(145,(map.clientHeight-height*camera.scale)/2)-top*camera.scale;
      if(readable && camera.scale<.65)camera={scale:.8,x:30-left*.8,y:165-top*.8};
      paint();remember();
    }
    const tools=node('div',undefined,'canvas-tools');tools.setAttribute('aria-label','Canvas controls');
    const zoom=node('span','100%','canvas-zoom');
    tools.append(button('−',()=>zoomAt(camera.scale/1.2),'quiet'),zoom,button('+',()=>zoomAt(camera.scale*1.2),'quiet'),button('Fit',()=>fit(),'quiet'),button('Reset layout',()=>{arrange();positionCards();fit();},'quiet canvas-reset'));
    const wireSelect=node('select');wireSelect.setAttribute('aria-label','Wire style');
    for(const [value,label] of [['bezier','Curved'],['straight','Straight']]){const option=node('option',label);option.value=value;wireSelect.append(option);}
    wireSelect.value=wireStyle;wireSelect.onchange=()=>{wireStyle=wireSelect.value;draw();remember();};tools.append(wireSelect);
    tools.children[0].setAttribute('aria-label','Zoom out');tools.children[2].setAttribute('aria-label','Zoom in');
    const legend=node('p',options.legend || 'Solid: file binding · Dashed: prerequisite','canvas-legend');
    function positionCards(){for(const [id,card] of cards){const p=positions.get(id);card.style.left=p.x+'px';card.style.top=p.y+'px';}draw();remember();}
    function draw(){
      svg.replaceChildren();
      for(const edge of canvasEdges(tasks)){
        const a=positions.get(edge.from),b=positions.get(edge.to);if(!a || !b)continue;
        const fromRow=portRows.get(edge.from)?.outputs.get(edge.output),toRow=portRows.get(edge.to)?.inputs.get(edge.input);
        const x1=a.x+174,y1=a.y+(fromRow ? fromRow.offsetTop+fromRow.offsetHeight/2 : 35),x2=b.x,y2=b.y+(toRow ? toRow.offsetTop+toRow.offsetHeight/2 : 35);
        const midpoint=(x1+x2)/2,path=document.createElementNS('http://www.w3.org/2000/svg','path');
        path.setAttribute('d',wireStyle==='straight' ? `M ${x1} ${y1} L ${x2} ${y2}` : `M ${x1} ${y1} C ${midpoint} ${y1}, ${midpoint} ${y2}, ${x2} ${y2}`);
        if(edge.kind==='dependency')path.setAttribute('stroke-dasharray','5 5');
        svg.append(path);
      }
    }
    function startDrag(event,id=null){if(event.button!==0)return;suppressClick=false;dragging={id,startX:event.clientX,startY:event.clientY,origin:{...(id?positions.get(id):camera)},moved:false};}
    map.onpointerdown=event=>{if(event.target===map || event.target===world)startDrag(event);};
    map.onpointermove=event=>{if(!dragging)return;const dx=event.clientX-dragging.startX,dy=event.clientY-dragging.startY;dragging.moved ||= Math.abs(dx)+Math.abs(dy)>4;if(!dragging.moved)return;map.setPointerCapture(event.pointerId);
      if(dragging.id){positions.set(dragging.id,{x:dragging.origin.x+dx/camera.scale,y:dragging.origin.y+dy/camera.scale});positionCards();}
      else{camera.x=dragging.origin.x+dx;camera.y=dragging.origin.y+dy;paint();}};
    function endDrag(event){if(!dragging)return;suppressClick=dragging.moved;dragging=null;if(map.hasPointerCapture(event.pointerId))map.releasePointerCapture(event.pointerId);remember();}
    map.onpointerup=endDrag;map.onpointercancel=endDrag;
    map.addEventListener('wheel',event=>{event.preventDefault();const r=map.getBoundingClientRect();if(event.ctrlKey || event.metaKey)zoomAt(camera.scale*Math.exp(-event.deltaY*.005),event.clientX-r.left,event.clientY-r.top);else{camera.x-=event.deltaX;camera.y-=event.deltaY;paint();remember();}},{passive:false});
    map.onkeydown=event=>{if(event.target!==map)return;const moves={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]};if(moves[event.key]){event.preventDefault();camera.x+=moves[event.key][0];camera.y+=moves[event.key][1];paint();remember();}else if(event.key==='0'){event.preventDefault();fit();}};
    let disposeResults=()=>{};
    inspector.addEventListener('scroll',()=>{if(selected){inspectorScroll[selected.id]=inspector.scrollTop;remember();}});
    function choose(task,reveal=true) {
      if(selected && inspector.dataset.step)inspectorScroll[selected.id]=inspector.scrollTop;
      inspector.dataset.step=task.id;
      requestAnimationFrame(()=>{if(!disposed && selected?.id===task.id)inspector.scrollTop=inspectorScroll[task.id] || 0;});
      disposeResults();disposeResults=()=>{};
      selected = task; select(task.id,{reveal});if(reveal)inspector.hidden=false;
      for (const [id,b] of buttons) {b.setAttribute('aria-pressed',String(id === task.id));cards.get(id).setAttribute('data-selected',String(id===task.id));}
      const close=button('×',()=>{const origin=buttons.get(selected?.id);inspector.replaceChildren(node('h3','Inspector'),node('p','Select a node to inspect its saved inputs, outputs and status.','hint'));inspector.hidden=true;selected=null;select(null);buttons.forEach(b=>b.setAttribute('aria-pressed','false'));cards.forEach(c=>c.setAttribute('data-selected','false'));origin?.focus();},'quiet');
      close.setAttribute('aria-label','Close inspector');
      const heading=node('div',undefined,'section-title');heading.append(node('h3',stepLabel(task)));panelWidth(inspector,heading,key+':inspector','Results',{button});heading.append(close);
      inspector.replaceChildren(heading,node('p',statusText(task),'definition-badge'));
      if(options.inspect){options.inspect(task,inspector);return;}
      for(const change of revisionsFor(task))inspector.append(options.changeLink(change,change.label));
      for(const change of changesFor(task))inspector.append(options.changeLink(change,'Earlier source version · '+change.old.path));
      if(task.stage_id)inspector.append(node('p','Stage: '+task.stage_id,'hint'));
      if (task.error) inspector.append(node('p',task.error,'feedback error'));
      if (task.review_of) inspector.append(node('p','Checks: '+(tasks.find(t=>t.id===task.review_of)?.objective || task.review_of),'hint'));
      if (task.quality_review) inspector.append(saved('Recorded review concerns',task.quality_review));
      const tabbar=node('div',undefined,'inspector-tabs'),inputPane=node('div'),resultPane=node('div');
      const showTab=name=>{inputPane.hidden=name!=='inputs';resultPane.hidden=name!=='results';inputTab.setAttribute('aria-pressed',String(name==='inputs'));resultTab.setAttribute('aria-pressed',String(name==='results'));inspectorTabs[task.id]=name;remember();};
      const inputTab=button('Inputs',()=>showTab('inputs'),'quiet'),resultTab=button('Results',()=>showTab('results'),'quiet');
      tabbar.append(inputTab,resultTab);inspector.append(tabbar,inputPane,resultPane);showTab(inspectorTabs[task.id] || 'results');
      const conversational=options.conversationView && (task.id.startsWith('conversation:') || task.id.startsWith('read:') || task.conversation_response);
      const inputs = node('div'); inputs.append(node('h4',task.latest_attempt ? 'Inputs' : 'Planned inputs'));
      if(promptValue(task))inputs.append(node('h4','Prompt'),node('p',promptValue(task),'workflow-instruction'));
      const rows = task.latest_attempt ? task.recorded_inputs || [] : task.planned_inputs || [];
      for (const input of rows) {
        if (input.file) inputs.append(outputFile({...input.file,purpose:input.purpose}));
        else inputs.append(node('p',[input.path,input.from_task ? 'from '+(tasks.find(t=>t.id===input.from_task)?.objective || input.from_task) : '',task.latest_attempt ? 'Saved file unavailable' : 'Planned file'].filter(Boolean).join(' · '),'path'));
      }
      if (!rows.length && !promptValue(task)) inputs.append(node('p',task.latest_attempt ? 'No input versions recorded for this attempt.' : 'No declared inputs.','hint'));
      if(!conversational)inputPane.append(inputs);
      const current = (view.latest_outputs || []).filter(f => f.task === task.id), historical = (view.historical_outputs || []).filter(f => f.task === task.id);
      if(!options.renderResults)for (const file of current.filter(f=>f.result_role!=='technical')) resultPane.append(outputFile(file,view.output_texts));
      if(conversational){
        if(task.id.startsWith('read:'))inspector.append(node('p',task.objective));
        else inspector.append(button('Open saved answer',()=>options.openConversation(task),'quiet'));
      }else if (!current.length) resultPane.append(node('p',historical.length ? 'Outputs from this attempt are retained, not current.' : 'No current outputs recorded.','hint'));
      if (historical.length && !options.renderResults) { const old=saved('Retained outputs — not current',''); old.querySelector('pre').remove(); historical.forEach(f=>old.append(outputFile(f))); resultPane.append(old); }

      const details=saved('Technical details','');details.querySelector('pre').remove();
      for(const file of current.filter(f=>f.result_role==='technical'))details.append(outputFile(file,view.output_texts));
      details.append(node('p',toolLabel(task),'hint'),node('p',`${task.attempts || 0}/${task.max_attempts || '—'} attempts`,'hint'),node('p',task.instruction || 'No instruction recorded.','workflow-instruction'));
      details.append(saved('Full objective',task.objective || task.id));
      if(task.planned_outputs?.length)details.append(saved('Output definitions',task.planned_outputs));
      if(task.user_gate)details.append(saved('Decision scope',task.user_gate));
      details.append(saved('Input records',rows));
      details.append(saved('Output records',{current,previous:historical}));
      if (task.review_target) details.append(saved('Exact review target',task.review_target));
      if (task.activity) details.append(saved('Recorded activity',task.activity));
      details.append(saved('Saved identity',{step:task.id,attempt:task.latest_attempt || null,attempt_state:task.attempt_state || null,output_is_current:task.output_is_current || false,run:task.run || view.name,original_step:task.original_id || task.id}));inspector.append(details);
      disposeResults=options.renderResults?.(task,resultPane,current,historical) || (()=>{});
      options.afterInspect?.(task,inspector,{inputPane,resultPane});
    }
    function statusText(task){
      return ({running:'Running',launching:'Starting',settling:'Finishing',cancelling:'Stopping',queued:task.runnable?'Queued':'Waiting for inputs',draft:'Not run',uncertain:'Needs attention · outcome unknown',blocked:'Blocked',completed:'Completed'})[task.status] || stateLabel(task.status);
    }
    const executionBusy=!!view.executing_runs?.length || tasks.some(t=>['queued','running','launching','settling','cancelling'].includes(t.status));
    for(const task of tasks){
      const card=node('div',undefined,'workflow-node');cards.set(task.id,card);card.dataset.task=task.id;
      const active=['running','launching','settling','cancelling'].includes(task.status);
      card.setAttribute('data-execution-state',task.status || 'draft');
      card.setAttribute('aria-busy',String(active));
      const b=button('',()=>{if(suppressClick){suppressClick=false;return;}choose(task);},'workflow-step');
      b.setAttribute('aria-pressed',String(task.id===selected?.id));b.title=task.objective || task.id;
      const glyph=node('span',undefined,'canvas-node-icon');glyph.append(operationIcon(task));
      const title=node('span',undefined,'canvas-node-title');title.append(node('strong',stepLabel(task)),node('small',task.execution?.capability || task.operation || (task.review_of?'Review':'AI task')));b.append(glyph,title);
      b.onpointerdown=event=>startDrag(event,task.id);buttons.set(task.id,b);card.append(b);
      const state=node('div',undefined,'canvas-node-state'+(active?' active':''));
      state.setAttribute('role','status');state.setAttribute('aria-live','polite');
      if(active){const spinner=node('span',undefined,'node-spinner');spinner.setAttribute('aria-hidden','true');state.append(spinner);}
      state.append(node('span',statusText(task)));card.append(state);
      if(['blocked','uncertain'].includes(task.status) && task.error){
        const failure=node('div',task.error,'canvas-node-error');failure.title=task.error;
        card.append(failure);
      }
      if(modelLabel(task))card.append(node('div',modelLabel(task),'canvas-model'));
      if(task.outdated)card.append(node('div','Result from an earlier prompt or input','canvas-attempts'));
      if(task.reused_source)card.append(node('div','Saved result · will not rerun','canvas-attempts'));
      if(Number.isInteger(task.attempts))card.append(node('div',`${task.attempts}/${task.max_attempts ?? '—'} attempts`,'canvas-attempts'));
      if(promptValue(task)){
        const prompt=node('div',undefined,'canvas-prompt');prompt.title=promptValue(task);
        prompt.append(node('small','Prompt'),node('span',promptValue(task)));card.append(prompt);
      }
      const ports=taskPorts(task), rows={inputs:new Map(),outputs:new Map()};portRows.set(task.id,rows);
      for(const kind of ['inputs','outputs'])for(const port of ports[kind]){
        const row=node('div',undefined,'canvas-port '+kind);row.title=port.label;
        row.append(node('span','', 'canvas-port-dot'),node('span',port.label,'canvas-port-label'));
        if(kind==='outputs' && options.openOutput){
          // Named editor ports and executed file paths are distinct identities.
          // Never guess by basename, label, extension, or a historical version.
          const matches=(view.latest_outputs || []).filter(f=>f.task===task.id && f.id && f.sha256 &&
            (port.output_port?f.output_port===port.output_port:f.path===port.id));
          if(matches.length===1){
            const file=matches[0],open=button('↗',async event=>{
              event?.stopPropagation();event?.preventDefault();open.disabled=true;
              try{await options.openOutput(file,open);open.title=label;}
              catch(error){open.title=String(error);open.setAttribute('aria-label',String(error));}
              finally{open.disabled=false;}
            },'canvas-output-open');
            const label=file.open_with?`Open ${port.label} in ${file.open_with}`:`Open ${port.label}`;
            open.title=label;open.setAttribute('aria-label',label);
            open.onpointerdown=event=>event.stopPropagation();row.append(open);
          }
        }
        rows[kind].set(port.id,row);card.append(row);
      }
      if(options.outputThumbnail && pictures(task).length){
        const strip=node('div',undefined,'canvas-image-strip');
        strip.setAttribute('aria-label','Saved image outputs');
        for(const file of pictures(task)){const thumb=options.outputThumbnail(file);thumbnails.push(thumb);strip.append(thumb);}
        card.append(strip);
      }
      if(options.runNode && !task.reused_source){
        const blocked=executionBusy || (tasks.some(t=>t.status==='uncertain') && !task.can_start_new_attempt);
        const controls=node('div',undefined,'canvas-node-controls');
        const confirmation=node('div',undefined,'canvas-node-confirmation');
        confirmation.setAttribute('aria-label','Run '+stepLabel(task)+' confirmation');
        const reset=()=>{confirmation.replaceChildren();run.disabled=blocked;};
        const run=button(active?statusText(task):'▶ Run',async()=>{
          if(run.disabled)return;
          run.disabled=true;choose(task,false);
          try{await options.runNode(task,confirmation,reset);}
          catch(e){confirmation.replaceChildren(node('p',String(e),'feedback error'),button('Close',reset,'quiet'));}
        },'canvas-node-run');
        run.setAttribute('aria-label','Run '+stepLabel(task));run.disabled=blocked;
        if(blocked)run.title=tasks.some(t=>t.status==='uncertain')?'Outcome unknown. Run an eligible stopped node separately to confirm a new attempt.':'Wait for the current execution to finish.';
        else if(task.can_start_new_attempt)run.title='Review and confirm a separate new attempt. The previous outcome stays unknown.';
        controls.append(run,confirmation);card.append(controls);
      }
      for(const change of revisionsFor(task))card.append(options.changeLink(change,change.label));
      for(const change of changesFor(task))card.append(options.changeLink(change,'Earlier source version'));world.append(card);
    }
    tools.hidden=!tasks.length;legend.hidden=!tasks.length;
    split.append(map,tools,legend,inspector);panel.append(split);container.append(panel);positionCards();paint();if(selected)choose(selected);
    const observer=new ResizeObserver(()=>{if(!fitted)fit(true);draw();});observer.observe(map);cards.forEach(card=>observer.observe(card));
    requestAnimationFrame(()=>{if(disposed)return;if(!remembered)fit(true);draw();});
    const dispose=()=>{if(selected){inspectorScroll[selected.id]=inspector.scrollTop;remember();}disposed=true;observer.disconnect();disposeResults();thumbnails.forEach(t=>t.disposeThumbnail?.());};dispose.showStep=id=>{const task=tasks.find(t=>t.id===id);if(task){options.reveal?.();choose(task);}};return dispose;
  }
  const renderKey=value=>JSON.stringify(value,function(key,item){return key==='captured_at' && Array.isArray(this.tasks) && typeof this.name==='string'?undefined:item;});
  const api={hostCodeReview,channelStatus,updateConnectionStatus,connectionIndicators,panelWidth,jobTitle,renderKey,icon,operationVisual,operationIcon,layout,toolLabel,resultFiles,taskPorts,canvasEdges,pipelineGraph,withCompletedSources,mount}; if(typeof module!=='undefined' && module.exports) module.exports=api; else root.RelayWorkflow=api;
})(typeof window==='undefined' ? {} : window);
