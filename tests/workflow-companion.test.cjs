// Small committed graphs; no runtime, provider, browser or native app is used.
const assert = require('node:assert/strict');
const {layout,resultFiles} = require('../task_relay/assets/companion-workflow.js');
const t = (id,deps=[],status='queued') => ({id,status,dependencies:deps.map(task=>({task}))});
const branch=[t('export',['review']),t('review',['draft']),t('draft',['research','data']),t('data'),t('research')];
const graph=layout(branch);
assert.deepEqual(graph.layers.map(layer=>layer.map(t=>t.id)),[['data','research'],['draft'],['review'],['export']]);
assert.equal(graph.sequential,false);
assert.deepEqual(new Set(graph.edges.map(e=>e.from+'>'+e.to)),new Set(['research>draft','data>draft','draft>review','review>export']));
assert.equal(layout([t('review',['draft']),t('draft')]).sequential,true);
// Disconnected work must not be drawn as an invented dependency chain.
assert.equal(layout([t('one'),t('two')]).sequential,false);
// Damaged history remains inspectable without pretending to have a valid order.
const broken=layout([t('one',['two']),t('two',['one']),t('other',['missing'])]);
assert.equal(broken.sequential,false);
assert.equal(broken.issues.length,2);
assert.deepEqual(new Set(broken.layers.flat().map(t=>t.id)),new Set(['one','two','other']));
// Review completion must not rewrite its producer's pending user decision.
const gated=[t('produce',[],'awaiting_user'),t('review',['produce'],'completed')];
const before=JSON.stringify(gated); layout(gated); assert.equal(JSON.stringify(gated),before);
// Reviewing a file keeps it beside its gate without duplicating it in results.
const outputs=[{id:'source',task:'source',sha256:'a'},{id:'draft',task:'draft',sha256:'b'},{id:'review',task:'review',sha256:'c'}];
const view={tasks:[t('source'),t('draft',['source']),{...t('review',['draft']),review_of:'draft'}],latest_outputs:outputs,selections:[]};
assert.deepEqual(resultFiles(view,new Set(['draft'])).primary,[]);
assert.deepEqual(resultFiles(view,new Set(['draft'])).other.map(f=>f.id),['source','review']);
// A review report cannot displace a selected result, and an old/mismatched
// selection cannot promote another file merely because the task/name matches.
view.selections=[{artifact:'source',sha256:'a'}];
assert.deepEqual(resultFiles(view).primary.map(f=>f.id),['source']);
view.selections=[{artifact:'source',sha256:'changed'},{artifact:'old-draft',sha256:'b'}];
assert.deepEqual(resultFiles(view).primary.map(f=>f.id),['draft']);
assert.deepEqual(view.latest_outputs,outputs);
console.log('Workflow projection passed: branching, sequence, disconnected work, damaged history and pending decisions.');

const direct={tasks:[{id:'owner',status:'completed',dependencies:[]}],latest_outputs:[{id:'manifest',task:'owner',sha256:'m'},{id:'answer',task:null,sha256:'a'}],delivered_outputs:[{artifact:'answer',sha256:'a',review_status:'unreviewed'}]};
assert.deepEqual(resultFiles(direct).primary.map(f=>f.id),['answer']);
assert.deepEqual(resultFiles(direct).other.map(f=>f.id),['manifest']);
assert.deepEqual(resultFiles({...direct,delivered_outputs:[{artifact:'answer',sha256:'changed'}]}).primary.map(f=>f.id),['manifest']);
// Do not fabricate historical graphs from stage order or message transcripts.
{
 const {pipelineGraph,canvasEdges}=require('../task_relay/assets/companion-workflow.js');
 const old={id:'old',stages:[{id:'read',tasks:[{id:'guess'}]},{id:'write',status:'pending'}]};
 assert.equal(pipelineGraph(old).tasks.length,0);
 const source={name:'a',tasks:[{id:'same',planned_outputs:[{path:'page'}]}],latest_outputs:[{id:'blob',sha256:'exact',task:'same',path:'page'}]};
 const target={name:'b',tasks:[{id:'same',planned_inputs:[{path:'input'}],recorded_inputs:[{path:'input',artifact:'blob',sha256:'wrong'}]}]};
 const view={id:'job',stages:[{id:'read',execution:source},{id:'write',execution:target}]};
 const before=JSON.stringify(view);let graph=pipelineGraph(view);
 assert.equal(new Set(graph.tasks.map(t=>t.id)).size,2);assert.equal(canvasEdges(graph.tasks).length,0,'same path or wrong hash cannot create a handoff');
 assert.equal(JSON.stringify(view),before);
 target.tasks[0].recorded_inputs[0].sha256='exact';graph=pipelineGraph(view);
 assert.equal(canvasEdges(graph.tasks).length,1);assert.equal(canvasEdges(graph.tasks)[0].kind,'binding');
 source.historical_outputs=source.latest_outputs;source.latest_outputs=[];
 assert.equal(canvasEdges(pipelineGraph(view).tasks).length,0,'retained output cannot be shown as current output');
}
