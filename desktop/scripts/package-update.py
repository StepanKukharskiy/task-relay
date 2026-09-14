"""Build the verified ZIP + metadata required by the in-app macOS updater.

Run on the reviewed, signed app. Upload both outputs to its matching GitHub
release. This script does not sign, notarize, publish or mutate the input app.
"""
import argparse
import json
from pathlib import Path
import plistlib
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from task_relay.app_updates import PROTOCOL, digest, version
from task_relay.app_updates_macos import run, signer
from task_relay.app_bundle import bundle_digest
from task_relay.runtime_check import check_packaged


def package(app, output, channel):
    app, output = Path(app).resolve(), Path(output).resolve()
    if output == app or output.is_relative_to(app): raise ValueError('Output must be outside the app.')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    v = info['CFBundleShortVersionString']; version(v)
    before = bundle_digest(app)
    certificate = signer(app)
    check_packaged(app)
    if channel == 'stable': run(['/usr/sbin/spctl', '--assess', '--type', 'execute', app])
    archs = run(['/usr/bin/lipo', '-archs', app / 'Contents/MacOS/task-relay-desktop']).stdout.decode().split()
    if len(archs) != 1 or archs[0] not in ('arm64', 'x86_64'): raise ValueError('Package one supported architecture per release manifest.')
    arch = archs[0]
    output.mkdir(parents=True, exist_ok=True)
    name = 'Task-Relay-' + v + '-macos-' + arch + '.zip'
    archive = output / name
    manifest_path = output / ('app-update-macos-' + arch + '.json')
    if archive.exists() or manifest_path.exists(): raise ValueError('Release assets cannot be overwritten.')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as stream:
        for path in sorted(app.rglob('*')):
            stream.write(path, 'Task Relay.app/' + path.relative_to(app).as_posix())
    if bundle_digest(app) != before: raise ValueError('App changed during packaging. Do not publish these files.')
    manifest = {'protocol': PROTOCOL, 'version': v, 'platform': 'macos', 'arch': arch, 'channel': channel,
                'asset': name, 'bytes': archive.stat().st_size, 'sha256': digest(archive),
                'signer_sha256': certificate, 'data_policy': 'unchanged'}
    with manifest_path.open('x') as stream: json.dump(manifest, stream, indent=2); stream.write('\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--channel', choices=('stable', 'beta'), required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.app, args.output, args.channel), indent=2))
