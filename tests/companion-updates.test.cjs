const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({window:{}});
vm.runInContext(fs.readFileSync('task_relay/assets/companion-updates.js','utf8'),context);
const view=context.window.RelayAppUpdates.view;
test('source-only releases cannot enable app installation',()=>{
  const model=view({supported:true,checked:1,candidate:null});
  assert.equal(model.ready,false);assert.equal(model.download,false);assert.equal(model.check,true);
});
test('only verified prepared downloads expose install and restart',()=>{
  for(const phase of ['downloading','launching','installing','interrupted','needs_attention','failed']) {
    assert.equal(view({supported:true,attempt:{phase}}).ready,false);
  }
  assert.equal(view({supported:true,attempt:{phase:'ready',version:'0.14.0'}}).ready,true);
});
test('uncertain installation offers recovery and blocks another submission',()=>{
  const model=view({supported:true,candidate:{version:'0.14.0'},attempt:{phase:'interrupted'}});
  assert.equal(model.recover,true);assert.equal(model.download,false);assert.equal(model.check,false);
});
test('busy worker is polled and cannot start another update',()=>{
  const model=view({supported:true,attempt:{phase:'downloading',progress:40,version:'0.14.0'}});
  assert.equal(model.busy,true);assert.equal(model.check,false);assert.match(model.detail,/40%/);
});
function harness(initial) {
  const elements=new Map(), calls=[];
  let state=initial;
  const context=vm.createContext({window:{__TAURI__:{core:{invoke:async (command, args)=>{
    calls.push({command,...args});
    if(args.path==='app-update-install') state={...state,attempt:{...state.attempt,phase:'launching'}};
    return state;
  }}}},document:{getElementById:id=>{
    if(!elements.has(id)) elements.set(id,{hidden:false,disabled:false,checked:false,scrollIntoView(){}});
    return elements.get(id);
  }},setTimeout:()=>1,clearTimeout:()=>{}});
  vm.runInContext(fs.readFileSync('task_relay/assets/companion-updates.js','utf8'),context);
  return {elements,calls,connect:context.window.RelayAppUpdates.connect};
}
test('startup reads or checks metadata without downloading or installing',async()=>{
  const app=harness({supported:true,checked:0,candidate:{id:'release-identity',version:'0.14.0'}});
  app.connect();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(app.calls.map(x=>x.path),['app-update-status','app-update-check']);
  assert.equal(app.elements.get('app-update-install').hidden,true);
  assert.equal(app.elements.get('app-update-notice').hidden,false);
});
test('install click sends exactly the prepared attempt once and disables the control',async()=>{
  const app=harness({supported:true,checked:Date.now()/1000,attempt:{id:'verified-attempt',phase:'ready',version:'0.14.0'}});
  app.connect();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(app.elements.get('app-update-install').hidden,false);
  const first=app.elements.get('app-update-install').onclick();
  const second=app.elements.get('app-update-install').onclick();
  await Promise.all([first,second]);
  const installs=app.calls.filter(x=>x.path==='app-update-install');
  assert.equal(installs.length,1);assert.equal(installs[0].value.id,'verified-attempt');
  assert.equal(app.elements.get('app-update-install').hidden,true);
});
