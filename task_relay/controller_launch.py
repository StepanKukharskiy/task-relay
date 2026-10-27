"""One exclusive controller launch and at most one explicitly committed restart."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from . import runtime_process


def run(directory,python,controller,run_id):
    directory=Path(directory)
    claim=directory/'launcher-started.json'
    if (directory/'restart-committed.json').exists():
        raise ValueError('Existing restart evidence; never adopt or replay another launch')
    # A crash after this claim never authorizes another invocation.
    with claim.open('x') as stream:
        json.dump(dict(pid=os.getpid(),at=time.time(),run=run_id,
            policy='one fresh authorized run; one committed scheduler restart'),stream)
        stream.flush();os.fsync(stream.fileno())
    journal=directory/'launcher-journal.jsonl'
    def record(value):
        with journal.open('a') as stream:
            stream.write(json.dumps(value,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
    argv=runtime_process.command(python,controller)
    env=runtime_process.environment()
    for ordinal in (1,2):
        record(dict(event='controller_launch',ordinal=ordinal,command=argv,at=time.time()))
        result=subprocess.run(argv,env=env)
        record(dict(event='controller_exit',ordinal=ordinal,returncode=result.returncode,at=time.time()))
        if result.returncode!=75 or ordinal==2:return result.returncode
        receipt=directory/'restart-committed.json'
        if receipt.is_symlink() or not receipt.is_file():raise ValueError('Missing committed restart receipt')
        raw=receipt.read_bytes();value=json.loads(raw)
        if value.get('run')!=run_id:raise ValueError('Restart receipt belongs to another run')
        record(dict(event='restart_admitted',receipt_sha256=hashlib.sha256(raw).hexdigest(),at=time.time()))
