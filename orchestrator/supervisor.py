"""Detached process owner. No model interpretation controls scheduler state."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


try:
    from host_runtime import HOST
except ImportError:
    from task_relay.host import HOST


def atomic(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value) + '\n'); os.replace(tmp, path)


def stop(proc):
    HOST.stop_tree(proc)


def main():
    control = Path(sys.argv[1]).resolve(); token = sys.argv[2]
    spec = json.loads((control / 'launch.json').read_text())
    if token != spec['token']:
        raise ValueError('Dispatch identity mismatch')
    if spec.get('host_support_sha256')!=hashlib.sha256((control/'host_runtime.py').read_bytes()).hexdigest():
        raise ValueError('Frozen host support changed before worker startup')
    support=spec.get('host_support_files',{})
    if HOST.platform=='win32' and set(support)!={'host_windows.py'}:
        raise ValueError('Frozen Windows process support is missing')
    for name,digest in support.items():
        if name!='host_windows.py' or hashlib.sha256((control/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Frozen native host support changed before worker startup')
    # Exclusive receipt protects against an accidental second supervisor invocation.
    with (control / 'supervisor.claim').open('x') as f:
        f.write(str(os.getpid()))
    start = time.time(); proc = None; reason = None; usage = []; tools = 0; thread = None
    cursor = 0; pending = b''; drained = False
    last_event = None; activity = 'waiting_for_response'; last_progress = 0
    identity=HOST.process_identity(os.getpid())
    atomic(control / 'started.json', {'token': token, 'supervisor_pid': os.getpid(), 'started': start,
                                    'supervisor_identity':identity})
    command = spec.get('registered_command') or [spec['executable'], 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral',
        '--skip-git-repo-check', '--json', '-m', spec['backend']['model'],
        '-c', 'model_reasoning_effort=' + json.dumps(spec['backend']['reasoning']),
        '-c', 'approval_policy="never"', '-s', 'workspace-write', '-C', spec['workspace'],
        '--output-schema', str(control / 'schema.json'),
        '-o', str(Path(spec['workspace']) / '.relay' / 'result.json'), '-']
    try:
        if (control / 'cancel.json').exists():
            atomic(control / 'done.json', {'token': token, 'exit_code': -1, 'reason': 'cancelled',
                'usage': [], 'tool_calls': 0, 'elapsed_seconds': time.time() - start})
            return
        with (control / 'events.jsonl').open('wb') as out, (control / 'stderr.txt').open('wb') as err, (control / 'prompt.txt').open('rb') as prompt:
            proc = HOST.spawn(command, stdin=prompt, stdout=out, stderr=err)
            atomic(control / 'started.json', {'token': token, 'supervisor_pid': os.getpid(),
                'child_pid': proc.pid, 'started': start, 'command': command,'supervisor_identity':identity})
            while True:
                with (control / 'events.jsonl').open('rb') as stream:
                    stream.seek(cursor); new = stream.read(); cursor = stream.tell()
                lines = (pending + new).split(b'\n'); pending = lines.pop()
                for line in lines:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event,dict):continue
                    last_event = time.time()
                    if event.get('type') == 'item.started':
                        activity = {'command_execution':'running_command','mcp_tool_call':'using_tool',
                                    'web_search':'searching_web'}.get(event.get('item',{}).get('type'),'processing_response')
                    elif event.get('type') in ('item.completed','turn.started','thread.started'):
                        activity = 'waiting_for_response'
                    if event.get('type') == 'thread.started':
                        thread = event.get('thread_id')
                    if event.get('type') == 'turn.completed':
                        usage.append(event.get('usage', {}))
                    if event.get('type') == 'turn.failed':
                        reason = reason or 'turn_failed'
                    if event.get('type') == 'item.started' and event.get('item', {}).get('type') in ('command_execution', 'mcp_tool_call', 'web_search'):
                        tools += 1
                if time.time()-last_progress>=2:
                    # Best-effort display telemetry; never changes execution or limits.
                    try:
                        atomic(control/'progress.json',{'token':token,'heartbeat_at':time.time(),
                            'last_event_at':last_event,'activity':activity,'tool_calls':tools,'usage':usage})
                    except OSError:pass
                    last_progress=time.time()
                if proc.poll() is not None:
                    if drained:
                        break
                    drained = True
                    continue
                if (control / 'cancel.json').exists():
                    reason = 'cancelled'
                elif time.time() - start > spec['limits']['seconds']:
                    reason = 'time_limit'
                elif tools > spec['limits']['tool_calls']:
                    reason = 'tool_limit'
                if reason:
                    stop(proc)
                    # One more iteration drains final events and usage.
                    continue
                time.sleep(.2)
        receipt = {'token': token, 'exit_code': proc.returncode, 'reason': reason,
            'thread_id': thread, 'usage': usage, 'tool_calls': tools, 'started': start,
            'finished': time.time(), 'elapsed_seconds': time.time() - start}
    except BaseException as exc:
        if proc:
            stop(proc)
        receipt = {'token': token, 'exit_code': -1, 'reason': type(exc).__name__ + ': ' + str(exc),
                   'usage': usage, 'tool_calls': tools, 'elapsed_seconds': time.time() - start}
    if proc is not None and HOST.platform=='win32':
        proc.close()  # End any surviving descendants before publishing completion.
    atomic(control / 'done.json', receipt)


if __name__ == '__main__':
    main()
