"""macOS app update mechanisms. No elevation, quarantine removal, or data rollback."""
from contextlib import ExitStack, closing
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import shutil
import signal
import sqlite3
import stat
import subprocess
import tempfile
import time
import urllib.request
import zipfile

from .app_updates import UpdateError, digest, version
from . import app_bundle
from .host import HOST
from .relay_paths import PATHS, Paths

RUNTIME = Path('Contents/Resources/resources/runtime')
EXECUTABLE = Path('Contents/MacOS/task-relay-desktop')


def run(args, check=True, timeout=60, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True, timeout=timeout, **kwargs)
    if check and result.returncode:
        raise UpdateError('macOS could not complete ' + str(args[0]) + '. Existing recovery files were retained.')
    return result


def signer(app):
    app_bundle.verify(app)
    with tempfile.TemporaryDirectory(prefix='relay-certificate-') as folder:
        prefix = str(Path(folder) / 'certificate')
        run(['/usr/bin/codesign', '--display', '--extract-certificates=' + prefix, app])
        certificate = Path(prefix + '0')
        if not certificate.is_file():
            raise UpdateError('This app has no signing certificate. Install a signed build manually once.')
        return digest(certificate)


def extract(package, destination):
    """Extract a bounded plain-file bundle; reject links, traversal and duplicates."""
    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        if len(infos) > 100_000 or sum(i.file_size for i in infos) > 6_000_000_000:
            raise UpdateError('App archive exceeds its extraction limit.')
        names = set()
        for info in infos:
            parts = Path(info.filename).parts
            mode = info.external_attr >> 16
            if (not parts or parts[0] != 'Task Relay.app' or '..' in parts or '\\' in info.filename or
                    info.filename in names or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise UpdateError('App archive contains an unsafe or duplicate entry.')
            names.add(info.filename)
        for info in infos:
            target = destination / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod((info.external_attr >> 16) & 0o777 or 0o755)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open('xb') as dst: shutil.copyfileobj(src, dst)
                target.chmod((info.external_attr >> 16) & 0o777 or 0o644)
    return destination / 'Task Relay.app'


class MacUpdater:
    def __init__(self, installed=None, paths=PATHS):
        runtime = Path(os.environ.get('TASK_RELAY_DESKTOP_RUNTIME_ROOT', ''))
        self.installed = Path(installed or os.environ.get('TASK_RELAY_UPDATE_APP') or
                              (runtime.parents[3] if len(runtime.parents) > 3 else '/unavailable'))
        self.runtime = self.installed / RUNTIME
        self.paths = paths

    def update_folder(self):
        key = hashlib.sha256(str(self.installed).encode()).hexdigest()[:16]
        return Path.home() / 'Library/Application Support/Task Relay App Updates' / key

    def support(self):
        info = self.installed / 'Contents/Info.plist'
        supported = (HOST.platform == 'darwin' and self.installed.suffix == '.app' and info.is_file() and
                     not self.installed.is_symlink() and (self.installed / EXECUTABLE).is_file())
        installed = plistlib.loads(info.read_bytes()).get('CFBundleShortVersionString') if supported else None
        return {'supported': supported, 'installed': installed, 'arch': platform.machine(),
                'detail': '' if supported else 'App installation is available in the packaged Mac app.'}

    def lock(self, stream): HOST.lock(stream)

    def worker_alive(self, record):
        pid = record.get('pid')
        if type(pid) is not int or pid < 1: return False
        result = run(['/bin/ps', '-p', pid, '-o', 'command='], check=False)
        command = result.stdout.decode(errors='replace')
        return result.returncode == 0 and record.get('folder', '\0') in command and 'app_updates' in command

    def prepare_worker(self, folder):
        HOST.require_macos('App updates')
        # The interpreter, libraries and helper must survive replacement of Contents.
        if shutil.disk_usage(folder).free < 4_000_000_000:
            raise UpdateError('Free at least 4 GB before downloading an app update.')
        run(['/usr/bin/ditto', self.runtime, folder / 'worker'], timeout=180)

    def spawn_worker(self, folder, mode, root):
        worker = folder / 'worker'
        code = "import sys;sys.path.insert(0,sys.argv[1]);from task_relay.app_updates import worker;worker(sys.argv[2],sys.argv[3])"
        env = {**os.environ, **self.paths.environment(), 'TASK_RELAY_UPDATE_APP': str(self.installed),
               'TASK_RELAY_DESKTOP_RUNTIME_ROOT': str(self.runtime), 'PYTHONDONTWRITEBYTECODE': '1'}
        env.pop('PYTHONHOME', None); env.pop('PYTHONPATH', None)
        with (folder / 'worker.log').open('ab') as log:
            return subprocess.Popen([str(worker / 'python/bin/python3'), '-I', '-B', '-c', code, str(worker / 'app'), mode, str(root)],
                                    env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                                    cwd=folder)

    def services(self):
        from .desktop_macos import DesktopService
        from .desktop_messages import MessagesService
        return [DesktopService(self.runtime, self.paths), MessagesService(self.runtime, self.paths)]

    def service_snapshot(self):
        result = []
        for service in self.services():
            owner, spec = service._owner()
            loaded = service._loaded()
            if owner == 'other' or (owner == 'none' and loaded) or service.path.is_symlink():
                raise UpdateError('An external service uses this installation. Review its handoff before updating the app.')
            result.append({'path': str(service.path), 'sha256': digest(service.path) if spec else None,
                           'label': spec['Label'] if spec else None, 'loaded': loaded})
        return result

    def idle(self):
        if not self.paths.state.exists(): return
        checks = {
            'backend_jobs': ('queued', 'running', 'waiting'), 'provider_jobs': ('queued', 'running'),
            'production_attempts': ('launching', 'running', 'cancelling'),
            'orchestrator_chats': ('queued', 'sending', 'running', 'processing'),
            'production_plans': ('queued', 'planning'), 'task_routes': ('queued', 'opening', 'submitting'),
            'browser_jobs': ('queued', 'submitting', 'running'), 'internal_jobs': ('queued', 'running'),
            'task_creations': ('queued', 'connecting', 'creating', 'created_pending', 'naming', 'opening', 'submitting'),
            'media_outbox': ('sending',), 'messages_delivery': ('sending',), 'desktop_creations': ('queued',),
            'desktop_commands': ('queued', 'submitting', 'sending', 'processing'),
        }
        with closing(sqlite3.connect(self.paths.state.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            for table in ('outbox', 'outbox_parts'):
                columns = [r[1] for r in db.execute('PRAGMA table_info(' + table + ')')]
                if not columns: continue
                if 'sent' not in columns: raise UpdateError('Delivery storage changed; update requires review.')
                if db.execute('SELECT 1 FROM ' + table + ' WHERE sent=0 LIMIT 1').fetchone():
                    raise UpdateError('Wait for pending replies to finish before installing.')
            for table, states in checks.items():
                col = 'state' if table == 'production_attempts' else 'status'
                columns = [r[1] for r in db.execute('PRAGMA table_info(' + table + ')')]
                if not columns: continue
                if col not in columns: raise UpdateError('Task storage changed; update requires review.')
                if db.execute('SELECT 1 FROM ' + table + ' WHERE ' + col + ' IN (' + ','.join('?' for _ in states) + ') LIMIT 1', states).fetchone():
                    raise UpdateError('Wait for running and queued work to finish, then install again.')
        if any((self.paths.messages / name).exists() for name in ('state.sqlite', 'providers.sqlite')):
            raise UpdateError('Legacy Messages storage needs a reviewed handoff before app updates.')

    def prepare(self, record, save):
        item = record['candidate']; folder = Path(record['folder'])
        if signer(self.installed) != item['signer_sha256']:
            raise UpdateError('This release uses a different signing identity. Install it manually after reviewing the publisher.')
        package = folder / 'package.zip'
        request = urllib.request.Request(item['url'], headers={'User-Agent': 'Task-Relay-App-Updater'})
        with urllib.request.urlopen(request, timeout=30) as response, package.open('xb') as output:
            if not response.url.startswith('https://'): raise UpdateError('Insecure package redirect.')
            count = 0; last = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > item['bytes']: raise UpdateError('App download exceeds its declared size.')
                output.write(chunk)
                if time.monotonic() - last > 1:
                    record['progress'] = round(100 * count / item['bytes']); save(); last = time.monotonic()
            output.flush(); os.fsync(output.fileno())
        if count != item['bytes'] or digest(package) != item['sha256']:
            raise UpdateError('The download checksum did not match. Your installed app was preserved.')
        app = extract(package, folder / 'candidate')
        if signer(app) != item['signer_sha256']: raise UpdateError('Downloaded app signing identity does not match.')
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleShortVersionString') != item['version'] or info.get('CFBundleExecutable') != 'task-relay-desktop':
            raise UpdateError('Downloaded app version does not match the release.')
        minimum = tuple(map(int, info.get('LSMinimumSystemVersion', '14.0').split('.')))
        current_os = tuple(map(int, platform.mac_ver()[0].split('.')))
        if (current_os + (0, 0, 0))[:3] < (minimum + (0, 0, 0))[:3]:
            raise UpdateError('This app requires a newer macOS version.')
        architecture = run(['/usr/bin/lipo', '-archs', app / EXECUTABLE]).stdout.decode().split()
        if item['arch'] not in architecture: raise UpdateError('Downloaded app does not support this Mac.')
        if item['channel'] == 'stable':
            run(['/usr/sbin/spctl', '--assess', '--type', 'execute', app])
        record.update(candidate_app=str(app), candidate_digest=app_bundle.bundle_digest(app),
                      installed_digest=app_bundle.bundle_digest(self.installed), installed_inode=self.installed.stat().st_ino,
                      installed=str(self.installed), bindings=self.paths.environment(), services=self.service_snapshot())
        self.compatible(app, folder / 'download-probe')
        record['progress'] = 100; save()

    def validate_prepared(self, record):
        if record.get('installed') != str(self.installed) or record.get('bindings') != self.paths.environment():
            raise UpdateError('The app or data location changed after download. Prepare a new update.')
        app = Path(record['candidate_app'])
        if (app_bundle.bundle_digest(app) != record['candidate_digest'] or
                app_bundle.bundle_digest(self.installed) != record['installed_digest'] or
                self.installed.stat().st_ino != record['installed_inode'] or
                signer(app) != record['candidate']['signer_sha256'] or
                signer(self.installed) != record['candidate']['signer_sha256']):
            raise UpdateError('The prepared app identity changed. Your installation was preserved.')
        if version(record['version']) <= version(self.support()['installed']):
            raise UpdateError('Only a newer app version can be installed.')

    def preflight(self, record):
        if self.service_snapshot() != record['services']:
            raise UpdateError('Service settings changed since download. Prepare the update again.')
        if not os.access(self.installed / 'Contents', os.W_OK) or not os.access(self.installed.parent, os.W_OK):
            raise UpdateError('This app location needs administrator access. Install the update manually in Applications.')
        self.idle()

    def compatible(self, app, folder):
        if not self.paths.state.exists(): return
        from .updates import snapshot
        from . import migrations
        folder.mkdir()
        runtime = app / RUNTIME
        baseline = folder / 'before.sqlite'
        snapshot(self.paths.state, baseline)
        test = folder / 'probe.sqlite'
        snapshot(baseline, test)
        probe_data = folder / 'probe-data'
        probe_data.mkdir()
        code = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                'from task_relay.bridge import State;s=State(Path(sys.argv[2]));s.db.close()')
        env = {**os.environ, **self.paths.environment(), 'TASK_RELAY_DATA_DIR': str(probe_data)}
        # -I ignores PYTHONDONTWRITEBYTECODE: -B is required to keep signed code immutable.
        result = run([runtime / 'python/bin/python3', '-I', '-B', '-c', code, runtime / 'app', test],
                     check=False, timeout=45, env=env)
        if result.returncode:
            raise UpdateError('The candidate could not reopen a copy of your data. Your installed app was preserved.')
        with closing(sqlite3.connect(baseline.as_uri() + '?mode=ro', uri=True)) as before, closing(sqlite3.connect(test)) as after:
            migrations.check(after)
            if migrations.fingerprint(before) != migrations.fingerprint(after):
                raise UpdateError('This update changes saved data. A reviewed migration is required; your data was preserved.')

    def app_pids(self):
        target = str(self.installed / EXECUTABLE)
        result = run(['/bin/ps', '-axo', 'pid=,command=']).stdout.decode(errors='replace')
        return [int(parts[0]) for line in result.splitlines() if len(parts := line.strip().split(None, 1)) == 2 and parts[1] == target]

    def stop_owners(self, record, save):
        # Stop intent covers all owners, including a crash between bootout and receipt.
        record['stop_intent'] = True; save()
        for pid in self.app_pids(): os.kill(pid, signal.SIGTERM)
        for service, item in reversed(list(zip(self.services(), record['services']))):
            if item['loaded'] and service._loaded():
                result = service._command(['bootout', f'gui/{os.getuid()}/' + item['label']])
                if result.returncode or not service._wait_unloaded(): raise UpdateError('A service did not stop. Review update recovery.')
        for _ in range(100):
            if not self.app_pids(): break
            time.sleep(.1)
        if self.app_pids(): raise UpdateError('Task Relay did not close. Review update recovery.')

    def data_locks(self):
        from .updates import lock
        stack = ExitStack()
        try:
            if self.paths.data.exists():
                for name in ('bridge.lock', 'setup.lock'):
                    stack.enter_context(lock(self.paths.data / name, timeout=10))
                if self.paths.messages.exists():
                    stack.enter_context(lock(self.paths.messages / 'pilot.lock', timeout=10))
            return stack
        except BaseException:
            stack.close(); raise

    def telegram_ready(self, started):
        with closing(sqlite3.connect(self.paths.state.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            for key in ('health:poll', 'health:scan', 'health:production', 'health:orchestrator-chat'):
                row = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
                import json
                stamp = json.loads(row[0]).get('last_success', 0) if row else 0
                if not isinstance(stamp, (int, float)) or stamp < started or not 0 <= time.time() - stamp < 20:
                    return False
        return True

    def start_owners(self, record, save):
        started = time.time()
        record['restart_intent'] = started; save()
        for service, item in zip(self.services(), record['services']):
            if item['loaded'] and not service._loaded():
                result = service._command(['bootstrap', f'gui/{os.getuid()}', item['path']])
                if result.returncode: raise UpdateError('A service did not restart. Review update recovery.')
        for _ in range(90):
            ready = True
            for service, item in zip(self.services(), record['services']):
                if not item['loaded']: continue
                status = service.status()
                stamp = service._heartbeat() if item['label'] == 'com.personal.codex-telegram' else None
                if stamp is None and (self.paths.messages / 'health.json').is_file():
                    from .app_updates import read
                    stamp = read(self.paths.messages / 'health.json', {}).get('updated_at', 0)
                if item['label'] == 'com.personal.codex-telegram':
                    ready &= self.telegram_ready(started)
                ready &= bool(status.get('healthy') and isinstance(stamp, (int, float)) and stamp >= started)
            if ready: return
            time.sleep(.5)
        raise UpdateError('Fresh service readiness was not confirmed. Review recovery; no work was resubmitted.')

    def reopen(self):
        run(['/usr/bin/open', '-a', self.installed])
        for _ in range(100):
            if self.app_pids(): return
            time.sleep(.1)
        raise UpdateError('The app did not confirm restart. Recovery files were retained.')

    def install(self, record, save):
        self.validate_prepared(record); self.preflight(record)
        record.update(phase='installing', holding=str(self.installed.parent / ('.task-relay-update-' + record['id'])))
        save()
        try:
            self.stop_owners(record, save)
            with self.data_locks():
                self.idle()
                # Check again with owners stopped, including code and exact service definitions.
                self.validate_prepared(record)
                for service, item in zip(self.services(), record['services']):
                    if (digest(service.path) if service.path.exists() else None) != item['sha256']:
                        raise UpdateError('A service definition changed during shutdown.')
                self.compatible(Path(record['candidate_app']), Path(record['folder']) / 'stopped-probe')
                if self.paths.state.exists():
                    from .updates import snapshot
                    backup = Path(record['folder']) / 'state-before.sqlite'
                    snapshot(self.paths.state, backup)
                    record['database_backup_sha256'] = digest(backup)
                record['replacement_intent'] = True; save()
                app_bundle.replace_contents(self.installed, Path(record['candidate_app']), Path(record['holding']))
                record['replaced'] = True; save()
            self.start_owners(record, save)
            record['phase'] = 'complete'; save()
            self.reopen()
        except Exception:
            # No new owner has run: safe automatic restoration of code only.
            if not record.get('restart_intent'):
                self.recover(record, save)
            raise

    def recover(self, record, save):
        if record.get('installed') != str(self.installed) or record.get('bindings') != self.paths.environment():
            raise UpdateError('Recovery belongs to another app or data location.')
        if self.installed.is_symlink() or self.installed.stat().st_ino != record['installed_inode']:
            raise UpdateError('Installed app root changed. Manual recovery is required.')
        for service, item in zip(self.services(), record['services']):
            if (digest(service.path) if service.path.exists() else None) != item['sha256']:
                raise UpdateError('Service definitions changed; automatic recovery is unavailable.')
        self.idle()
        self.stop_owners(record, save)
        with self.data_locks():
            self.idle()
            holding = Path(record.get('holding', '/unavailable'))
            previous = holding / 'previous-contents'
            if holding.is_symlink() or previous.is_symlink():
                raise UpdateError('Recovery contents are linked. Manual inspection is required.')
            if previous.is_dir():
                # Materialize a candidate only for signature and data compatibility checks.
                rollback = Path(record['folder']) / ('rollback-' + str(time.time_ns())) / 'previous-bundle'
                rollback.mkdir(parents=True)
                run(['/usr/bin/ditto', previous, rollback / 'Contents'], timeout=180)
                if app_bundle.bundle_digest(rollback) != record['installed_digest']:
                    raise UpdateError('Recovery app identity changed. Saved data was preserved.')
                app_bundle.verify(rollback)
                self.compatible(rollback, rollback.parent / 'probe')
                app_bundle.restore_contents(self.installed, holding)
            elif app_bundle.bundle_digest(self.installed) != record['installed_digest']:
                raise UpdateError('Previous app is unavailable. Manual recovery is required.')
        if app_bundle.bundle_digest(self.installed) != record['installed_digest']:
            raise UpdateError('Previous app restoration did not verify. Services remain stopped.')
        self.start_owners(record, save)
        record['phase'] = 'rolled_back'; save()
        self.reopen()
