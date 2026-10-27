import {evidence} from './evidence.js';
import {connectCards} from './map-wires.js';
// Portable decision maps. Models supply bounded fragments, never source IDs,
// offsets, SVG, URLs or execution authority. Code binds every cited span.
export const KINDS=['context','requirement','attempt','finding','decision','proposal','question','next_action'];
export const STATUSES=['reported','proposed','rejected','superseded','unresolved'];
export const RELATIONS=['precedes','motivates','qualifies','contradicts','replaces','depends_on','supports'];
export const MAP_INSTRUCTIONS=`At the TOP LEVEL, beside skill_candidates and work_changes (not inside a Work item), also return work_graph: {"nodes":[{"key":"n1","kind":"attempt","label":"Short statement","status":"reported","source_ref":"e0001"}],"edges":[{"from":"n1","to":"n2","relation":"qualifies","source_ref":"e0002"}]}. Prefer 8–20 pivotal nodes and at most 24 connections, not a row-by-row transcription. Retain the important qualifications and failed branches; the full source is kept separately. Hard maximum: 80 nodes and 120 edges. Node kinds: ${KINDS.join(', ')}. Status: ${STATUSES.join(', ')}. Relationships: ${RELATIONS.join(', ')}. Use precedes from the earlier step to the later step, never the reverse. A rejected alternative branch is not automatically a contradiction. Use qualifies from a qualification to the claim it limits; replaces from the newer approach to the older one; depends_on from the dependent to its prerequisite. Use only IDs from source_units. Select the unit supporting each statement or connection; code will extract its literal text. Do not copy, paraphrase or invent quotations. Source-unit IDs are local to this request. Keep similar version names on different branches distinct. Preserve failed attempts and changes in validation; a reported result is not independently verified. Future designs remain proposed, even if a section calls them agreed. Do not infer causation from chronology, approval from a suggestion, or implementation from a plan. Omit unsupported relationships. Do not generate new source IDs, offsets or drawing code. An empty graph is allowed when no supported statements exist.`;
const text=(s,n=4000)=>{if(typeof s!=='string'||!s.trim()||s.length>n)throw Error('Invalid map text');return s;};
function fields(value,keys){if(!value||Array.isArray(value)||Object.keys(value).sort().join('|')!==keys.slice().sort().join('|'))throw Error('Unexpected map fields');}
export function validateFragment(content,fragment){
  fields(fragment,['nodes','edges']);
  if(!Array.isArray(fragment.nodes)||fragment.nodes.length>80||!Array.isArray(fragment.edges)||fragment.edges.length>120)throw Error('Map exceeds 80 nodes or 120 connections');
  const keys=new Set();
  for(const n of fragment.nodes){fields(n,['key','kind','label','status',Object.hasOwn(n,'source_ref')?'source_ref':'quote']);if(!/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(n.key)||keys.has(n.key))throw Error('Duplicate or invalid map node key');keys.add(n.key);text(n.label,320);if(!KINDS.includes(n.kind)||!STATUSES.includes(n.status))throw Error('Invalid map kind or status');if(['proposal','next_action'].includes(n.kind)&&!['proposed','unresolved'].includes(n.status))throw Error('A proposed action cannot be reported as completed');evidence(content,n);}
  const edges=new Set();
  for(const e of fragment.edges){fields(e,['from','to','relation',Object.hasOwn(e,'source_ref')?'source_ref':'quote']);if(!keys.has(e.from)||!keys.has(e.to)||e.from===e.to||!RELATIONS.includes(e.relation))throw Error('Invalid map connection');const identity=JSON.stringify([e.from,e.to,e.relation]);if(edges.has(identity))throw Error('Duplicate map connection');edges.add(identity);evidence(content,e);}
  return structuredClone(fragment);
}
async function sha(s){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))].map(v=>v.toString(16).padStart(2,'0')).join('');}
export async function createMap(capture,parts){
  const content=capture.selected_content??capture.extracted_content;
  const digest=await sha(content),sourceId='source-'+digest;
  const source={id:sourceId,sha256:digest,title:capture.title,url:capture.url||null,content,captured_at:capture.source_metadata.captured_at,limitations:capture.source_metadata.limitations||[]};
  const nodes=new Map(),edges=new Map();
  for(const part of parts){
    if(!Number.isInteger(part.start)||!Number.isInteger(part.end)||part.start<0||part.end>content.length||part.end<=part.start)throw Error('Invalid map source bounds');
    const body=content.slice(part.start,part.end),fragment=validateFragment(body,part.fragment),keys=new Map();
    const bind=row=>{const local=evidence(body,row);return {source_id:sourceId,start:part.start+local.start,end:part.start+local.end,quote:local.quote};};
    for(const n of fragment.nodes){const ev=bind(n),id='node-'+await sha(JSON.stringify([sourceId,ev.start,ev.end,n.kind,n.label]));keys.set(n.key,id);const item={id,kind:n.kind,identity_label:n.label,label:n.label,status:n.status,evidence:ev};
      if(nodes.has(id)&&(nodes.get(id).label!==n.label||nodes.get(id).status!==n.status))throw Error('Overlapping map fragments disagree. Review the conflicting response; neither interpretation was discarded.');nodes.set(id,item);}
    for(const e of fragment.edges){const from=keys.get(e.from),to=keys.get(e.to),ev=bind(e),id='edge-'+await sha(JSON.stringify([from,to,e.relation,ev.start,ev.end]));edges.set(id,{id,from,to,relation:e.relation,evidence:ev});}
  }
  if(nodes.size>240||edges.size>360)throw Error('Combined map exceeds 240 nodes or 360 connections. Keep this work in smaller maps.');
  return {format:'task-relay-map',format_version:1,title:capture.title,sources:[source],nodes:[...nodes.values()],edges:[...edges.values()],coverage:{characters:content.length,parts:parts.length,scope:'Supplied text only; not a complete-chat claim.',cross_part_relations:parts.length>1?'Only explicitly extracted connections; cross-part relationships may be missing.':null}};
}
export async function validateMap(map){
  fields(map,['format','format_version','title','sources','nodes','edges','coverage']);text(map.title,1000);
  if(map.format!=='task-relay-map'||map.format_version!==1||!Array.isArray(map.sources)||map.sources.length!==1||!Array.isArray(map.nodes)||map.nodes.length>240||!Array.isArray(map.edges)||map.edges.length>360)throw Error('Invalid portable map');
  const s=map.sources[0];fields(s,['id','sha256','title','url','content','captured_at','limitations']);text(s.content,300000);text(s.title,1000);if(!Number.isFinite(Date.parse(s.captured_at))||!Array.isArray(s.limitations)||s.limitations.length>20||s.limitations.some(x=>typeof x!=='string'||x.length>2000))throw Error('Invalid map source metadata');
  if(s.url!==null){const u=new URL(s.url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw Error('Invalid map source URL');}
  const hash=await sha(s.content);if(hash!==s.sha256||s.id!=='source-'+hash)throw Error('Map source checksum does not match');
  fields(map.coverage,['characters','parts','scope','cross_part_relations']);if(map.coverage.characters!==s.content.length||!Number.isInteger(map.coverage.parts)||map.coverage.parts<1||map.coverage.parts>40)throw Error('Invalid map coverage');text(map.coverage.scope,500);if(map.coverage.cross_part_relations!==null)text(map.coverage.cross_part_relations,500);
  const evidence=ev=>{fields(ev,['source_id','start','end','quote']);if(ev.source_id!==s.id||!Number.isInteger(ev.start)||!Number.isInteger(ev.end)||ev.start<0||ev.end<=ev.start||ev.end>s.content.length||s.content.slice(ev.start,ev.end)!==ev.quote)throw Error('Map evidence binding was changed');text(ev.quote);};
  const keys=new Set();
  for(const n of map.nodes){fields(n,['id','kind','identity_label','label','status','evidence']);text(n.label,320);text(n.identity_label,320);evidence(n.evidence);if(!KINDS.includes(n.kind)||!STATUSES.includes(n.status)||(['proposal','next_action'].includes(n.kind)&&!['proposed','unresolved'].includes(n.status)))throw Error('Invalid map node');const id='node-'+await sha(JSON.stringify([s.id,n.evidence.start,n.evidence.end,n.kind,n.identity_label]));if(id!==n.id||keys.has(id))throw Error('Invalid map node identity');keys.add(id);}
  const edgeKeys=new Set();for(const e of map.edges){fields(e,['id','from','to','relation','evidence']);evidence(e.evidence);if(!keys.has(e.from)||!keys.has(e.to)||e.from===e.to||!RELATIONS.includes(e.relation))throw Error('Invalid map edge');const id='edge-'+await sha(JSON.stringify([e.from,e.to,e.relation,e.evidence.start,e.evidence.end]));if(id!==e.id||edgeKeys.has(id))throw Error('Invalid map edge identity');edgeKeys.add(id);}
  return structuredClone(map);
}
export async function reverseChronology(map,edgeId){
  const revised=await validateMap(map),edge=revised.edges.find(row=>row.id===edgeId);
  if(!edge||edge.relation!=='precedes')throw Error('Choose one chronology connection to reverse.');
  const before=structuredClone(edge);[edge.from,edge.to]=[edge.to,edge.from];
  edge.id='edge-'+await sha(JSON.stringify([edge.from,edge.to,edge.relation,edge.evidence.start,edge.evidence.end]));
  await validateMap(revised);
  return {map:revised,receipt:{action:'reverse_chronology',at:new Date().toISOString(),source_sha256:map.sources[0].sha256,before,after:structuredClone(edge)}};
}
export function mapFromMarkdown(content){const blocks=[...content.matchAll(/^```task-relay-map\r?\n([\s\S]*?)\r?\n```[ \t]*$/gm)];if(!blocks.length)return null;if(blocks.length!==1)throw Error('Several maps in this file. Select one saved work file.');try{return JSON.parse(blocks[0][1]);}catch{throw Error('The saved map is incomplete');}}
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
function lines(s,width=38){const words=s.split(/\s+/),out=[];let line='';for(const word of words){if(line&&line.length+word.length+1>width){out.push(line);line='';}line+=(line?' ':'')+word;}if(line)out.push(line);return out.slice(0,3).map((l,i)=>i===2&&out.length>3?l.slice(0,width-3)+'…':l);}
export function layout(map){
  // Explicit chronology orders the progression; source order breaks ties.
  // Citation position alone is not chronology (a recap may repeat an early
  // Mermaid overview before its detailed experiment audit).
  const ordered=map.nodes.map((n,i)=>({...n,order:i})).sort((a,b)=>a.evidence.start-b.evidence.start||a.order-b.order);
  const sequence=new Set(map.edges.filter(e=>e.relation==='precedes').flatMap(e=>[e.from,e.to]));
  let main=ordered.filter(n=>!['rejected','superseded'].includes(n.status)&&(sequence.has(n.id)||['context','attempt','decision','proposal','next_action'].includes(n.kind)));
  if(!main.length)main=ordered.filter(n=>!map.edges.some(e=>e.from===n.id&&['qualifies','contradicts'].includes(e.relation)));
  if(!main.length)main=ordered.slice();
  const pending=main.slice(),sorted=[],remaining=new Set(main.map(n=>n.id)),indegree=new Map(main.map(n=>[n.id,0])),outgoing=new Map(main.map(n=>[n.id,[]]));let chronologyCycle=false;
  for(const e of map.edges)if(e.relation==='precedes'&&remaining.has(e.from)&&remaining.has(e.to)){indegree.set(e.to,indegree.get(e.to)+1);outgoing.get(e.from).push(e.to);}
  while(pending.length){let index=pending.findIndex(n=>indegree.get(n.id)===0);if(index<0){chronologyCycle=true;index=0;}const [next]=pending.splice(index,1);sorted.push(next);remaining.delete(next.id);for(const to of outgoing.get(next.id))if(remaining.has(to))indegree.set(to,indegree.get(to)-1);}main=sorted;
  const mainIndex=new Map(main.map((n,i)=>[n.id,i])),groups=main.map(()=>[]);
  for(const n of ordered.filter(n=>!mainIndex.has(n.id))){
    const related=map.edges.flatMap(e=>e.from===n.id&&mainIndex.has(e.to)?[{id:e.to,priority:['qualifies','contradicts','depends_on'].includes(e.relation)?0:1}]:e.to===n.id&&mainIndex.has(e.from)?[{id:e.from,priority:1}]:[]);
    related.sort((a,b)=>a.priority-b.priority||Math.abs(main[mainIndex.get(a.id)].evidence.start-n.evidence.start)-Math.abs(main[mainIndex.get(b.id)].evidence.start-n.evidence.start)||mainIndex.get(a.id)-mainIndex.get(b.id));
    const index=related.length?mainIndex.get(related[0].id):main.reduce((best,row,i)=>Math.abs(row.evidence.start-n.evidence.start)<Math.abs(main[best].evidence.start-n.evidence.start)?i:best,0);
    groups[index].push(n);
  }
  const positions=new Map();
  main.forEach((n,i)=>{const x=72+i*440;positions.set(n.id,{x,y:100,width:320,height:128,lane:0});groups[i].forEach((side,j)=>positions.set(side.id,{x,y:340+j*190,width:320,height:128,lane:1}));});
  return {ordered,positions,width:Math.max(900,main.length*440+24),height:Math.max(420,Math.max(0,...groups.map(g=>g.length))*190+340),chronologyCycle};
}
export function svg(map){
  const {ordered,positions,width,height}=layout(map);
  const edgeMarkup=map.edges.map((e,i)=>{
    const a=positions.get(e.from),b=positions.get(e.to),same=a.lane===b.lane,forward=b.x>a.x;
    let path,lx,ly;
    if(same&&forward&&b.x-a.x<=460){const x1=a.x+a.width,x2=b.x,y=a.y+64;path=`M ${x1} ${y} C ${x1+42} ${y}, ${x2-42} ${y}, ${x2} ${y}`;lx=(x1+x2)/2;ly=y-13;}
    else if(a.x===b.x&&Math.abs(a.y-b.y)<=300){const x=a.x+160,down=b.y>a.y,y1=a.y+(down?a.height:0),y2=b.y+(down?0:b.height);path=`M ${x} ${y1} C ${x} ${(y1+y2)/2}, ${x} ${(y1+y2)/2}, ${x} ${y2}`;lx=x+12;ly=(y1+y2)/2;}
    else if(same){const x1=a.x+160,x2=b.x+160,rail=a.lane?height-28-(i%3)*14:68-(i%3)*16,y1=a.y+(a.lane?a.height:0),y2=b.y+(b.lane?b.height:0),sign=a.lane?1:-1;path=`M ${x1} ${y1} C ${x1} ${rail}, ${x1} ${rail}, ${x1+(forward?24:-24)} ${rail} L ${x2+(forward?-24:24)} ${rail} C ${x2} ${rail}, ${x2} ${rail}, ${x2} ${y2}`;lx=(x1+x2)/2;ly=rail+sign*13;}
    else{const x1=a.x+160,x2=b.x+160,y1=a.y+(a.lane?0:a.height),y2=b.y+(b.lane?0:b.height),rail=262+(i%3)*18;path=`M ${x1} ${y1} C ${x1} ${rail}, ${x1} ${rail}, ${x1+(forward?24:-24)} ${rail} L ${x2+(forward?-24:24)} ${rail} C ${x2} ${rail}, ${x2} ${rail}, ${x2} ${y2}`;lx=(x1+x2)/2;ly=rail-10;}
    const label=e.relation.replaceAll('_',' '),color=e.relation==='precedes'?'#8796fb':['qualifies','contradicts'].includes(e.relation)?'#92a3c7':'#a8b4ce',labelWidth=label.length*6+16;
    return `<g data-edge-from="${e.from}" data-edge-to="${e.to}"><path d="${path}" fill="none" stroke="${color}" stroke-width="1.8" marker-end="url(#arrow)"><title>${escape(label)}: ${escape(e.evidence.quote)}</title></path><rect x="${lx-labelWidth/2}" y="${ly-10}" width="${labelWidth}" height="20" rx="10" fill="#fff" stroke="#e2e7f1"/><text x="${lx}" y="${ly+3}" text-anchor="middle" font-size="10" fill="#596982">${escape(label)}</text></g>`;
  }).join('');
  const statusColor={reported:'#536bc0',proposed:'#9b710e',rejected:'#ac5353',superseded:'#79669b',unresolved:'#9b710e'};
  const nodesMarkup=ordered.slice().sort((a,b)=>positions.get(a.id).x-positions.get(b.id).x||positions.get(a.id).y-positions.get(b.id).y).map(n=>{const p=positions.get(n.id);return `<g data-node-id="${n.id}" tabindex="0" role="button" aria-label="${escape(n.kind+': '+n.label+' ('+n.status+')')}" transform="translate(${p.x} ${p.y})"><title>${escape(n.label)}</title><rect class="node-body" width="320" height="128" rx="9" fill="#fff" stroke="#d6deec" filter="url(#node-shadow)"/><text x="15" y="23" font-size="10" font-weight="600" letter-spacing=".5" fill="#6275a5">${escape(n.kind.replaceAll('_',' ').toUpperCase())}</text><text x="15" y="48" font-size="13" font-weight="500" fill="#25303e">${lines(n.label).map((l,j)=>`<tspan x="15" dy="${j?18:0}">${escape(l)}</tspan>`).join('')}</text><text x="15" y="112" font-size="10" fill="${statusColor[n.status]}">${escape(n.status)}</text></g>`;}).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="group" aria-label="${escape(map.title+' — decision map')}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif"><title>${escape(map.title)}</title><desc>Extracted interpretations, not verified results. Select a node to inspect its source. ${escape(map.coverage.scope)}</desc><defs><pattern id="canvas-dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#dce3f0"/></pattern><filter id="node-shadow" x="-10%" y="-15%" width="120%" height="135%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#25303e" flood-opacity=".05"/></filter><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 1 1 L 9 5 L 1 9" fill="none" stroke="#8796fb" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs><style>[data-node-id]{cursor:pointer;outline:none}[data-node-id]:hover .node-body,[data-node-id]:focus .node-body,[data-selected="true"] .node-body{stroke:#253de8;stroke-width:2}</style><rect width="100%" height="100%" fill="#fafbff"/><rect width="100%" height="100%" fill="url(#canvas-dots)"/>${edgeMarkup}${nodesMarkup}</svg>`;
}
// A reversible view projection, not new work state or semantic model output.
// Keep branches with their chronology anchor; never turn adjacency into an edge.
export function groupPhases(map){
  const view=layout(map),anchors=map.nodes.filter(n=>view.positions.get(n.id).lane===0).sort((a,b)=>view.positions.get(a.id).x-view.positions.get(b.id).x);
  if(!anchors.length)return {phases:[],connections:[],chronologyCycle:view.chronologyCycle};
  let proposedStart=anchors.length;
  while(proposedStart>0&&['proposal','next_action'].includes(anchors[proposedStart-1].kind))proposedStart--;
  const hasProposal=proposedStart>0&&proposedStart<anchors.length;
  const count=Math.min(5,Math.max(1,Math.ceil((hasProposal?proposedStart:anchors.length)/4))),chunks=[];
  let cursor=0;const end=hasProposal?proposedStart:anchors.length;
  for(let i=0;i<count;i++){const size=Math.ceil((end-cursor)/(count-i));chunks.push(anchors.slice(cursor,cursor+size));cursor+=size;}
  if(hasProposal)chunks.push(anchors.slice(proposedStart));
  const membership=new Map(),phases=chunks.map((chunk,i)=>{
    const columns=new Set(chunk.map(n=>view.positions.get(n.id).x)),nodes=map.nodes.filter(n=>columns.has(view.positions.get(n.id).x)).sort((a,b)=>view.positions.get(a.id).x-view.positions.get(b.id).x||view.positions.get(a.id).y-view.positions.get(b.id).y);
    const phase={id:'phase-'+chunk[0].id,index:i,title:chunk[0].label,nodes,proposed:chunk.every(n=>['proposal','next_action'].includes(n.kind))};
    for(const n of nodes)membership.set(n.id,phase.id);return phase;
  });
  const connections=new Map();
  for(const edge of map.edges){const from=membership.get(edge.from),to=membership.get(edge.to);if(from===to)continue;const key=JSON.stringify([from,to]);if(!connections.has(key))connections.set(key,{from,to,edges:[]});connections.get(key).edges.push(edge);}
  return {phases,connections:[...connections.values()],chronologyCycle:view.chronologyCycle};
}
let mapViewSequence=0;
export function renderMap(container,map,onEdit,state={mode:'overview',phase:null}){
  // Reserve the mounted workspace before replacing it. Otherwise a shorter
  // phase (or the temporarily empty host) clamps the document's scroll range.
  // This is view-local; opening a different map starts with a fresh height.
  container.style.minHeight=state.minHeight?state.minHeight+'px':'';
  container.replaceChildren();container.setAttribute('data-map-view','true');const doc=container.ownerDocument,make=(tag,content)=>{const el=doc.createElement(tag);if(content!==undefined)el.textContent=content;return el;};
  const refresh=()=>{const height=container.getBoundingClientRect?.().height||0;state.minHeight=Math.max(state.minHeight||0,height);renderMap(container,map,onEdit,state);},grouped=groupPhases(map),tools=make('div');tools.className='view-tabs map-modes';
  for(const [mode,label] of [['overview','Overview'],['full','Full graph']]){const b=make('button',label);b.type='button';b.setAttribute('aria-pressed',String(state.mode===mode));b.onclick=()=>{state.mode=mode;refresh();};tools.append(b);}
  container.append(tools);
  const summary=make('p',`${map.nodes.length} nodes · ${map.edges.length} connections · ${map.sources.length} supplied source${map.sources.length===1?'':'s'}`);summary.className='muted';container.append(summary);
  if(state.mode==='full'){const full=make('div');container.append(full);renderCanvas(full,map,onEdit,{sourceMap:map,refresh});return;}
  const hint=make('p','Expand a phase to see its nodes. Groups follow step order; titles come from existing nodes.');hint.className='muted';container.append(hint);
  if(grouped.chronologyCycle)container.append(make('p','Chronology links form a cycle. Review them in Full graph before relying on phase order.'));
  if(map.coverage.cross_part_relations)container.append(make('p',map.coverage.cross_part_relations));
  if(!grouped.phases.length){container.append(make('p','No supported nodes in this map.'));return;}
  const grid=make('div');grid.className='map-phases';grid.setAttribute('aria-label','Work phases');
  const detail=make('div');detail.className='map-phase-detail';detail.id='map-phase-detail-'+(++mapViewSequence);detail.setAttribute('data-phase-detail','true');
  const focusPhase=id=>container.querySelector('[data-phase-id="'+id+'"]')?.focus({preventScroll:true});
  for(const phase of grouped.phases){
    const card=make('button');card.type='button';card.className='map-phase';card.setAttribute('data-phase-id',phase.id);card.setAttribute('data-wire-id',phase.id);card.setAttribute('aria-expanded',String(state.phase===phase.id));card.setAttribute('aria-controls',detail.id);
    const caption=make('span',`PHASE ${phase.index+1}${phase.proposed?' · PROPOSED':''}`);caption.className='map-phase-caption';
    const title=make('strong',phase.title),counts=make('span',`${phase.nodes.length} nodes${phase.nodes.some(n=>['rejected','superseded','unresolved'].includes(n.status))?' · includes cautions':''}`);counts.className='muted';
    const links=make('span',state.phase===phase.id?'Collapse phase':'Expand phase');links.className='map-phase-links';
    card.append(caption,title,counts,links);card.onclick=()=>{state.phase=state.phase===phase.id?null:phase.id;refresh();focusPhase(phase.id);};grid.append(card);
  }
  container.append(grid,detail);
  connectCards(grid,grouped.connections.map(c=>({from:c.from,to:c.to,label:c.edges.length===1?c.edges[0].relation.replaceAll('_',' '):c.edges.length+' links',title:c.edges.map(e=>`${map.nodes.find(n=>n.id===e.from).label} → ${e.relation.replaceAll('_',' ')} → ${map.nodes.find(n=>n.id===e.to).label}`).join('\n')})));
  const phase=grouped.phases.find(p=>p.id===state.phase);if(!phase)return;
  detail.setAttribute('data-wire-id','expanded-'+phase.id);detail.setAttribute('data-expanded-phase',phase.id);detail.setAttribute('aria-label','Expanded phase '+(phase.index+1));detail.setAttribute('role','group');
  detail.append(make('h3',`Phase ${phase.index+1} · ${phase.title}`));
  const close=make('button','Collapse phase');close.type='button';close.className='quiet';close.onclick=()=>{state.phase=null;refresh();container.querySelector('[data-phase-id="'+phase.id+'"]')?.focus({preventScroll:true});};detail.append(close);
  const ids=new Set(phase.nodes.map(n=>n.id)),body=make('div');detail.append(body);
  renderCanvas(body,{...map,nodes:phase.nodes,edges:map.edges.filter(e=>ids.has(e.from)&&ids.has(e.to))},onEdit,{sourceMap:map,refresh,compact:true});
  const cross=grouped.connections.filter(c=>c.from===phase.id||c.to===phase.id);
  if(cross.length){const links=make('details');links.className='map-phase-connections';links.append(make('summary','Connections with other phases ('+cross.reduce((n,c)=>n+c.edges.length,0)+')'));
    for(const c of cross){const other=grouped.phases.find(p=>p.id===(c.from===phase.id?c.to:c.from));for(const edge of c.edges){const row=make('div'),jump=make('button',`${c.from===phase.id?'→':'←'} Phase ${other.index+1} · ${edge.relation.replaceAll('_',' ')}`);jump.type='button';jump.onclick=()=>{state.phase=other.id;refresh();focusPhase(other.id);};row.append(jump,make('p',map.nodes.find(n=>n.id===edge.from).label+' → '+map.nodes.find(n=>n.id===edge.to).label));links.append(row);}}detail.append(links);
  }
  // This wire denotes a view expansion, never an extracted relationship.
  connectCards(container,[{from:phase.id,to:'expanded-'+phase.id,expansion:true,label:'',title:'Expanded details for phase '+(phase.index+1)+': '+phase.title}]);
}
function renderCanvas(container,map,onEdit,{sourceMap=map,refresh=()=>renderMap(container,sourceMap,onEdit),compact=false}={}){
  container.replaceChildren();const doc=container.ownerDocument;
  const make=(tag,content)=>{const el=doc.createElement(tag);if(content!==undefined)el.textContent=content;return el;};
  const coverage=make('p',`${map.coverage.characters.toLocaleString()} supplied characters · interpretations, not verified results. Select a node for evidence.`);coverage.className='muted';container.append(coverage);
  if(map.coverage.cross_part_relations)container.append(make('p',map.coverage.cross_part_relations));
  const tools=make('div');tools.className='actions';const viewport=make('div');viewport.className='map-viewport';viewport.setAttribute('aria-label','Scrollable decision map');viewport.tabIndex=0;
  viewport.onpointerdown=event=>{if(event.button!==0||event.target.closest('[data-node-id]'))return;const start={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(event.pointerId);viewport.style.cursor='grabbing';viewport.onpointermove=move=>{viewport.scrollLeft=start.left-(move.clientX-start.x);viewport.scrollTop=start.top-(move.clientY-start.y);};const finish=()=>{viewport.onpointermove=null;viewport.style.cursor='';};viewport.onpointerup=finish;viewport.onpointercancel=finish;};
  const drawing=make('div');drawing.className=compact?'map-phase-nodes':'map-drawing';
  if(compact){const placed=layout(map),columns=[...new Set([...placed.positions.values()].map(p=>p.x))].sort((a,b)=>a-b);drawing.setAttribute('data-flow-columns',String(columns.length));for(const n of map.nodes){const p=placed.positions.get(n.id),b=make('button');b.type='button';b.className='map-detail-node';b.setAttribute('data-node-id',n.id);b.setAttribute('data-wire-id',n.id);b.setAttribute('data-flow-column',String(columns.indexOf(p.x)));b.setAttribute('data-flow-lane',String(p.lane?1+Math.round((p.y-340)/190):0));b.setAttribute('aria-label',n.label+' ('+n.status+')');const kind=make('span',n.kind.replaceAll('_',' ')+' · '+n.status);kind.className='map-phase-caption';b.append(kind,make('strong',n.label));drawing.append(b);}}
  else drawing.innerHTML=svg(map);viewport.append(drawing);const size=layout(map);let scale=Math.min(.9,Math.max(.4,((container.clientWidth||636)-6)/900));
  if(size.chronologyCycle)container.append(make('p','Chronology links form a cycle. Review the connections before relying on this order.'));
  const zoom=delta=>{if(compact)return;scale=Math.max(.08,Math.min(1.5,scale+delta));const image=drawing.querySelector('svg');image.style.width=(size.width*scale)+'px';image.style.height='auto';};
  for(const [label,delta] of [['−',-.15],['+',.15]]){const b=make('button',label);b.type='button';b.setAttribute('aria-label',delta<0?'Zoom out':'Zoom in');b.onclick=()=>zoom(delta);tools.append(b);}zoom(0);
  const fit=make('button','Fit map');fit.type='button';fit.onclick=()=>{scale=Math.min(1,(viewport.clientWidth-12)/size.width,(viewport.clientHeight-12)/size.height);zoom(0);viewport.scrollLeft=0;viewport.scrollTop=0;};tools.append(fit);
  const reset=make('button','All connections');reset.hidden=true;reset.type='button';reset.onclick=()=>{for(const el of drawing.querySelectorAll('[data-node-id],[data-edge-from]')){el.style.opacity='1';el.setAttribute('data-selected','false');}reset.hidden=true;inspector.replaceChildren();};tools.append(reset);
  const inspector=make('div');inspector.className='map-inspector';inspector.setAttribute('aria-live','polite');
  const inspect=id=>{const n=sourceMap.nodes.find(x=>x.id===id);if(!n)return;inspector.replaceChildren(make('h3',n.label),make('p',n.kind.replaceAll('_',' ')+' · '+n.status));
    const related=new Set([id]);for(const e of map.edges.filter(e=>e.from===id||e.to===id)){related.add(e.from);related.add(e.to);}
    for(const el of drawing.querySelectorAll('[data-node-id]')){el.style.opacity=related.has(el.getAttribute('data-node-id'))?'1':'.28';el.setAttribute('data-selected',String(el.getAttribute('data-node-id')===id));}
    for(const el of drawing.querySelectorAll('[data-edge-from]'))el.style.opacity=[el.getAttribute('data-edge-from'),el.getAttribute('data-edge-to')].includes(id)?'1':'.06';reset.hidden=false;
    if(onEdit){const label=make('label','Label'),input=make('textarea');input.value=n.label;input.maxLength=320;label.append(input);const save=make('button','Keep label edit');save.onclick=async()=>{const before=n.label;try{text(input.value,320);n.label=input.value;await onEdit({action:'edit_node_label',at:new Date().toISOString(),source_sha256:sourceMap.sources[0].sha256,node_id:n.id,before,after:n.label});refresh();}catch(error){n.label=before;inspector.append(make('p',error.message));}};inspector.append(label,save);}
    const source=map.sources.find(x=>x.id===n.evidence.source_id);inspector.append(make('p',`Source: ${source.title} · characters ${n.evidence.start+1}–${n.evidence.end}`),make('blockquote',n.evidence.quote));
    for(const e of sourceMap.edges.filter(e=>e.from===id||e.to===id)){const other=sourceMap.nodes.find(x=>x.id===(e.from===id?e.to:e.from));const row=make('details'),summary=make('summary',(e.from===id?'→ ':'← ')+e.relation.replaceAll('_',' ')+': '+other.label);row.append(summary,make('blockquote',e.evidence.quote));
      if(onEdit&&e.relation==='precedes'){const reverse=make('button','Reverse chronology');reverse.type='button';reverse.onclick=async()=>{const original=sourceMap.edges;try{const result=await reverseChronology(sourceMap,e.id);sourceMap.edges=result.map.edges;await onEdit(result.receipt);refresh();}catch(error){sourceMap.edges=original;inspector.append(make('p',error.message));}};row.append(reverse);}inspector.append(row);}
    const close=make('button','Close details');close.type='button';close.className='quiet';close.onclick=reset.onclick;inspector.append(close);
  };
  for(const el of drawing.querySelectorAll('[data-node-id]')){el.onclick=()=>inspect(el.getAttribute('data-node-id'));el.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inspect(el.getAttribute('data-node-id'));}};}
  const hint=make('span','Drag canvas to pan · select a node for evidence');hint.className='muted';tools.append(hint);
  if(compact){viewport.className='map-phase-content';container.append(drawing,reset,inspector);connectCards(drawing,map.edges.map(e=>({from:e.from,to:e.to,label:e.relation.replaceAll('_',' '),title:sourceMap.nodes.find(n=>n.id===e.from).label+' → '+e.relation.replaceAll('_',' ')+' → '+sourceMap.nodes.find(n=>n.id===e.to).label})));}else container.append(tools,viewport,inspector);
}
