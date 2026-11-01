const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('task_relay/assets/companion-setup.js','utf8'), context);
const step = context.RelaySetup.step;
const info = () => ({setup:{providers:{},telegram:{}},service:{owner:'none'}});
test('fresh install progresses only after each saved connection and healthy startup',()=>{
  const s=info(); assert.equal(step(s).id,'ai');
  s.setup.providers.gemini=true; assert.equal(step(s).action,'start');
  s.service.loaded=true; assert.equal(step(s).action,'troubleshoot');
  s.service.healthy=true; assert.equal(step(s),null);
  assert.equal(s.setup.telegram.configured,undefined);
});
test('existing installation is offered before creating new credentials or services',()=>{
  const s=info(); s.service.connectable=true; assert.equal(step(s).action,'connect');
  s.service.connectable=false;s.service.owner='other';s.setup.selected_provider='later';s.setup.telegram.configured=true;
  assert.equal(step(s).action,'handoff');
});
test('saved messenger setup stays separate from local worker health',()=>{
  const s=info();s.setup.selected_provider='later';s.setup.telegram={configured:true,paired:true};
  s.service.healthy=true; assert.equal(step(s),null);
  s.setup.telegram.paired=false;s.service.healthy=false;s.service.error='Access unavailable';
  assert.equal(step(s).action,'troubleshoot');
});
test('automatic startup is offered only for completed readable local setup',()=>{
  const auto = s => context.RelaySetup.shouldAutoStart(s);
  const s = info(); assert.equal(auto(s),false);
  s.setup.selected_provider='later'; assert.equal(auto(s),true);
  s.setup.telegram.error='Unreadable credential'; assert.equal(auto(s),true);
  s.service.loaded=true; assert.equal(auto(s),false);
  s.service.loaded=false;s.service.owner='other'; assert.equal(auto(s),false);
  s.service.owner='desktop';s.setup.setup_error='Unreadable setup'; assert.equal(auto(s),false);
});

test('app-open refresh submits startup once, including recursive and later refreshes',async()=>{
  const nodes = new Map();
  const sandbox = vm.createContext({
    window:{RelaySetup:context.RelaySetup},
    $:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);},
    readFailed:false, refreshing:false, mutating:false, automaticStartAttempted:false,
    snapshot:null, calls:[], message:()=>{},
    request:async action=>action==='companion-status' ?
      {setup:{selected_provider:'later'},service:{owner:'desktop',loaded:false}} : {items:[]}
  });
  const source=fs.readFileSync('task_relay/assets/companion.js','utf8');
  vm.runInContext(`function render(info){snapshot=info;}
    async function change(action){calls.push(action);await refresh();}
` +
    source.slice(source.indexOf('async function refresh()'),source.indexOf('function savedWorkError(')),sandbox);
  await sandbox.refresh(); await sandbox.refresh();
  assert.deepEqual(Array.from(sandbox.calls),['service-auto-start']);
});

test('Codex chat hides API credentials and qualifies for local startup',()=>{
  const nodes=new Map();
  const sandbox=vm.createContext({$:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);},keyURLs:{gemini:'fixture'}});
  const source=fs.readFileSync('task_relay/assets/companion.js','utf8');
  vm.runInContext(source.slice(source.indexOf('function providerFields()'),source.indexOf('let setupStep')),sandbox);
  nodes.set('provider-name',{value:'codex'});sandbox.providerFields();
  assert.equal(nodes.get('provider-credentials').hidden,true);
  assert.equal(nodes.get('codex-chat-help').hidden,false);
  nodes.get('provider-name').value='gemini';sandbox.providerFields();
  assert.equal(nodes.get('provider-credentials').hidden,false);
  assert.equal(nodes.get('codex-chat-help').hidden,true);
  const s=info();s.setup.providers.codex=true;assert.equal(step(s).action,'start');
});
