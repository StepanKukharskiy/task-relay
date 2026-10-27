// One shared multipart protocol for Skill and Work extraction. Each transition
// follows an explicitly read reply; nothing sends, retries or changes a page.
import * as portable from './portable.js';
export const SOURCE_LIMIT=300000,REQUEST_LIMIT=180000,PART_REPLY_LIMIT=16000;
const replyLimit=batch=>Math.min(PART_REPLY_LIMIT,Math.floor(120000/batch.parts.length));
export function excerpt(capture,start,end){return {...capture,selected_content:undefined,extracted_content:(capture.selected_content??capture.extracted_content).slice(start,end),source_metadata:{...capture.source_metadata,limitations:[...(capture.source_metadata.limitations||[]),`This request contains source characters ${start+1}–${end} only.`]}};}
export function plan(capture,intent){
  const body=portable.source(capture).content;if(!body.trim()||body.length>SOURCE_LIMIT)throw Error('Use at most 300,000 characters; nothing was truncated.');
  if(body.length<=60000&&portable.analysisPrompt(capture,null,null,intent).length<REQUEST_LIMIT-1000)return null;
  const parts=[];let start=0;
  while(start<body.length){let end=Math.min(start+45000,body.length);
    if(end<body.length){const boundary=body.lastIndexOf('\n',end);if(boundary>start+20000)end=boundary+1;if(end>start&&/[\uD800-\uDBFF]/.test(body[end-1]))end--;}
    while(portable.analysisPrompt(excerpt(capture,start,end),null,null,'make_job').length>REQUEST_LIMIT-5000){end=start+Math.floor((end-start)/2);if(end<=start)throw Error('Cannot bound this source request');}
    parts.push({start,end});start=end;
  }
  return {version:1,id:crypto.randomUUID(),intent,parts,index:0,phase:'parts',receipts:[]};
}
export function prompt(capture,batch){
  if(batch.phase==='parts'){
    const part=batch.parts[batch.index],selected=excerpt(capture,part.start,part.end);
    return portable.analysisPrompt(selected,null,null,'make_job')+'\n\n'+portable.promptJSON({relay_batch:{id:batch.id,phase:'parts',index:batch.index+1,total:batch.parts.length},instruction:`Extract this part only, returning the Work and work_graph schema above. Keep the entire response under ${replyLimit(batch)} characters, with at most ${Math.min(80,Math.floor(240/batch.parts.length))} nodes and ${Math.min(120,Math.floor(360/batch.parts.length))} edges. Prefer a few pivotal statements over a row-by-row transcription; the exact source is retained separately. Preserve short exact quotes, distinct branches, failures, qualifications and untested proposals. Do not fill missing history from earlier chat messages. This is an intermediate extraction, not the final work.`});
  }
  if(batch.phase!=='synthesis')throw Error('No pending text part');
  // Supply evidence packets, not the original giant document or earlier chat.
  const header=portable.analysisPrompt({...capture,selected_content:undefined,extracted_content:'Use only the exact excerpts in the evidence packets below.'},null,null,batch.intent,{structuredEvidence:false,includeMap:false});
  const request=header+'\n\n'+portable.promptJSON({relay_batch:{id:batch.id,phase:'synthesis',total:batch.parts.length},instruction:'Synthesize ONE final result for the original intent from these validated evidence packets. For Save work, omit work_graph: Relay retains and assembles all per-part maps itself. Quotes must be exact excerpts from the packets. Keep changed validators and ambiguous branches distinct; do not infer acceptance or causation. Do not ask for or reconstruct the original chat.',original_intent:portable.intentInstructions(batch.intent),evidence_packets:batch.receipts.map(r=>({skill_candidates:[],work_changes:r.answer.work_changes}))});
  if(request.length>REQUEST_LIMIT-1000)throw Error('The evidence packets exceed the final handoff budget. Download the retained progress and use smaller sources; nothing was truncated.');return request;
}
export function acceptPart(capture,batch,answer){
  answer=portable.normalizeAnswer(answer);
  if(batch.phase!=='parts')throw Error('No pending source part');
  const limit=replyLimit(batch),raw=JSON.stringify(answer);if(raw.length>limit)throw Error(`This part reply exceeds ${limit.toLocaleString()} characters. Ask for a shorter reply to this same request, then import it; progress is retained.`);
  const part=batch.parts[batch.index],validated=portable.validateAnswer(excerpt(capture,part.start,part.end),answer),normalized={...answer,work_changes:validated.work_changes};
  if(JSON.stringify(normalized).length>limit)throw Error('The bound evidence makes this part too large. Import fewer statements for this same part; progress is retained.');
  if(answer.skill_candidates.length||answer.work_changes.length!==1)throw Error('An intermediate part needs one Work extraction, not a Skill.');
  if(batch.intent==='make_job'&&!answer.work_graph)throw Error('This part is missing its work_graph. Import a complete response to this same request.');
  if(answer.work_graph&&(answer.work_graph.nodes.length>Math.floor(240/batch.parts.length)||answer.work_graph.edges.length>Math.floor(360/batch.parts.length)))throw Error('This part has too many map nodes or connections. Import a smaller map for this same part; progress is retained.');
  // Return a new plan; a failed persistence or validation cannot advance the
  // caller's cursor or silently lose an already accepted part.
  const next=structuredClone(batch);next.receipts.push({...part,answer:structuredClone(normalized)});next.index++;if(next.index===next.parts.length)next.phase='synthesis';return next;
}
