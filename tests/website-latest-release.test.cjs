const {test}=require('node:test');
const assert=require('node:assert/strict');
const repo='https://github.com/StepanKukharskiy/task-relay';
function release(version,extra={}) {return {tag_name:'v'+version,draft:false,prerelease:true,published_at:'2026-01-01T00:00:00Z',assets:['arm64.dmg','arm64.dmg.sha256','source.tar.gz','source.tar.gz.sha256'].map(suffix=>({name:'Task-Relay-'+version+'-'+suffix,size:123,state:'uploaded',browser_download_url:repo+'/releases/download/v'+version+'/Task-Relay-'+version+'-'+suffix})),...extra};}
test('highest complete release includes betas and ignores drafts, partial uploads and unrelated URLs',async()=>{
 const {newestRelease,releaseFromGithub}=await import('../website/releases.mjs');
 const partial=release('0.14.0');partial.assets.pop();
 const injected=release('0.15.0');injected.assets[0].browser_download_url='https://example.org/download.dmg';
 const uploading=release('0.16.0');uploading.assets[0].state='new';
 const duplicate=release('0.17.0');duplicate.assets.push(duplicate.assets[0]);
 const good=release('0.13.54');
 assert.equal(newestRelease([good,release('0.13.9'),partial,injected,uploading,duplicate,release('99.0.0',{draft:true})]).version,'0.13.54');
 assert.equal(newestRelease([release('1.0.0-beta.10'),release('1.0.0-beta.2')]).version,'1.0.0-beta.10');
 assert.equal(newestRelease([release('1.0.0-beta.10'),release('1.0.0',{prerelease:false})]).channel,'Stable');
 assert.equal(releaseFromGithub(release('0.13.54',{tag_name:'<script>'})),null);
});
test('resolver coalesces requests, caches, advances automatically and preserves last good on failures or downgrade',async()=>{
 const {createReleaseResolver}=await import('../website/releases.mjs');let now=0,calls=0,rows=[release('0.13.54')],fail=false;
 const resolve=createReleaseResolver({fallback:release('0.13.26'),now:()=>now,ttl:10,fetcher:async()=>{calls++;if(fail)throw Error('offline');return new Response(JSON.stringify(rows));}});
 const first=await Promise.all([resolve(),resolve(),resolve()]);assert.equal(calls,1);assert.ok(first.every(x=>x.version==='0.13.54'));
 await resolve();assert.equal(calls,1);now=11;rows=[release('0.13.55')];assert.equal((await resolve()).version,'0.13.55');
 now=22;fail=true;assert.equal((await resolve()).version,'0.13.55');
 now=33;fail=false;rows=[release('0.13.26')];assert.equal((await resolve()).version,'0.13.55');
 now=44;rows={message:'API rate limit exceeded'};assert.equal((await resolve()).version,'0.13.55');
});
test('fresh deployment has complete fallback when discovery fails and renders a consistent version and links',async()=>{
 const {createReleaseResolver,renderRelease}=await import('../website/releases.mjs');
 const resolve=createReleaseResolver({fallback:release('0.13.54'),fetcher:async()=>new Response('',{status:403})});
 const r=await resolve();const html=renderRelease('{{RELEASE_CHANNEL}} {{RELEASE_VERSION}} {{DMG_URL}} {{SOURCE_URL}}',r);
 assert.match(html,/Beta 0.13.54/);assert.match(html,/v0.13.54\/Task-Relay-0.13.54-arm64.dmg/);assert.match(html,/v0.13.54\/Task-Relay-0.13.54-source.tar.gz/);assert.ok(!html.includes('{{'));
});
