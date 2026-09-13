const {test}=require('node:test');
const assert=require('node:assert/strict');
const {mkdtemp,writeFile,rm}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
test('download routes support complete files, HEAD and resume without exposing arbitrary files',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'relay-download-'));
  const names=['Task-Relay-0.12.1-beta.1-arm64.dmg','Task-Relay-0.12.1-beta.1-source.tar.gz'];
  for(const name of names)for(const suffix of ['', '.sha256'])await writeFile(join(folder,name+suffix),'0123456789');
  const child=spawn(process.execPath,['website/server.mjs'],{env:{...process.env,PORT:'0',TASK_RELAY_DOWNLOAD_DIR:folder}});
  try{
    const text=await new Promise((resolve,reject)=>{child.stdout.once('data',b=>resolve(b.toString()));child.once('error',reject);child.once('exit',c=>reject(Error('server exit '+c)));});
    const base='http://127.0.0.1:'+text.match(/port (\d+)/)[1], url=base+'/downloads/'+names[0];
    const head=await fetch(url,{method:'HEAD'});assert.equal(head.status,200);assert.equal(head.headers.get('content-length'),'10');assert.equal(await head.text(),'');
    const full=await fetch(url);assert.equal(await full.text(),'0123456789');assert.match(full.headers.get('content-disposition'),/attachment/);
    const part=await fetch(url,{headers:{Range:'bytes=4-6'}});assert.equal(part.status,206);assert.equal(await part.text(),'456');assert.equal(part.headers.get('content-range'),'bytes 4-6/10');
    assert.equal((await fetch(url,{headers:{Range:'bytes=40-'}})).status,416);
    assert.equal((await fetch(base+'/downloads/%2e%2e/server.mjs')).status,404);
    assert.equal((await fetch(url,{method:'POST'})).status,405);
    assert.equal((await fetch(base+'/health')).status,200);
  }finally{child.kill('SIGTERM');await once(child,'exit');await rm(folder,{recursive:true,force:true});}
});
