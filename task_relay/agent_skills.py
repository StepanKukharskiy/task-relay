"""Publish bundled local agent instructions without replacing personal edits."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path

from . import __version__
from .filesystem import FILES, Grant
from .host import HOST

NAMES = ('relay-manage', 'relay-author')
BUNDLED = Path(__file__).parent / 'assets/skills'
RECEIPT = '.relay-skills.json'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unlinked(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('A linked skill location was preserved. Choose a regular folder for automatic installation.')


def read_receipt(root):
    unlinked(root / RECEIPT)
    path = root / RECEIPT
    if not path.exists():
        return {'version': 1, 'skills': {}}
    raw = path.read_bytes()
    if len(raw) > 100_000:
        raise ValueError('Skill installation receipt is too large; it was preserved.')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('skills'), dict):
        raise ValueError('Skill installation receipt needs inspection; it was preserved.')
    return value


def write(root, name, raw):
    grant = Grant(root, 'Relay bundled agent skill installation', writes=frozenset({name}))
    FILES.write(grant, name, raw)


def save(root, receipt):
    write(root, RECEIPT, (json.dumps(receipt, indent=2) + '\n').encode())


@contextmanager
def locked(root, host):
    unlinked(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / '.relay-skills.lock'
    unlinked(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as stream:
        host.lock(stream)
        yield


def sync_one(name, root, source, host):
    target = root / name
    raw = (source / name / 'SKILL.md').read_bytes()
    expected = digest(raw)
    with locked(root, host):
        receipt = read_receipt(root)
        previous = receipt['skills'].get(name, {})
        if not isinstance(previous, dict):
            raise ValueError('Skill installation receipt needs inspection; it was preserved.')
        prior_version = previous.get('version', '')
        if (re.fullmatch(r'\d+\.\d+\.\d+', prior_version) and
                tuple(map(int, prior_version.split('.'))) > tuple(map(int, __version__.split('.')))):
            raise ValueError('A newer Relay version manages this skill; its files were preserved.')
        unlinked(target)
        current = None
        if target.exists():
            if not target.is_dir() or {p.name for p in target.iterdir()} - {'SKILL.md'}:
                raise ValueError('Existing skill contains personal files; nothing was overwritten.')
            skill = target / 'SKILL.md'
            unlinked(skill)
            if skill.exists():
                if not skill.is_file() or skill.stat().st_size > 1_000_000:
                    raise ValueError('Existing skill needs inspection; nothing was overwritten.')
                current = digest(skill.read_bytes())
            elif not previous.get('pending_sha256'):
                raise ValueError('Existing incomplete skill was preserved.')
        if current != expected:
            allowed = {previous.get('sha256'), previous.get('pending_sha256')} - {None}
            if current is not None and current not in allowed:
                raise ValueError('Existing skill was edited or installed separately; nothing was overwritten.')
            # Write-ahead receipt recognizes either complete version after interruption.
            receipt['skills'][name] = dict(sha256=current, pending_sha256=expected, version=__version__)
            save(root, receipt)
            target.mkdir(exist_ok=True, mode=0o700)
            write(root, name + '/SKILL.md', raw)
        receipt['skills'][name] = dict(sha256=expected, version=__version__)
        save(root, receipt)
    return dict(name=name, path=str(target), status='ready', changed=current != expected)


def sync(*, host=HOST, source=BUNDLED):
    """App-open mutation, independent of services, credentials and job databases."""
    roots = host.agent_skill_roots()
    items = []
    for name in NAMES:
        # Reuse a previous user-scope location instead of creating duplicate names.
        candidates = [root for root in roots if (root / name).exists() or (root / name).is_symlink()]
        root = candidates[0] if candidates else roots[0]
        try:
            result = sync_one(name, root, source, host)
            if len(candidates) > 1:
                result['warning'] = 'Another copy exists in a legacy skill folder; both copies were retained.'
        except (OSError, ValueError) as exc:
            result = dict(name=name, path=str(root / name), status='attention', changed=False,
                          message=str(exc) if isinstance(exc, ValueError) else 'Skill installation could not finish. Check folder access, then retry.')
        items.append(result)
    ready = all(item['status'] == 'ready' for item in items)
    return dict(ready=ready, skills=items,
                message=('Relay skills are ready for ChatGPT Desktop / Codex. Start a new chat; restart the agent if they do not appear.' if ready else
                         'Some Relay skills need attention. Existing files were preserved; local Relay startup can continue.'))
