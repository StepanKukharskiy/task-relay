"""Bundle the optional Messages transport without a second visible application."""
from pathlib import Path
import plistlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    runtime = ROOT / 'desktop/src-tauri/resources/runtime'
    app = runtime / 'helpers/Messages Relay.app'
    contents = app / 'Contents'
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    (contents / 'Resources').mkdir(parents=True, exist_ok=True)
    # Retain the helper's bundle identifier; macOS may still require grants for
    # its new signed location. Never claim permission continuity from this ID.
    info = {'CFBundleExecutable': 'MessagesRelay', 'CFBundleIdentifier': 'com.personal.taskrelay.messages',
            'CFBundleName': 'Messages Relay', 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': '5', 'CFBundleShortVersionString': '1.4',
            'CFBundleIconFile': 'MessagesRelay.icns', 'LSUIElement': True,
            'LSMinimumSystemVersion': '14.0',
            'NSAppleEventsUsageDescription': 'Task Relay sends replies to your paired Messages conversation.'}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copy2(ROOT / 'desktop/src-tauri/icons/icon.icns', contents / 'Resources/MessagesRelay.icns')
    cache = ROOT / 'desktop/build/swift-cache'
    cache.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/usr/bin/xcrun', 'swiftc', '-module-cache-path', str(cache), '-O',
                    str(ROOT / 'task_relay/assets/macos/Launcher.swift'), '-o',
                    str(contents / 'MacOS/MessagesRelay'), '-framework', 'AppKit'], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier',
                    'com.personal.taskrelay.messages', str(app)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], check=True)
    print('Bundled and signature-verified the optional Messages helper. No service started.')


if __name__ == '__main__':
    main()
