// Public release discovery: exact repository, complete asset sets, no credentials.
export const repository = 'https://github.com/StepanKukharskiy/task-relay';
const api = 'https://api.github.com/repos/StepanKukharskiy/task-relay/releases?per_page=100';
export const assetKinds = {dmg: 'arm64.dmg', dmgChecksum: 'arm64.dmg.sha256', source: 'source.tar.gz', sourceChecksum: 'source.tar.gz.sha256'};
const versionPattern = /^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$/;
export function compareVersions(a,b) {
  const parts = v => { const m=versionPattern.exec(v); if(!m)throw Error('Invalid version'); return [Number(m[1]),Number(m[2]),Number(m[3]),m[4]===undefined?Infinity:Number(m[4])]; };
  const x=parts(a),y=parts(b);for(let i=0;i<x.length;i++)if(x[i]!==y[i])return x[i]>y[i]?1:-1;return 0;
}
export function releaseFromGithub(row) {
  if (!row || row.draft!==false || typeof row.prerelease!=='boolean' || !row.published_at || !Array.isArray(row.assets)) return null;
  const version=String(row.tag_name).replace(/^v/,'');
  if (!versionPattern.test(version) || row.tag_name!=='v'+version || !Number.isFinite(Date.parse(row.published_at))) return null;
  const assets={};
  for (const [kind,suffix] of Object.entries(assetKinds)) {
    const name='Task-Relay-'+version+'-'+suffix;
    const matches=row.assets.filter(a=>a.name===name);
    if(matches.length!==1)return null;
    const a=matches[0],url=repository+'/releases/download/'+row.tag_name+'/'+name;
    if(a.state!=='uploaded' || !Number.isSafeInteger(a.size) || a.size<=0 || a.browser_download_url!==url)return null;
    assets[kind]={name,url,bytes:a.size};
  }
  return {version,channel:row.prerelease?'Beta':'Stable',url:repository+'/releases/tag/'+row.tag_name,assets};
}
export function newestRelease(rows) {
  if(!Array.isArray(rows))throw Error('Invalid release list');
  return rows.map(releaseFromGithub).filter(Boolean).sort((a,b)=>compareVersions(b.version,a.version))[0] || null;
}
export function createReleaseResolver({fallback,fetcher=fetch,now=Date.now,ttl=300000}={}) {
  let current=releaseFromGithub(fallback),expires=0,pending;
  if(!current)throw Error('A complete published fallback release is required');
  return async function resolve() {
    if(now()<expires)return current;
    if(!pending)pending=(async()=>{
      try {
        const res=await fetcher(api,{headers:{Accept:'application/vnd.github+json','User-Agent':'Task-Relay-Website'},signal:AbortSignal.timeout(5000)});
        if(!res.ok)throw Error('Release discovery unavailable');
        const text=await res.text();if(text.length>2000000)throw Error('Release list oversized');
        const candidate=newestRelease(JSON.parse(text));
        if(candidate && compareVersions(candidate.version,current.version)>=0)current=candidate;
      } catch { /* Keep the last known complete release during API failures. */ }
      expires=now()+ttl;return current;
    })().finally(()=>{pending=undefined;});
    return pending;
  };
}
export function renderRelease(template,release) {
  const values={RELEASE_VERSION:release.version,RELEASE_CHANNEL:release.channel,RELEASE_URL:release.url};
  for(const [kind,a] of Object.entries(release.assets))values[kind.toUpperCase()+'_URL']=a.url;
  return template.replace(/\{\{([A-Z_]+)\}\}/g,(match,key)=>{if(!(key in values))throw Error('Unknown release placeholder');return values[key].replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');});
}
