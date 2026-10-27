// Synthetic projection checks; no solver data or model calls in public tests.
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const {groupPhases}=await import(path.resolve('extensions/chrome/work-map.js'));let checks=0;
 function fixture(count,kind='attempt'){
  const nodes=Array.from({length:count},(_,i)=>({id:'n'+i,label:'Step '+i,kind,status:'reported',evidence:{start:i*100}}));
  return {nodes,edges:nodes.slice(1).map((n,i)=>({id:'e'+i,from:'n'+i,to:n.id,relation:'precedes'}))};
 }
 function verify(map){
  const original=JSON.stringify(map),a=groupPhases(map),b=groupPhases(map);
  assert.deepEqual(a,b);assert.equal(JSON.stringify(map),original,'Projection leaves exact map state unchanged');
  assert.deepEqual(a.phases.flatMap(p=>p.nodes.map(n=>n.id)).sort(),map.nodes.map(n=>n.id).sort(),'Every node appears exactly once');
  assert(a.phases.length<=6);assert(a.phases.every(p=>p.nodes.length&&p.nodes.some(n=>n.label===p.title)));
  const membership=new Map(a.phases.flatMap(p=>p.nodes.map(n=>[n.id,p.id])));
  assert.deepEqual(a.connections.flatMap(c=>c.edges.map(e=>e.id)).sort(),map.edges.filter(e=>membership.get(e.from)!==membership.get(e.to)).map(e=>e.id).sort(),'All and only actual cross-phase edges remain inspectable');checks++;return a;
 }
 assert.equal(verify(fixture(0)).phases.length,0);assert.equal(verify(fixture(1)).phases.length,1);
 for(const kind of ['attempt','finding','requirement'])for(const count of [2,9,20,80,240])verify(fixture(count,kind));
 const branches=fixture(16);branches.nodes.push({id:'caveat',label:'Unverified metric',kind:'finding',status:'unresolved',evidence:{start:50}},{id:'rejected',label:'Rejected alternative',kind:'attempt',status:'rejected',evidence:{start:80}});branches.edges.push({id:'c',from:'caveat',to:'n10',relation:'qualifies'},{id:'r',from:'n2',to:'rejected',relation:'precedes'});
 const grouped=verify(branches),owner=id=>grouped.phases.find(p=>p.nodes.some(n=>n.id===id));assert.equal(owner('caveat'),owner('n10'));assert.equal(owner('rejected'),owner('n2'));checks++;
 const proposal=fixture(18);for(const n of proposal.nodes.slice(-2)){n.kind='proposal';n.status='proposed';}const proposed=verify(proposal);assert(proposed.phases.at(-1).proposed);assert.deepEqual(proposed.phases.at(-1).nodes.map(n=>n.id),['n16','n17']);checks++;
 const reversed=fixture(9);reversed.nodes.reverse();for(const n of reversed.nodes)n.evidence.start=900-n.evidence.start;const ordered=verify(reversed);assert.equal(ordered.phases[0].nodes[0].id,'n0');checks++;
 const cycle=fixture(9);cycle.edges.push({id:'cycle',from:'n8',to:'n0',relation:'precedes'});assert(verify(cycle).chronologyCycle);checks++;
 console.log(JSON.stringify({passed:true,checks,scope:'Chronology phase projection: exhaustive membership, bounded overview, attached cautions/branches, proposed tail, all cross-phase edges, cycles, deterministic non-mutating legacy-map support',live_ai:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
