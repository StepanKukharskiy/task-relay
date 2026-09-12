"""Startup readiness before provider workers run during a release switch."""
import os
import time
from . import credentials
from .relay_paths import PATHS


def startup(paths=PATHS, timeout=90):
    activation = paths.data / 'updates' / 'activation.json'
    if not activation.exists():
        return
    deadline = time.monotonic() + timeout
    while True:
        record = credentials.private_json(activation)
        target = record.get('target', {})
        if target.get('install') != str(paths.install):
            raise RuntimeError('Another release is selected; use task-relay update status or recover.')
        if record['phase'] in ('starting', 'active'):
            credentials.save(paths.data / 'updates' / 'ready.json',
                             dict(nonce=record['nonce'], pid=os.getpid(), install=str(paths.install)))
            if record['phase'] == 'active':
                return
        else:
            raise RuntimeError('Release activation is incomplete. Run task-relay update recover.')
        if time.monotonic() >= deadline:
            raise RuntimeError('Release activation was not committed. Run task-relay update recover.')
        time.sleep(.1)
