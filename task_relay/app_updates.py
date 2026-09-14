"""Desktop-only update discovery and durable, exact-candidate preparation.

GitHub supplies public metadata; installed certificate continuity authenticates
executable code. No source update, credential, or URL supplied by a webview is used.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.request
import urllib.error
import uuid

REPOSITORY = 'StepanKukharskiy/task-relay'
API = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=30'
DOWNLOADS = 'https://github.com/' + REPOSITORY + '/releases/download/'
PROTOCOL = 1
MAX_PACKAGE = 2_000_000_000
TERMINAL = {'complete', 'rolled_back', 'failed'}


class UpdateError(ValueError):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise UpdateError('Invalid app release version.')
    return tuple(map(int, value.split('.')))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise UpdateError('Linked update records are not supported.')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex)
    with temporary.open('x') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def read(path, default=None):
    path = Path(path)
    if not path.exists(): return default
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise UpdateError('Invalid update receipt. Preserve it for recovery.')
    return json.loads(path.read_text())


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'Task-Relay-App-Updater', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if not response.url.startswith('https://'):
                raise UpdateError('An update download redirected to an insecure address.')
            raw = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError):
        raise UpdateError('Could not reach GitHub. Check your connection and try Check for updates again.') from None
    if len(raw) > limit: raise UpdateError('Release metadata exceeds its size limit.')
    return json.loads(raw)


def candidate(release, manifest, arch, current, beta):
    """Validate every field before treating metadata as an installable candidate."""
    if release.get('draft') or (release.get('prerelease') and not beta): return None
    v = manifest.get('version')
    if version(v) <= version(current): return None
    tag = release.get('tag_name')
    if tag != 'v' + v or manifest.get('protocol') != PROTOCOL:
        raise UpdateError('This release needs a newer installer. Download it from the release page.')
    if manifest.get('platform') != 'macos' or manifest.get('arch') != arch: return None
    if manifest.get('channel') != ('beta' if release.get('prerelease') else 'stable'):
        raise UpdateError('App release channel does not match GitHub.')
    name = manifest.get('asset')
    if not isinstance(name, str) or not re.fullmatch(r'Task-Relay-[0-9.]+-macos-(arm64|x86_64)\.zip', name):
        raise UpdateError('Invalid app package name.')
    size, sha = manifest.get('bytes'), manifest.get('sha256')
    signer = manifest.get('signer_sha256')
    if type(size) is not int or not 0 < size <= MAX_PACKAGE or not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha):
        raise UpdateError('Invalid app package size or checksum.')
    if not isinstance(signer, str) or not re.fullmatch('[a-f0-9]{64}', signer):
        raise UpdateError('App release has no signing certificate identity.')
    assets = [a for a in release.get('assets', []) if a.get('name') == name]
    url = DOWNLOADS + tag + '/' + name
    if len(assets) != 1 or assets[0].get('browser_download_url') != url or assets[0].get('size') != size or assets[0].get('digest') != 'sha256:' + sha:
        raise UpdateError('GitHub asset does not match the app release manifest.')
    if manifest.get('data_policy') != 'unchanged':
        raise UpdateError('This release requires a reviewed data migration; automatic installation is unavailable.')
    result = {key: manifest[key] for key in ('version', 'platform', 'arch', 'channel', 'asset', 'bytes', 'sha256', 'signer_sha256', 'data_policy', 'protocol')}
    result.update(url=url, release_url='https://github.com/' + REPOSITORY + '/releases/tag/' + tag)
    result['id'] = identity(result)
    return result


class Updater:
    def __init__(self, host=None, root=None, clock=time.time, fetcher=fetch):
        if host is None:
            from .app_updates_macos import MacUpdater
            host = MacUpdater()
        self.host, self.clock, self.fetcher = host, clock, fetcher
        self.root = Path(root or host.update_folder())
        self.cache = self.root / 'status.json'
        self.receipt = self.root / 'attempt.json'

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink(): raise UpdateError('Update folder cannot be linked.')
        with (self.root / 'update.lock').open('a') as stream:
            try: self.host.lock(stream)
            except BlockingIOError: raise UpdateError('Another update operation is already running.') from None
            yield

    def save(self, record):
        events = record.setdefault('events', [])
        if not events or events[-1]['phase'] != record['phase']:
            events.append({'phase': record['phase'], 'at': self.clock()})
        # Keep each completed/failed attempt even when a later update is prepared.
        write(Path(record['folder']) / 'receipt.json', record)
        write(self.receipt, record)

    def status(self):
        support = self.host.support()
        saved = read(self.cache, {})
        attempt = read(self.receipt, {})
        # A dead worker is never silently restarted. The user sees its receipt.
        if attempt.get('phase') in ('downloading', 'preparing', 'launching', 'installing', 'recovering') and not self.host.worker_alive(attempt):
            attempt = {**attempt, 'phase': 'interrupted', 'error': 'The update was interrupted. Review recovery before trying again.'}
        return {**support, **saved, 'attempt': {k: attempt[k] for k in ('id', 'phase', 'version', 'error', 'progress') if k in attempt}}

    def check(self, beta=False):
        if type(beta) is not bool: raise UpdateError('Choose a release channel.')
        support = self.host.support()
        if not support['supported']: raise UpdateError(support['detail'])
        with self.lock():
            selected = None
            releases = self.fetcher(API, 1_000_000)
            if not isinstance(releases, list): raise UpdateError('Could not read app releases.')
            for release in releases:
                if release.get('draft') or (release.get('prerelease') and not beta): continue
                tag = release.get('tag_name', '')
                if not re.fullmatch(r'v\d{1,5}\.\d{1,5}\.\d{1,5}', tag): continue
                if version(tag[1:]) <= version(support['installed']): continue
                names = [a for a in release.get('assets', []) if a.get('name') == 'app-update-macos-' + support['arch'] + '.json']
                if not names: continue  # A wheel/DMG alone is not an app update.
                url = DOWNLOADS + tag + '/' + names[0]['name']
                if len(names) != 1 or names[0].get('browser_download_url') != url:
                    raise UpdateError('Invalid app release metadata URL.')
                item = candidate(release, self.fetcher(url, 16384), support['arch'], support['installed'], beta)
                if item and (not selected or version(item['version']) > version(selected['version'])): selected = item
            write(self.cache, {'checked': self.clock(), 'beta': beta, 'candidate': selected})
        return self.status()

    def download(self, ident):
        with self.lock():
            item = (read(self.cache, {}) or {}).get('candidate')
            if not item or ident != item['id']: raise UpdateError('Release selection changed. Check for updates again.')
            old = read(self.receipt, {})
            if old and old.get('phase') not in TERMINAL:
                raise UpdateError('An update is already prepared or needs recovery. It was not repeated.')
            folder = self.root / uuid.uuid4().hex
            folder.mkdir(mode=0o700)
            record = {'id': folder.name, 'phase': 'preparing', 'version': item['version'], 'candidate': item,
                      'folder': str(folder), 'started': self.clock()}
            self.save(record)
            try:
                self.host.prepare_worker(folder)
                process = self.host.spawn_worker(folder, 'download', self.root)
                record.update(pid=process.pid, phase='downloading')
                self.save(record)
            except Exception as exc:
                record.update(phase='failed', error=str(exc)); self.save(record)
                raise
        return self.status()

    def install(self, ident):
        with self.lock():
            record = read(self.receipt, {})
            if record.get('id') != ident or record.get('phase') != 'ready':
                raise UpdateError('Review a verified download before installing. No installation was repeated.')
            self.host.validate_prepared(record)
            self.host.preflight(record)
            record.update(phase='launching', approved=self.clock())
            self.save(record)
            try:
                process = self.host.spawn_worker(Path(record['folder']), 'install', self.root)
                record['pid'] = process.pid
                self.save(record)
            except Exception as exc:
                record.update(phase='needs_attention', error=str(exc)); self.save(record)
                raise
        return self.status()

    def recover(self, ident):
        with self.lock():
            record = read(self.receipt, {})
            if record.get('id') != ident or record.get('phase') in TERMINAL or self.host.worker_alive(record):
                raise UpdateError('No interrupted update is available for recovery.')
            if not record.get('approved'):
                record.update(phase='failed', error='Prepared download discarded. You can check and download again.')
                self.save(record)
            else:
                record['phase'] = 'recovering'
                self.save(record)
                try:
                    process = self.host.spawn_worker(Path(record['folder']), 'recover', self.root)
                    record['pid'] = process.pid
                    self.save(record)
                except Exception as exc:
                    record.update(phase='needs_attention', error=str(exc)); self.save(record)
                    raise
        return self.status()


def worker(mode, root):
    updater = Updater(root=root)
    # Parent publishes PID/intent while holding the lock; worker waits for commit.
    for _ in range(300):
        try:
            with updater.lock():
                record = read(updater.receipt, {})
                if record.get('pid') != os.getpid(): raise UpdateError('Update worker identity changed.')
                save = lambda: updater.save(record)
                try:
                    if mode == 'download':
                        updater.host.prepare(record, save)
                        record['phase'] = 'ready'; save()
                    elif mode == 'install':
                        updater.host.install(record, save)
                    elif mode == 'recover':
                        updater.host.recover(record, save)
                    else: raise UpdateError('Unknown update worker operation.')
                except Exception as exc:
                    record.update(phase=record['phase'] if record['phase'] == 'rolled_back' else 'failed' if mode == 'download' else 'needs_attention', error=str(exc)); save()
                return
        except UpdateError as exc:
            if 'already running' not in str(exc): raise
            time.sleep(.1)
    raise UpdateError('Update worker could not acquire its receipt lock.')


if __name__ == '__main__':
    import sys
    worker(sys.argv[1], Path(sys.argv[2]))
