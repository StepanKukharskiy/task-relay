"""Frozen Safari runtime availability; discovery never launches a browser."""
import json
from pathlib import Path
from .relay_paths import PATHS
from . import computer_contract as native
from orchestrator.computer_contract import validate
from orchestrator.workers import atomic


def current(required=False, data=None):
    path=Path(data or PATHS.data)/'computer-worker-target.json'
    try:
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Safari target must not traverse symlinks.')
        value=validate(json.loads(path.read_text()))
        from .host_computer import SOURCE,require_host
        import hashlib
        require_host()
        if value['identity'].get('source_sha256')!=hashlib.sha256(SOURCE.read_bytes()).hexdigest():
            raise ValueError('Build and select the current Safari helper before planning.')
        return value
    except (OSError,ValueError,RuntimeError) as exc:
        if required:raise ValueError('Safari worker target unavailable: '+str(exc)) from None
        return None


def runtime(required=False):
    # Preserve explicitly selected scopes; otherwise offer the shipped launcher.
    selected=current()
    if selected:return selected
    try:
        from .host_computer import Observer,bundled_helper
        helper=Observer(bundled_helper())
        value={'mode':'new-scripting-window','helper':str(helper.app),'identity':helper.identity}
        return {**value,'selection':native.digest(value)}
    except (OSError,ValueError,RuntimeError) as exc:
        if required:raise ValueError('Safari worker unavailable: '+str(exc)) from None
        return None


def verify_policy(policy):
    selected=runtime(required=True)
    if native.managed_target(policy['spec']['target']):
        if selected.get('mode')!=policy['spec']['target']['mode'] or any(policy[k]!=selected[k] for k in ('helper','identity')):
            raise ValueError('Safari launcher changed after planning; approve a new scope.')
    elif selected!=policy:
        raise ValueError('Selected Safari authority changed after planning; approve a new scope.')


def select(helper,spec,*,data=None):
    spec=native.session_spec(spec)
    if spec['actions'] or spec['capture']:raise ValueError('Select a text-only worker target with an empty actions list.')
    value={'helper':str(helper.app),'identity':helper.identity,'spec':spec}
    value['selection']=native.digest(value)
    validate(value)
    # Validate the selected document now; dispatch will bind it afresh. No navigation.
    response=helper.call(native.request(spec['target'],spec['url'],'Select this window for explicitly approved Safari worker tasks.',False,spec['local_fixture']))
    native.validate_response(response,native.request(spec['target'],spec['url'],'Select this window for explicitly approved Safari worker tasks.',False,spec['local_fixture']))
    path=Path(data or PATHS.data)/'computer-worker-target.json'
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Safari target must not traverse symlinks.')
    path.parent.mkdir(parents=True,exist_ok=True)
    atomic(path,value)
    return value
