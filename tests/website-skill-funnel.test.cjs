const {test}=require('node:test');
const assert=require('node:assert/strict');
const {mkdtemp,writeFile,readFile,rm}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
const {once}=require('node:events');

test('request counts keep only fixed dimensions and honor privacy/bot exclusions',async()=>{
 const {campaignFor,countRequest}=await import('../website/funnel.mjs');
 const url=new URL('https://example.com/skills/excel-to-powerpoint?utm_source=medium&utm_medium=article&utm_campaign=excel-to-powerpoint-v1&email=private@example.com');
 assert.equal(campaignFor(url),'medium-excel-to-powerpoint-v1');
 assert.equal(campaignFor(new URL('https://example.com/?utm_source=medium&utm_medium=article&utm_campaign=excel-to-powerpoint-v2')),'medium-excel-to-powerpoint-v2');
 assert.equal(campaignFor(new URL('https://example.com/?campaign=%3Cscript%3Esecret')),'direct');
 assert.equal(campaignFor(new URL('https://example.com/?utm_source=personal&utm_medium=article&utm_campaign=excel-to-powerpoint-v3')),'personal-excel-to-powerpoint-v3');
 assert.equal(campaignFor(new URL('https://example.com/?utm_source=guide&utm_medium=article&utm_campaign=excel-to-powerpoint-v3')),'direct');
 const logs=[],request={method:'GET',headers:{'user-agent':'Mozilla/5.0',cookie:'private-cookie','x-forwarded-for':'private-ip',referer:'https://private.example'}};
 const options={enabled:true,now:new Date('2026-10-05T10:00:00Z'),log:x=>logs.push(JSON.parse(x))};
 assert.equal(countRequest(request,'skill_page_request',campaignFor(url),options),true);
 assert.deepEqual(logs,[{schema:'skill-funnel.v1',day:'2026-10-05',skill:'excel-to-powerpoint',campaign:'medium-excel-to-powerpoint-v1',event:'skill_page_request'}]);
 for(const headers of [{dnt:'1'},{'sec-gpc':'1'},{'user-agent':'Googlebot'},{purpose:'prefetch'},{'sec-purpose':'prefetch;prerender'}]) assert.equal(countRequest({...request,headers:{...request.headers,...headers}},'skill_download_request','direct',options),false);
 assert.equal(countRequest({...request,method:'HEAD'},'skill_download_request','direct',options),false);
 assert.equal(countRequest(request,'skill_page_request','direct',{...options,enabled:false}),false);
 assert.equal(logs.length,1);
 assert.throws(()=>countRequest(request,'arbitrary_payload','direct',options),/Unknown/);
});

test('campaign survives Skill download and Relay handoff without logging HEAD, bots or opted-out requests',async()=>{
 const folder=await mkdtemp(join(tmpdir(),'relay-skill-funnel-'));
 const names=['Task-Relay-0.12.1-beta.1-arm64.dmg','Task-Relay-0.12.1-beta.1-source.tar.gz','Task-Relay-0.13.0-beta.1-arm64.dmg','Task-Relay-0.13.0-beta.1-source.tar.gz','Task-Relay-0.13.26-arm64.dmg','Task-Relay-0.13.26-source.tar.gz'];
 for(const name of names)for(const suffix of ['', '.sha256'])await writeFile(join(folder,name+suffix),'small fixture');
 let stdout='';
 const child=spawn(process.execPath,['--import=data:text/javascript,globalThis.fetch=async()=>{throw Error(%22offline fixture%22)}','website/server.mjs'],{env:{...process.env,PORT:'0',TASK_RELAY_DOWNLOAD_DIR:folder,TASK_RELAY_FUNNEL_ANALYTICS:'on'}});
 child.stdout.on('data',b=>stdout+=b.toString());
 try{
  const initial=await new Promise((resolve,reject)=>{child.stdout.once('data',b=>resolve(b.toString()));child.once('error',reject);child.once('exit',c=>reject(Error('server exit '+c)));});
  const base='http://127.0.0.1:'+initial.match(/port (\d+)/)[1],headers={'user-agent':'Mozilla/5.0 controlled-fixture'};
  const campaign='medium-excel-to-powerpoint-v1';
  const landing=await fetch(base+'/skills/excel-to-powerpoint?utm_source=medium&utm_medium=article&utm_campaign=excel-to-powerpoint-v1&email=secret@example.com',{headers});
  const body=await landing.text();assert.equal(landing.status,200);assert.equal(landing.headers.get('cache-control'),'no-store');assert.equal(landing.headers.get('set-cookie'),null);
  assert.ok(body.includes('/get-relay?campaign='+campaign));assert.ok(body.includes('/download/skill?campaign='+campaign));assert.ok(!body.includes('{{skillCampaign}}'));assert.ok(!body.includes('secret@example.com'));
  const archive=await fetch(base+'/skills/excel-to-powerpoint/download/skill?campaign='+campaign,{headers});
  assert.equal(archive.status,200);assert.match(archive.headers.get('content-disposition'),/v2-skill.zip/);assert.equal(Buffer.from(await archive.arrayBuffer()).subarray(0,2).toString(),'PK');
  const handoff=await fetch(base+'/skills/excel-to-powerpoint/get-relay?campaign='+campaign,{headers,redirect:'manual'});
  assert.equal(handoff.status,302);assert.equal(handoff.headers.get('location'),'/?skill=excel-to-powerpoint&campaign='+campaign+'#download');
  const home=await fetch(base+handoff.headers.get('location'),{headers});const homepage=await home.text();
  assert.ok(homepage.includes('/downloads/latest/arm64.dmg?skill=excel-to-powerpoint&campaign='+campaign));
  const relay=await fetch(base+'/downloads/latest/arm64.dmg?skill=excel-to-powerpoint&campaign='+campaign,{headers,redirect:'manual'});
  assert.equal(relay.status,302);assert.match(relay.headers.get('location'),/^https:\/\/github.com\//);
  const privacy=await fetch(base+'/skills/privacy',{headers});assert.match(await privacy.text(),/Do Not Track/);
  for(const extra of [{method:'HEAD'},{headers:{...headers,dnt:'1'}},{headers:{'user-agent':'Googlebot'}},{headers:{...headers,'sec-gpc':'1'}}]) assert.equal((await fetch(base+'/skills/excel-to-powerpoint/download/example?campaign='+campaign,{headers,...extra})).status,200);
  assert.equal((await fetch(base+'/skills/excel-to-powerpoint/download/unlisted',{headers})).status,404);
  assert.equal((await fetch(base+'/skills/excel-to-powerpoint/download/skill',{method:'POST',headers})).status,405);
  const bad=await fetch(base+'/skills/excel-to-powerpoint?campaign=private-campaign',{headers});assert.ok((await bad.text()).includes('/download/skill?campaign=direct'));
  const mediumV2='medium-excel-to-powerpoint-v2';
  const guide=await fetch(base+'/guides/excel-to-powerpoint?utm_source=medium&utm_medium=article&utm_campaign=excel-to-powerpoint-v2',{headers,redirect:'manual'});
  assert.equal(guide.status,308);assert.equal(guide.headers.get('cache-control'),'no-store');
  assert.equal(guide.headers.get('location'),'https://stepankukharskiy.com/ai-work/excel-to-powerpoint-automation?campaign='+mediumV2);
  const ownGuide=await fetch(base+'/guides/excel-to-powerpoint/',{headers,redirect:'manual'});assert.equal(ownGuide.status,308);assert.equal(ownGuide.headers.get('location'),'https://stepankukharskiy.com/ai-work/excel-to-powerpoint-automation');
  const mediumV3='medium-excel-to-powerpoint-v3';
  const nextLanding=await fetch(base+'/skills/excel-to-powerpoint?utm_source=medium&utm_medium=article&utm_campaign=excel-to-powerpoint-v3',{headers});assert.ok((await nextLanding.text()).includes('/download/example?campaign='+mediumV3));
  const exampleV2=await fetch(base+'/skills/excel-to-powerpoint/download/example?campaign='+mediumV3,{headers});assert.match(exampleV2.headers.get('content-disposition'),/v2-example.zip/);await exampleV2.arrayBuffer();
  const personalV3='personal-excel-to-powerpoint-v3';
  const personalLanding=await fetch(base+'/skills/excel-to-powerpoint?campaign='+personalV3,{headers});assert.ok((await personalLanding.text()).includes('/download/skill?campaign='+personalV3));
  const evilGuide=await fetch(base+'/guides/excel-to-powerpoint?campaign=https://private.example',{headers,redirect:'manual'});assert.equal(evilGuide.headers.get('location'),'https://stepankukharskiy.com/ai-work/excel-to-powerpoint-automation');
  assert.equal((await fetch(base+'/skills',{headers})).status,200);
  const legacy=await fetch(base+'/skills/assets/excel-to-powerpoint-v1-skill.zip',{headers});assert.ok(Buffer.from(await legacy.arrayBuffer()).equals(await readFile('website/public/skills/assets/excel-to-powerpoint-v1-skill.zip')));
  await fetch(base+'/health');
  child.kill('SIGTERM');await once(child,'exit');
  const events=stdout.split('\n').filter(x=>x.startsWith('{')).map(x=>JSON.parse(x));
  assert.deepEqual(events.map(e=>[e.event,e.campaign]),[['skill_page_request',campaign],['skill_download_request',campaign],['relay_cta_request',campaign],['relay_download_request',campaign],['skill_page_request','direct'],['skill_page_request',mediumV3],['example_download_request',mediumV3],['skill_page_request',personalV3]]);
  assert.ok(!stdout.includes('private-campaign'));assert.ok(!stdout.includes('secret@example.com'));
 }finally{if(child.exitCode===null){child.kill('SIGTERM');await once(child,'exit');}await rm(folder,{recursive:true,force:true});}
});


test('exported Railway logs aggregate only valid funnel records',()=>{
 const event={schema:'skill-funnel.v1',day:'2026-10-05',skill:'excel-to-powerpoint',campaign:'medium-excel-to-powerpoint-v1',event:'skill_download_request'};
 const input=[JSON.stringify(event),JSON.stringify({message:JSON.stringify(event),timestamp:'2026-10-05T10:00:00Z'}),JSON.stringify({...event,message:'',level:'info',timestamp:'2026-10-05T10:00:01Z'}),'ordinary server log',JSON.stringify({...event,campaign:'unrecognized'}),JSON.stringify({...event,event:'private_payload'})].join('\n');
 const result=spawnSync(process.execPath,['website/summarize-funnel.mjs'],{input,encoding:'utf8'});
 assert.equal(result.status,0);
 assert.equal(result.stdout,'day,skill,campaign,event,requests\n2026-10-05,excel-to-powerpoint,medium-excel-to-powerpoint-v1,skill_download_request,3\n');
 assert.match(result.stderr,/Accepted 3 website event records/);assert.match(result.stderr,/do not establish unique visitors/);
});
