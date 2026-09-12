"""Fresh, bounded roadmap evidence from known project roots, never model paths."""
import hashlib
import os
from pathlib import Path
import re
import stat
import time
from task_relay import file_tools

MAX_BYTES = 64000
MAX_PROJECTS = 3


def normalized(value):
    return ' '.join(re.findall(r'\w+', str(value).casefold()))


def read(root):
    root = Path(root).resolve()
    path = root / 'ROADMAP.md'
    result = {'project': Path(root).name, 'path': str(path), 'read_at': time.time()}
    try:
        with file_tools.Workspace(root).open('ROADMAP.md') as fd, os.fdopen(os.dup(fd), 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('Roadmap is not a regular file.')
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > MAX_BYTES:
            raise ValueError('Roadmap exceeds the 64 KB evidence limit; no partial priorities supplied.')
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Roadmap changed while being read; request fresh evidence.')
        result.update(status='ready', sha256=hashlib.sha256(raw).hexdigest(),
                      modified_at=after.st_mtime, content=raw.decode('utf-8'))
    except FileNotFoundError:
        result.update(status='missing', error='No root ROADMAP.md exists. Do not infer priorities from task titles.')
    except (OSError, ValueError, UnicodeError) as exc:
        result.update(status='unavailable', error=str(exc))
    return result


def context(tasks, workflows, focus, prompt, history=()):
    projects = {}
    broad = {Path('/'), Path.home(), Path.home() / 'Documents'}
    for item in tasks + workflows:
        if not item.get('cwd'):
            continue
        root = Path(item['cwd']).resolve()
        if root in broad:
            continue
        aliases = projects.setdefault(str(root), set())
        aliases.add(normalized(root.name))
        if item in workflows and item.get('name'):
            aliases.add(normalized(item['name']))
    def matching(text):
        value = ' ' + normalized(text) + ' '
        return [root for root, aliases in projects.items()
                if any(alias and ' ' + alias + ' ' in value for alias in aliases)]
    selected = matching(prompt)
    source = 'current_message'
    if not selected and focus:
        selected = matching(focus)
        source = 'reply_focus'
    # Only exact earlier USER messages supply conversational project scope.
    # Assistant claims and task titles never become project priorities.
    if not selected:
        for turn in reversed(history):
            selected = matching(turn.get('prompt', ''))
            if selected:
                source = 'previous_user_message'
                break
    if not selected and len(projects) == 1:
        selected = list(projects)
        source = 'only_known_project'
    result = {'selection_source': source, 'available_projects': sorted(projects), 'documents': []}
    if not selected or len(selected) > MAX_PROJECTS:
        result.update(status='needs_project', reason='Select one relevant project (up to three for comparison); no roadmap priorities have been read.')
        return result
    result.update(status='selected', documents=[read(root) for root in selected])
    return result
