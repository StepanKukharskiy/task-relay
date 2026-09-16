import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createReleaseResolver, renderRelease, assetKinds } from './releases.mjs';
const resolveRelease = createReleaseResolver({fallback: JSON.parse(await readFile(new URL('./release-fallback.json', import.meta.url)))});

// Exact public routes only: no access to Relay configuration or arbitrary files.
const assets = new Map();
for (const [route, file, type] of [
  ['/', 'index.html', 'text/html; charset=utf-8'],
  ['/style.css', 'style.css', 'text/css; charset=utf-8'],
  ['/logo.png', 'logo.png', 'image/png'],
  ['/llms.txt', 'llms.txt', 'text/plain; charset=utf-8'],
  ['/guides/', 'guides/index.html', 'text/html; charset=utf-8'],
  ['/guides/guide.css', 'guides/guide.css', 'text/css; charset=utf-8'],
  ...['architectural-site-analysis', 'rhino-model-revisions', 'rhino-named-view-renders', 'blender-asset-handoff', 'design-review-presentation',
      'rename-invoice-pdfs', 'combine-csv-exports', 'find-automation-opportunities']
    .map(slug => ['/guides/' + slug, 'guides/' + slug + '.html', 'text/html; charset=utf-8']),
  ...['invoice-sample.zip', 'csv-sample.zip'].map(name => ['/guides/assets/' + name, 'guides/assets/' + name, 'application/zip']),
  ['/guides/assets/file-recipes.py', 'guides/assets/file-recipes.py', 'text/plain; charset=utf-8'],
  ['/guides/assets/barcelona-pre-schematic-v1.pptx', 'guides/assets/barcelona-pre-schematic-v1.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'],
  ['/guides/assets/architecture-preview.png', 'guides/assets/architecture-preview.png', 'image/png'],
  ['/guides/assets/architecture-sources.json', 'guides/assets/architecture-sources.json', 'application/json; charset=utf-8'],
  ...['architecture-request.txt', 'architecture-request-v2.txt', 'complaint-research-request.txt'].map(name => ['/guides/assets/' + name, 'guides/assets/' + name, 'text/plain; charset=utf-8']),
  ['/sitemap.xml', 'sitemap.xml', 'application/xml; charset=utf-8'],
  ['/robots.txt', 'robots.txt', 'text/plain; charset=utf-8'],
]) assets.set(route, { body: await readFile(new URL(`./public/${file}`, import.meta.url)), type });
assets.set('/index.html', assets.get('/'));
assets.set('/guides', assets.get('/guides/'));
for (const [route, asset] of [...assets]) {
  if (route.startsWith('/guides/') && asset.type.startsWith('text/html') && !route.endsWith('/')) assets.set(route + '/', asset);
}
assets.set('/health', { body: Buffer.from('ok\n'), type: 'text/plain; charset=utf-8' });
const downloads = new Map();
const directory = process.env.TASK_RELAY_DOWNLOAD_DIR || fileURLToPath(new URL('./downloads/', import.meta.url));
for (const name of ['Task-Relay-0.12.1-beta.1-arm64.dmg', 'Task-Relay-0.12.1-beta.1-source.tar.gz',
  'Task-Relay-0.13.0-beta.1-arm64.dmg', 'Task-Relay-0.13.0-beta.1-source.tar.gz',
  'Task-Relay-0.13.26-arm64.dmg', 'Task-Relay-0.13.26-source.tar.gz']) {
  for (const suffix of ['', '.sha256']) {
    const filename = name + suffix, path = join(directory, filename);
    const info = await stat(path); // Fail deployment health if an advertised asset is missing.
    if (!info.isFile() || !info.size) throw Error('Missing release asset: ' + filename);
    downloads.set('/downloads/' + filename, {path, filename, size: info.size,
      type: suffix ? 'text/plain; charset=utf-8' : name.endsWith('.dmg') ? 'application/x-apple-diskimage' : 'application/gzip'});
  }
}
const server = createServer(async (request, response) => {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.setHeader('Content-Security-Policy', "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'");
  if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405, {Allow:'GET, HEAD'}); response.end(); return; }
  const route = (request.url || '/').split('?')[0];
  const latestKind = Object.keys(assetKinds).find(kind => route === '/downloads/latest/' + assetKinds[kind]);
  if (latestKind || route === '/api/release') {
    const release = await resolveRelease();
    response.setHeader('Cache-Control', 'no-store');
    if (latestKind) { response.writeHead(302, {Location: release.assets[latestKind].url}); response.end(); return; }
    const body = JSON.stringify(release);
    response.writeHead(200, {'Content-Type':'application/json; charset=utf-8', 'Content-Length':Buffer.byteLength(body)});
    response.end(request.method === 'HEAD' ? undefined : body); return;
  }
  const download = downloads.get(route);
  if (download) {
    let start = 0, end = download.size - 1, status = 200;
    if (request.headers.range) {
      const match = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range);
      if (match) { start = Number(match[1]); end = match[2] ? Math.min(Number(match[2]), end) : end; }
      if (!match || !Number.isSafeInteger(start) || start > end || start >= download.size) {
        response.writeHead(416, {'Content-Range':`bytes */${download.size}`}); response.end(); return;
      }
      status = 206; response.setHeader('Content-Range', `bytes ${start}-${end}/${download.size}`);
    }
    response.writeHead(status, {'Content-Type':download.type, 'Content-Length':end-start+1,
      'Content-Disposition':`attachment; filename="${download.filename}"`, 'Accept-Ranges':'bytes',
      'Cache-Control':'public, max-age=31536000, immutable'});
    if (request.method === 'HEAD') { response.end(); return; }
    const stream = createReadStream(download.path, {start,end});
    stream.on('error', () => response.destroy()); response.on('close', () => stream.destroy());
    stream.pipe(response); return;
  }
  const asset = assets.get(route);
  if (!asset) { response.writeHead(404, {'Content-Type':'text/plain; charset=utf-8'}); response.end(request.method === 'HEAD' ? undefined : 'Not found\n'); return; }
  const body = ['/', '/index.html', '/llms.txt'].includes(route) ? Buffer.from(renderRelease(asset.body.toString(), await resolveRelease())) : asset.body;
  response.writeHead(200, {'Content-Type':asset.type, 'Content-Length':body.length, 'Cache-Control':'public, max-age=0, must-revalidate'});
  response.end(request.method === 'HEAD' ? undefined : body);
});
server.listen(Number(process.env.PORT || 3000), '0.0.0.0', () => console.log(`Task Relay website listening on port ${server.address().port}`));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close());
