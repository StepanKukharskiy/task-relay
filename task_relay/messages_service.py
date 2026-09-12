#!/usr/bin/env python3
"""Build/install/manage the user's Messages Relay login service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time

from task_relay.host import HOST
from task_relay.relay_paths import PATHS, ASSETS, CHECKOUT
ROOT = PATHS.install
APP = (ROOT if CHECKOUT else PATHS.data/'build') / 'Messages Relay.app'
INSTALLED_APP = Path.home() / 'Applications/Messages Relay.app'
LABEL = 'com.personal.taskrelay.messages'
DATA = PATHS.messages
LOGS = Path.home() / 'Library/Logs/Messages Relay'
PLIST = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
ICON_SOURCE = PATHS.messages_icon
MENU_ICON_SOURCE = PATHS.menu_icon
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def refresh_icon():
    # copytree preserves the old bundle timestamp, so macOS can retain its
    # placeholder icon. Refresh metadata without changing the signed contents.
    os.utime(INSTALLED_APP, None)
    for duplicate in (APP, PATHS.data / 'messages-app-before-icon-v1.app'):
        if duplicate.exists():
            # An already unregistered backup can return -10814. It must not
            # prevent refreshing the installed app after a successful start.
            subprocess.run([LSREGISTER, '-u', str(duplicate)], capture_output=True)
    subprocess.run([LSREGISTER, '-f', str(INSTALLED_APP)], check=True)


def build_icon(destination):
    iconset = PATHS.data / 'messages-icon.iconset'
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            subprocess.run(['/usr/bin/sips', '-z', str(size * scale), str(size * scale),
                            str(ICON_SOURCE), '--out', str(iconset / name)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['/usr/bin/iconutil', '--convert', 'icns', '--output', str(destination), str(iconset)], check=True)


def definition():
    return {'Label': LABEL, 'ProgramArguments': [str(INSTALLED_APP / 'Contents/MacOS/MessagesRelay')],
            'WorkingDirectory': str(Path.home()), 'RunAtLoad': True, 'KeepAlive': True,
            'LimitLoadToSessionType': 'Aqua', 'ThrottleInterval': 20, 'ExitTimeOut': 12,
            'StandardOutPath': str(LOGS / 'service.log'), 'StandardErrorPath': str(LOGS / 'service-error.log'),
            'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin', **PATHS.environment()},
            'Umask': 0o077}


def runtime_configuration():
    return {'python':str(Path(sys.executable).resolve()),'root':str(ROOT),
            'data':str(PATHS.data),'workspaces':str(PATHS.workspaces),
            'generated':str(PATHS.generated),'messages':str(PATHS.messages)}


def build():
    source = ASSETS / 'macos/Launcher.swift'
    contents = APP / 'Contents'
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    (contents / 'Resources').mkdir(parents=True, exist_ok=True)
    python = str(Path(sys.executable).resolve())
    template_builder = ASSETS / 'macos/BuildMenuTemplate.swift'
    fingerprint = hashlib.sha256(source.read_bytes() + template_builder.read_bytes() + python.encode() + str(ROOT).encode()
                                 + ICON_SOURCE.read_bytes() + MENU_ICON_SOURCE.read_bytes() + json.dumps(runtime_configuration(),sort_keys=True).encode()).hexdigest()
    stamp = PATHS.data / 'messages-service-build.sha256'
    binary = contents / 'MacOS/MessagesRelay'
    if stamp.exists() and stamp.read_text() == fingerprint and binary.exists():
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(APP)], check=True)
        return
    info = {'CFBundleExecutable': 'MessagesRelay', 'CFBundleIdentifier': LABEL,
            'CFBundleName': 'Messages Relay', 'CFBundleDisplayName': 'Messages Relay',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': '4', 'CFBundleShortVersionString': '1.3',
            'CFBundleIconFile': 'MessagesRelay.icns',
            'LSUIElement': True, 'LSMinimumSystemVersion': '14.0',
            'NSAppleEventsUsageDescription': 'Messages Relay sends agent replies to your paired Messages conversation.',
            'NSDocumentsFolderUsageDescription': 'Messages Relay runs your local agent relay in Documents/task-relay.'}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    (contents / 'Resources/runtime.json').write_text(json.dumps(runtime_configuration()) + '\n')
    build_icon(contents / 'Resources/MessagesRelay.icns')
    cache = PATHS.data / 'messages-swift-cache'
    cache.mkdir(parents=True, exist_ok=True)
    template = PATHS.data / 'messages-menu-template.png'
    subprocess.run(['/usr/bin/xcrun', 'swift', '-module-cache-path', str(cache),
                    str(template_builder), str(MENU_ICON_SOURCE), str(template)], check=True)
    subprocess.run(['/usr/bin/sips', '-z', '40', '40', str(template),
                    '--out', str(contents / 'Resources/MenuBarTemplate.png')],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['/usr/bin/xcrun', 'swiftc', '-module-cache-path', str(cache),
                    '-O', str(source), '-o', str(binary), '-framework', 'AppKit'], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier', LABEL, str(APP)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(APP)], check=True)
    stamp.write_text(fingerprint)


def install():
    binary = APP / 'Contents/MacOS/MessagesRelay'
    if not binary.is_file():
        raise SystemExit('Build the app first: python3 messages_service.py build')
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(APP)], check=True)
    runtime=json.loads((APP/'Contents/Resources/runtime.json').read_text())
    if runtime!=runtime_configuration():raise SystemExit('Rebuild the Messages app for the selected path configuration before installing.')
    installed_config=INSTALLED_APP/'Contents/Resources/runtime.json'
    if installed_config.exists():
        prior=json.loads(installed_config.read_text())
        if prior.get('root')!=str(ROOT):raise SystemExit('The installed Messages app belongs to another checkout; it was preserved.')
        if Path(prior.get('data',str(ROOT/'private')))!=PATHS.data:
            raise SystemExit('The installed Messages app uses another data root. An explicit migration is required; it was preserved.')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOGS.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('service.log', 'service-error.log'):
        path = LOGS / name
        path.touch(exist_ok=True)
        path.chmod(0o600)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    target = f'gui/{os.getuid()}/{LABEL}'
    HOST.launchctl(['bootout', target], capture_output=True)
    # bootout can return while launchd is still removing the job. Do not copy a
    # running executable or bootstrap over that asynchronous shutdown.
    for _ in range(60):
        if HOST.launchctl(['print', target], capture_output=True).returncode:
            break
        time.sleep(.25)
    else:
        raise SystemExit('The previous Messages service is still stopping. Retry install shortly.')
    # launchd must be able to execute the app and open logs before it has any
    # Documents access. Use the normal per-user Applications/Library locations.
    INSTALLED_APP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP, INSTALLED_APP, dirs_exist_ok=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(INSTALLED_APP)], check=True)
    PLIST.write_bytes(plistlib.dumps(definition()))
    PLIST.chmod(0o600)
    HOST.launchctl(['enable', target], check=True)
    HOST.launchctl(['bootstrap', f'gui/{os.getuid()}', str(PLIST)], check=True)
    refresh_icon()
    print('Messages Relay installed and started. Closing Terminal will not stop it.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'install', 'status', 'restart', 'stop'])
    args = parser.parse_args()
    HOST.require_macos("Messages service")
    target = f'gui/{os.getuid()}/{LABEL}'
    if args.command == 'build':
        build()
        print('Built and verified:', APP)
    elif args.command == 'install':
        install()
    elif args.command == 'status':
        result = HOST.launchctl(['print', target], capture_output=True, text=True)
        print('Installed and loaded' if result.returncode == 0 else 'Not loaded')
        path = DATA / 'health.json'
        if path.exists():
            print(path.read_text())
    elif args.command == 'stop':
        # Retain the plist and paired state; disabled jobs do not start at the next login.
        HOST.launchctl(['disable', target], check=True)
        HOST.launchctl(['bootout', target], capture_output=True)
        print('Messages Relay stopped. Run install to enable it again. Pairing is preserved.')
    elif args.command == 'restart':
        HOST.launchctl(['kickstart', '-k', target], check=True)


if __name__ == '__main__':
    main()
