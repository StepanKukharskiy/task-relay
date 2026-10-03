// Isolated DOM/controller fixture; no browser, helper, account or provider is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.hidden = false; this.disabled = false; this.value = ''; this.handlers = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  set innerHTML(_) { throw Error('Untrusted session data must never use innerHTML'); }
}
const elements = new Map();
const document = {getElementById: id => {
  if (!elements.has(id)) elements.set(id, new Element('fixture'));
  return elements.get(id);
}, createElement: tag => new Element(tag)};
const $ = document.getElementById;
const calls = [];
let failControl = false, pending = null, delayDetail = false, state = 'running', failPermissions = false;
const view = id => ({id, job: 'fixture-job', state, exact_request: '<img src=x onerror=alert(1)>',
  spec: {actions: [{operation: 'scroll', direction: 'down'}]}, helper: {binary_sha256: 'fixture'},
  current_url: 'https://example.com/one', unresolved: 1, actions: [{state: 'uncertain', resolved: false}],
  evidence_note: 'Unreviewed', recent_decisions: [], decision_count: 0, fingerprint: 'frozen-'+id,
  can_pause: state === 'running', can_cancel: state !== 'cancelled'});
const window = {__TAURI__: {core: {invoke: async (command, args) => {
  assert.equal(command, 'relay_request'); calls.push(args);
  if (args.path === 'computer-setup-status') return {available:true,helper:'/fixture/helper.app',permissions:{accessibility:true,screen_recording:false,session_unlocked:true}};
  if (args.path === 'computer-request-permissions') { if (failPermissions) throw Error('Unconfirmed permission response'); return {available:false,error:'Fixture helper missing'}; }
  if (args.path === 'computer-sessions') return {items: ['A','B'].map(id => ({id, request_excerpt: id, state})), total:2, next_offset:null};
  if (args.path === 'computer-session-detail') {
    if (delayDetail && args.value.id === 'A') return new Promise(resolve => { pending = () => resolve(view('A')); });
    return view(args.value.id);
  }
  if (args.path === 'computer-session-control') {
    if (failControl) throw Error('Lost decision reply');
    state = args.value.kind === 'pause' ? 'paused' : 'cancelled';
    return view(args.value.id);
  }
  throw Error('Unexpected operation '+args.path);
}}}};
vm.runInNewContext(fs.readFileSync('task_relay/assets/companion-computer.js','utf8'), {window, document, console});
const tick = () => new Promise(resolve => setImmediate(resolve));
const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
const buttons = () => descendants($('computer-session-detail')).filter(e => e.tag === 'button');
const note = () => $('computer-session-detail').children.find(e => e.tag === 'textarea');
(async () => {
  await window.RelayComputerSessions.connect();
  assert.equal($('computer-sessions-open').hidden, false);
  $('computer-sessions-open').onclick(); await tick();
  const rows = $('computer-sessions-list').children;
  // Old detail response must not replace a newer user selection.
  delayDetail = true;
  rows[0].onclick(); await tick();
  await rows[1].onclick(); pending(); await tick();
  assert.match($('computer-session-detail').children[1].textContent, /Session B/);
  const exact = $('computer-session-detail').children[2].children[1];
  assert.equal(exact.textContent, '<img src=x onerror=alert(1)>');
  assert.ok(buttons().every(b => b.disabled));
  note().value = 'Pause while I inspect Safari.'; note().handlers.input();
  assert.ok(buttons().every(b => !b.disabled));
  await buttons()[0].onclick();
  const decision = calls.find(c => c.path === 'computer-session-control');
  assert.equal(decision.value.id, 'B'); assert.equal(decision.value.fingerprint, 'frozen-B');
  assert.equal(decision.value.note, 'Pause while I inspect Safari.');
  assert.equal(buttons().length, 1); // paused still permits Cancel
  assert.equal($('computer-session-detail').children[0].textContent, 'Session paused');
  failControl = true; note().value = 'Cancel further actions.'; note().handlers.input();
  await buttons()[0].onclick(); await tick();
  assert.equal(calls.filter(c => c.path === 'computer-session-control').length, 2);
  assert.equal($('computer-session-detail').children.length, 0);
  assert.match($('computer-sessions-feedback').textContent, /Refresh to inspect saved state/);
  assert.ok(calls.every(c => !/run|resume|approve/.test(c.path)));
  await $('computer-setup-check').onclick();
  assert.equal($('computer-setup-summary').textContent, 'Helper available');
  assert.match($('computer-setup-detail').textContent, /Screen Recording not granted/);
  assert.match($('computer-setup-detail').textContent, /Automation is checked when an approved task starts/);
  failPermissions = true;
  await $('computer-permissions-request').onclick(); await tick();
  assert.equal($('computer-setup-summary').textContent, 'Check failed');
  assert.equal($('computer-permissions-request').disabled, false);
  assert.equal(calls.filter(c=>c.path==='computer-request-permissions').length, 1);
  console.log('PASS: escaped display, out-of-order detail, explicit note, frozen decision, unknown reply without replay.');
})().catch(error => { console.error(error); process.exitCode = 1; });
