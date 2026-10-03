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
