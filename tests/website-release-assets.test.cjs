const {test}=require('node:test');
const assert=require('node:assert/strict');
const {mkdtemp,readFile,rm,access}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
const {createHash}=require('node:crypto');

test('build assets verify bytes before replacement and preserve prior file on corrupt download',async()=>{
  const {fetchDownloads}=await import('../website/fetch-downloads.mjs');
  const dir=await mkdtemp(join(tmpdir(),'relay-release-'));
  const name='Task-Relay-0.13.26-arm64.dmg';
  const body='fixture bytes';
  const item={name,url:'https://github.com/StepanKukharskiy/task-relay/releases/download/v0.13.26/'+name,
    bytes:Buffer.byteLength(body),sha256:createHash('sha256').update(body).digest('hex')};
  try{
    await fetchDownloads([item],dir,async()=>new Response(body));
    assert.equal(await readFile(join(dir,name),'utf8'),body);
    await assert.rejects(fetchDownloads([item],dir,async()=>new Response('corrupt bytes')),/checksum|size/);
    assert.equal(await readFile(join(dir,name),'utf8'),body);
    await assert.rejects(access(join(dir,name+'.partial')));
    await assert.rejects(fetchDownloads([{...item,name:'../escape'}],dir),/manifest/);
    await assert.rejects(fetchDownloads([{...item,url:'https://example.org/'+name}],dir),/URL/);
    await assert.rejects(fetchDownloads([item],dir,async()=>new Response('',{status:404})),/download failed/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
