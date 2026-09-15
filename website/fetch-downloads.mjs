// Build-time fetch of reviewed immutable downloads; no credentials or app data.
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

export async function fetchDownloads(manifest, directory, fetcher = fetch) {
  await mkdir(directory, { recursive: true });
  for (const item of manifest) {
    if (!/^Task-Relay-[0-9.]+(?:-beta\.[0-9]+)?-(?:arm64\.dmg|source\.tar\.gz)(?:\.sha256)?$/.test(item.name)
        || !/^[a-f0-9]{64}$/.test(item.sha256) || !Number.isSafeInteger(item.bytes) || item.bytes <= 0 || item.bytes > 300_000_000)
      throw Error('Invalid release asset manifest');
    const url = new URL(item.url);
    const github = url.origin === 'https://github.com' && url.pathname.startsWith('/StepanKukharskiy/task-relay/releases/download/');
    const legacy = url.origin === 'https://task-relay-website-production.up.railway.app' && url.pathname === '/downloads/' + item.name;
    if ((!github && !legacy) || url.search || url.hash || !url.pathname.endsWith('/' + item.name)) throw Error('Unapproved asset URL');
    const temporary = join(directory, item.name + '.partial');
    try {
      const response = await fetcher(item.url, { signal: AbortSignal.timeout(300_000) });
      if (!response.ok || !response.body) throw Error('Asset download failed: ' + item.name);
      let bytes = 0; const digest = createHash('sha256');
      await writeFile(temporary, '', { flag: 'wx' });
      for await (const chunk of response.body) {
        bytes += chunk.byteLength;
        if (bytes > item.bytes) throw Error('Asset size exceeded: ' + item.name);
        digest.update(chunk); await writeFile(temporary, chunk, { flag: 'a' });
      }
      if (bytes !== item.bytes || digest.digest('hex') !== item.sha256) throw Error('Asset checksum mismatch: ' + item.name);
      await rename(temporary, join(directory, item.name));
    } catch (error) { await rm(temporary, { force: true }); throw error; }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await fetchDownloads(JSON.parse(await readFile(new URL('./downloads.json', import.meta.url))), fileURLToPath(new URL('./downloads/', import.meta.url)));
}
