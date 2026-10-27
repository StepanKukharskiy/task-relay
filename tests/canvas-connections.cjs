// Connection badges project existing health/policy; never dispatch or infer delivery.
const assert=require('node:assert/strict');
const {channelStatus}=require('../task_relay/assets/companion-workflow.js');
const ready={setup:{telegram:{paired:true}},service:{healthy:true,loaded:true},messages:{paired:true,healthy:true,loaded:true},channels:{policy:{paused:false,enabled:{telegram:true,messages:true}},runtime:{telegram:true,messages:true}}};
assert.equal(channelStatus(null,'telegram').state,'unknown');
for(const channel of ['telegram','messages']){
 assert.equal(channelStatus(ready,channel).state,'connected');
 const copy=()=>JSON.parse(JSON.stringify(ready));let v=copy();
 v.channels.policy.paused=true;assert.equal(channelStatus(v,channel).label,'Messaging paused');
 v=copy();v.channels.policy.enabled[channel]=false;assert.equal(channelStatus(v,channel).label,'Turned off');
 v=copy();v.channels.runtime[channel]=false;assert.equal(channelStatus(v,channel).state,'attention');
 v=copy();v[channel==='telegram'?'service':'messages'].healthy=false;v[channel==='telegram'?'service':'messages'].loaded=false;assert.equal(channelStatus(v,channel).label,'Stopped');
 v=copy();v[channel==='telegram'?'service':'messages'].error='Permission missing';assert.equal(channelStatus(v,channel).label,'Needs attention');
 v=copy();if(channel==='telegram')v.setup.telegram.paired=false;else v.messages.paired=false;assert.equal(channelStatus(v,channel).label,'Not connected');
}
console.log('PASS: 15 connection-state cases across Telegram and Messages. No network or state mutation.');
