"""macOS discovery and management adapter over the existing app updater."""
from pathlib import Path
import plistlib
import os
import re
import sqlite3
import subprocess

from .app_updates import Updater, UpdateError, read
from .app_updates_macos import MacUpdater, RUNTIME, signer

PACKAGE = Path(__file__).resolve().parent.parent


def current_app(package=PACKAGE):
    for parent in package.parents:
        if parent.suffix == '.app' and parent / RUNTIME / 'app' == package:
            return parent
    return None


def describe(app):
    app = Path(app).absolute()
    if app.is_symlink():
        raise ValueError('Linked app installations require manual inspection.')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.taskrelay.desktop':
        raise ValueError('Expected a Task Relay app.')
    command = app / RUNTIME / 'relay'
    available = command.is_file() and os.access(command, os.X_OK)
    return dict(path=str(app), version=info.get('CFBundleShortVersionString'),
                management_available=available, command=[str(command), 'manage'] if available else None)


def discover(app=None):
    found = []
    candidates = [Path('/Applications/Task Relay.app'), Path.home() / 'Applications/Task Relay.app']
    if app:
        candidates = [Path(app).expanduser().absolute()]
    own = current_app()
    if not app and own is not None and own not in candidates:
        candidates.append(own)
    for path in candidates:
        if not path.exists() and not path.is_symlink():
            continue
        try:
            found.append(describe(path))
        except (OSError, ValueError, plistlib.InvalidFileException):
            found.append(dict(path=str(path), management_available=False, error='App metadata is unreadable or has an unexpected identity.'))
    return found


class Manager:
    def __init__(self, paths, app=None, *, package=PACKAGE):
        own = current_app(package)
        selected = Path(app).expanduser().absolute() if app else own
        if selected is None:
            raise UpdateError('Run the management command returned by discover for the intended app. Source/package updates use task-relay update.')
        if selected.suffix != '.app' or selected.is_symlink():
            raise UpdateError('Select the original, unlinked Task Relay.app path.')
        self.host = MacUpdater(installed=selected, paths=paths)
        self.updater = Updater(host=self.host)
        self.installed_runtime = own == selected
        if not self.installed_runtime:
            # A copied helper may recover only its own exact current attempt.
            # Do not let a different checkout or another retained helper operate
            # the installation using mismatched code, receipts or data bindings.
            record = read(self.updater.receipt, {})
            folder = Path(record.get('folder', '/unavailable'))
            if (not re.fullmatch('[a-f0-9]{32}', record.get('id', ''))
                    or folder != self.updater.root / record['id']
                    or package != folder / 'worker/app'
                    or record.get('installed') != str(selected)
                    or record.get('bindings') != paths.environment()):
                raise UpdateError('This helper does not own the current update attempt and saved data binding.')

    def require_installed_runtime(self):
        if not self.installed_runtime:
            raise UpdateError('Retained helpers support status, diagnostics, receipts and recovery only. Use the installed app for new updates.')

    def diagnose(self):
        from .diagnostics import inspect
        result = dict(configuration=inspect(self.host.paths), updater=self.updater.status(),
                      scope='Local checks only; no provider calls, messages, service changes or job execution.')
        try:
            result['signer_sha256'] = signer(self.host.installed)
            result['signature_verified'] = True
        except (OSError, ValueError, subprocess.SubprocessError):
            result['signature_verified'] = False
        try:
            self.host.idle()
            result['update_admission'] = dict(allowed=True, scope='Idle-work check only; full installation preflight still applies.')
        except (OSError, ValueError, sqlite3.Error) as exc:
            result['update_admission'] = dict(allowed=False, reason=str(exc))
        result['services'] = []
        for service in self.host.services():
            status = service.status()
            result['services'].append({key: status.get(key) for key in ('owner', 'loaded', 'healthy', 'shared_data')})
        return result

    def receipts(self, attempt=None):
        if attempt is not None and not re.fullmatch('[a-f0-9]{32}', attempt):
            raise ValueError('Choose an exact update attempt ID from update-status or update-receipts.')
        root = self.updater.root
        if root.is_symlink():
            raise UpdateError('Linked update storage requires manual inspection.')
        folders = [root / attempt] if attempt else [p for p in root.glob('*') if re.fullmatch('[a-f0-9]{32}', p.name) and not p.is_symlink()]
        total = len(folders)
        if not attempt:
            folders = sorted(folders, key=lambda p: p.stat().st_mtime, reverse=True)[:50]
        items = []
        current = read(self.updater.receipt, {}).get('id')
        for folder in folders:
            if attempt and folder.is_symlink():
                raise UpdateError('Linked update attempt requires manual inspection.')
            if not re.fullmatch('[a-f0-9]{32}', folder.name) or folder.is_symlink():
                continue
            path = folder / 'receipt.json'
            if not path.is_file():
                if attempt:
                    raise UpdateError('No retained receipt exists for that update attempt.')
                continue
            record = read(path, {})
            if record.get('id') != folder.name or record.get('folder') != str(folder) or record.get('installed', str(self.host.installed)) != str(self.host.installed):
                raise UpdateError('Update receipt identity is inconsistent; preserve it for inspection.')
            item = {key: record[key] for key in ('id', 'version', 'phase', 'started', 'approved', 'events', 'database_backup_sha256') if key in record}
            item.update(receipt=str(path), current=record['id'] == current, management_helper_available=False)
            helper = folder / 'worker/relay'
            if item['current'] and helper.is_file() and not helper.is_symlink():
                bindings = record.get('bindings')
                if bindings == self.host.paths.environment():
                    item['management_helper_available'] = True
                    item['recovery_command'] = ['env', *(key+'='+value for key, value in bindings.items()),
                        str(helper), 'manage', '--app', str(self.host.installed), 'update-recover', '--attempt', record['id']]
            items.append(item)
        return dict(root=str(root), items=items, more=total > len(folders),
                    scope='At most 50 recent attempts; select an exact ID for older receipts. Original journals and backups remain in place.')
