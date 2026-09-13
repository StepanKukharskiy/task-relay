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
  s.setup.providers.gemini=true; assert.equal(step(s).id,'telegram');
  s.setup.telegram.configured=true; assert.equal(step(s).action,'start');
  s.service.loaded=true; assert.equal(step(s).action,'troubleshoot');
  s.service.healthy=true; assert.equal(step(s).action,'pair');
  s.setup.telegram.paired=true; assert.equal(step(s),null);
});
test('existing installation is offered before creating new credentials or services',()=>{
  const s=info(); s.service.connectable=true; assert.equal(step(s).action,'connect');
  s.service.connectable=false;s.service.owner='other';s.setup.selected_provider='later';s.setup.telegram.configured=true;
  assert.equal(step(s).action,'handoff');
});
test('resume retains saved setup and stopping a paired service does not restart onboarding',()=>{
  const s=info();s.setup.selected_provider='later';s.setup.telegram={configured:true,paired:true};
  assert.equal(step(s),null);
  s.setup.telegram.paired=false;s.service.error='Access unavailable';
  assert.equal(step(s).action,'troubleshoot');
});
