"""Package an already-built Mac app for direct beta distribution; never installs it."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from task_relay.runtime_check import check_packaged


def package(app, output):
    app, output = app.resolve(), output.resolve()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.taskrelay.desktop':
        raise ValueError('Select the built Task Relay app.')
    if output.exists():
        raise ValueError('Release artifacts are immutable. Choose a new filename.')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    check_packaged(app)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='task-relay-dmg-') as folder:
        root = Path(folder)
        subprocess.run(['ditto', str(app), str(root / 'Task Relay.app')], check=True)
        (root / 'Applications').symlink_to('/Applications')
        (root / 'Read me.txt').write_text('Task Relay — Mac beta\n\n'
            'Requires an Apple Silicon Mac running macOS 14 or newer.\n'
            'Drag Task Relay into Applications, eject this disk, then open Task Relay.\n'
            'The app includes Python. Follow its four setup steps; no Terminal is needed.\n\n'
            'This local beta is not an Apple-notarized public release.\n'
            'If macOS blocks it, follow Apple’s instructions for a trusted app:\n'
            'https://support.apple.com/guide/mac-help/mh40616/mac\n'
            'Privacy & Security → Open Anyway may be needed after trying to open it.\n'
            'Do not disable Gatekeeper. Managed Macs may disallow this beta.\n'
            'Updates can require refreshing existing macOS permission grants.\n\n'
            'First-time onboarding uses Telegram and your AI access. Messages remains\n'
            'an optional pilot with separate setup and permissions. Provider use may cost money.\n'
            'Existing service connections require a reviewed handoff; no silent replacement.\n')
        subprocess.run(['hdiutil', 'create', '-volname', 'Task Relay Beta', '-srcfolder', str(root),
                        '-format', 'UDZO', str(output)], check=True)
    subprocess.run(['hdiutil', 'verify', str(output)], check=True)
    digest = hashlib.file_digest(output.open('rb'), 'sha256').hexdigest()
    output.with_suffix('.dmg.sha256').write_text(digest + '  ' + output.name + '\n')
    return {'filename': output.name, 'sha256': digest, 'bytes': output.stat().st_size,
            'version': info['CFBundleShortVersionString'], 'architecture': 'arm64',
            'minimum_macos': '14.0', 'distribution': 'beta', 'notarized': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.app, args.output), indent=2))
