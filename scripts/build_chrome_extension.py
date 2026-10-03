"""Build a portable, offline MV3 directory and reproducible Chrome ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    source = ROOT / 'extensions/chrome'
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'task-relay-chrome'
    target.mkdir(exist_ok=True)
    files = ['manifest.json', 'worker.js', 'extract.js', 'chatgpt.js', 'panel.html', 'panel.css', 'panel.js', 'portable.js']
    for name in files: shutil.copy2(source / name, target / name)
    shutil.copy2(ROOT / 'plugins/relay/assets/logo.png', target / 'logo.png')
    files.append('logo.png')
    archive = output / 'task-relay-chrome.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(files):
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16; bundle.writestr(item, (target / name).read_bytes())
    receipt = {'version': json.loads((target / 'manifest.json').read_text())['version'],
               'unpacked': str(target), 'zip': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
               'files': {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in sorted(files)},
               'published': False, 'installed': False}
    (output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', required=True)
    print(json.dumps(build(parser.parse_args().out), indent=2))


if __name__ == '__main__': main()
