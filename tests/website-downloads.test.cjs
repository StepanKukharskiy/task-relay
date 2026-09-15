const {test}=require('node:test');
const assert=require('node:assert/strict');
const {mkdtemp,writeFile,rm}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
test('download routes support complete files, HEAD and resume without exposing arbitrary files',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'relay-download-'));
  const names=['Task-Relay-0.12.1-beta.1-arm64.dmg','Task-Relay-0.12.1-beta.1-source.tar.gz','Task-Relay-0.13.0-beta.1-arm64.dmg','Task-Relay-0.13.0-beta.1-source.tar.gz','Task-Relay-0.13.26-arm64.dmg','Task-Relay-0.13.26-source.tar.gz'];
  for(const name of names)for(const suffix of ['', '.sha256'])await writeFile(join(folder,name+suffix),'0123456789');
  const child=spawn(process.execPath,['website/server.mjs'],{env:{...process.env,PORT:'0',TASK_RELAY_DOWNLOAD_DIR:folder}});
  try{
    const text=await new Promise((resolve,reject)=>{child.stdout.once('data',b=>resolve(b.toString()));child.once('error',reject);child.once('exit',c=>reject(Error('server exit '+c)));});
    const base='http://127.0.0.1:'+text.match(/port (\d+)/)[1], url=base+'/downloads/'+names[0];
    const page=await (await fetch(base)).text(); assert.match(page,/Beta 0\.13\.26/);
    assert.match(page,/href="\/guides\/"/);
    const guidePaths=['/guides/','/guides/architectural-site-analysis','/guides/rhino-model-revisions','/guides/rhino-named-view-renders','/guides/blender-asset-handoff','/guides/design-review-presentation'];
    const archivedPaths=['/guides/rename-invoice-pdfs','/guides/combine-csv-exports','/guides/find-automation-opportunities'];
    for(const guidePath of [...guidePaths,...archivedPaths]){
      const res=await fetch(base+guidePath);assert.equal(res.status,200);assert.match(res.headers.get('content-type'),/text\/html/);
      const body=await res.text();assert.match(body,/<h1>/);assert.match(body,/rel="canonical"/);
      for(const [,local] of body.matchAll(/(?:href|src)="(\/[^"#]*)(?:#[^"]*)?"/g)){
        assert.equal((await fetch(base+local,{method:'HEAD'})).status,200,guidePath+' links to '+local);
      }
      const guideHead=await fetch(base+guidePath,{method:'HEAD'});assert.equal(await guideHead.text(),'');
      assert.equal(Number(guideHead.headers.get('content-length')),Buffer.byteLength(body));
    }
    assert.equal((await fetch(base+'/guides')).status,200);
    assert.equal((await fetch(base+'/guides/rename-invoice-pdfs/')).status,200);
    const script=await fetch(base+'/guides/assets/file-recipes.py');assert.match(script.headers.get('content-type'),/text\/plain/);assert.match(await script.text(),/def invoice_plan/);
    const sitemap=await(await fetch(base+'/sitemap.xml')).text();
    for(const guidePath of guidePaths)assert.ok(sitemap.includes(guidePath+'</loc>'));
    const hub=await(await fetch(base+'/guides/')).text();
    for(const guidePath of archivedPaths){
      assert.ok(!sitemap.includes(guidePath+'</loc>'));
      assert.ok(!hub.includes('href="'+guidePath+'"'));
      assert.match(await(await fetch(base+guidePath)).text(),/name="robots" content="noindex, follow"/);
    }
    assert.match(await(await fetch(base+'/robots.txt')).text(),/Sitemap:/);
    assert.equal((await fetch(base+'/guides/assets/../../server.mjs')).status,404);
    assert.equal((await fetch(base+'/guides/assets/not-listed.json')).status,404);
    assert.equal((await fetch(base+'/guides/rename-invoice-pdfs',{method:'POST'})).status,405);
    for(const name of names)for(const suffix of ['', '.sha256'])assert.equal((await fetch(base+'/downloads/'+name+suffix,{method:'HEAD'})).status,200);
    for(const [,path] of page.matchAll(/href="(\/downloads\/[^"]+)"/g))assert.equal((await fetch(base+path,{method:'HEAD'})).status,200);
    const head=await fetch(url,{method:'HEAD'});assert.equal(head.status,200);assert.equal(head.headers.get('content-length'),'10');assert.equal(await head.text(),'');
    const full=await fetch(url);assert.equal(await full.text(),'0123456789');assert.match(full.headers.get('content-disposition'),/attachment/);
    const part=await fetch(url,{headers:{Range:'bytes=4-6'}});assert.equal(part.status,206);assert.equal(await part.text(),'456');assert.equal(part.headers.get('content-range'),'bytes 4-6/10');
    assert.equal((await fetch(url,{headers:{Range:'bytes=40-'}})).status,416);
    assert.equal((await fetch(base+'/downloads/%2e%2e/server.mjs')).status,404);
    assert.equal((await fetch(url,{method:'POST'})).status,405);
    assert.equal((await fetch(base+'/health')).status,200);
  }finally{child.kill('SIGTERM');await once(child,'exit');await rm(folder,{recursive:true,force:true});}
});
