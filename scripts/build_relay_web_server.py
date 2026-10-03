#!/usr/bin/env python3
"""Prepare only the stateless web runtime for public hosting, never deploy it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ('task_relay/__init__.py', 'task_relay/portable_work.py',
           'task_relay/web_plugin.py', 'task_relay/assets/relay-reusable.html',
           'task_relay/assets/relay-reusable.css', 'task_relay/assets/relay-reusable.js',
           'task_relay/assets/companion.css', 'task_relay/assets/messages-icon.png')
HOST = ('Dockerfile', 'requirements.txt', 'railway.json', 'start.py')


def build(out):
    out = Path(out).absolute()
    receipt_path = out.parent / (out.name + '-receipt.json')
    if out.exists() or receipt_path.exists():
        raise ValueError('Choose a new directory; existing versions are preserved.')
    out.mkdir(parents=True, mode=0o700)
    for relative in RUNTIME:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for name in HOST:
        shutil.copyfile(ROOT / 'plugins/relay/server' / name, out / name)
    # No source tree, environment, profile, database, receipts or ignored state.
    receipt = {'schema': 'task-relay.web-deployment-build', 'version': 1,
               'deployed': False, 'published': False,
               'files': {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(out.rglob('*')) if p.is_file()}}
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    print(json.dumps(build(parser.parse_args().out), indent=2))
