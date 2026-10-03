"""Read-only version observations; no import, replacement or rebuild authority."""
from contextlib import closing
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import time

from .desktop_plans import DesktopPlanError, _database
from .filesystem import FILES, Grant, AccessDenied
from .host import UnsupportedHost
from .relay_paths import PATHS

MAX_BYTES = 20_000_000
MAX_TOTAL = 50_000_000
TEXT_BYTES = 200_000
NOTE = ('Earlier version supplied means recorded input dependencies, not proof of semantic use. '
        'Inspection does not change frozen files, historical decisions or execution authorization.')


def identity(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def metadata(db, artifact):
    row = db.execute('SELECT id,run,task,attempt,path,sha256,bytes FROM production_artifacts WHERE id=?', (artifact,)).fetchone()
    return dict(row) if row else None


def impacts(db, run, old, new=None):
    """Follow verified frozen edges, stopping at the explicitly revised version."""
    from orchestrator.artifact_dependencies import trace
    graph = trace(db, [old['id']], direction='downstream', limit=200)
    hashes = {a['id']: a['sha256'] for a in graph['artifacts']}
    reached = {old['id']}
    while True:
        more = {e['output'] for e in graph['dependencies']
                if e['input'] in reached and hashes.get(e['input']) == e['input_sha256']
                and (not new or e['output'] != new['id'])}
        if more <= reached:
            break
        reached.update(more)
    tasks = []
    for row in db.execute('''SELECT t.id,t.latest,p.frozen FROM production_tasks t
        LEFT JOIN production_attempts p ON p.id=t.latest WHERE t.run=?''', (run,)):
        if not row['latest'] or (new and row['latest'] == new.get('attempt')):
            continue
        frozen = json.loads(row['frozen']) if row['frozen'] else {}
        supplied = [i['artifact'] for i in frozen.get('inputs', []) if i.get('artifact') in reached
                    and hashes.get(i['artifact']) == i.get('sha256')]
        outputs = [a['id'] for a in graph['artifacts'] if a['id'] in reached and a['run'] == run
                   and a['task'] == row['id'] and a['attempt'] == row['latest']]
        if supplied or outputs:
            tasks.append(dict(task=row['id'], attempt=row['latest'], inputs=supplied, outputs=outputs))
    return dict(tasks=tasks, incomplete=graph['truncated'] or bool(graph['gaps']))


def recorded(state, run):
    """Only recorded revision intent or explicit replacement establishes a pair."""
    db = state.db
    from orchestrator.artifact_replacements import view
    result = []
    for head in view(db, run)['heads']:
        if not head['history']:
            continue
        event = head['history'][-1]
        versions = []
        for decision in (event['old_decision'], event['new_decision']):
            row = db.execute('SELECT artifact FROM production_decisions WHERE id=?', (decision,)).fetchone()
            versions.append(metadata(db, row[0]) if row else None)
        if not all(versions):
            continue
        old, new = versions
        result.append(dict(id=identity('replacement', run, event['id']), kind='replacement',
                           label='Replacement selected', old=old, new=new, receipt=event['id'],
                           **impacts(db, run, old, new)))
    for row in db.execute('''SELECT t.id,t.latest,p.frozen FROM production_tasks t
        JOIN production_attempts p ON p.id=t.latest WHERE t.run=?''', (run,)):
        frozen = json.loads(row['frozen'])
        previous = frozen.get('revision', {}).get('previous_attempt')
        if not previous:
            continue
        for item in frozen.get('inputs', []):
            if not item.get('previous_delivery') or not item.get('artifact'):
                continue
            old = metadata(db, item['artifact'])
            if (not old or old['run'] != run or old['task'] != row['id']
                    or old['attempt'] != previous or old['sha256'] != item.get('sha256')):
                continue
            new = db.execute('SELECT id FROM production_artifacts WHERE run=? AND task=? AND attempt=? AND path=?',
                             (run, row['id'], row['latest'], old['path'])).fetchone()
            if not new:
                continue
            new = metadata(db, new[0])
            result.append(dict(id=identity('revision', run, old['id'], new['id']), kind='revision',
                               label='File revised' if old['sha256'] != new['sha256'] else 'Revision · same content',
                               old=old, new=new, revised_task=row['id'], **impacts(db, run, old, new)))
    return result


def bindings(state, run, paths=PATHS):
    """Recover original attachment identity from exact saved capture paths."""
    db = state.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_plan_inputs'").fetchone():
        return []
    row = db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()
    if not row:
        raise DesktopPlanError('That saved job is unavailable.')
    job = json.loads(row[0]).get('origin', {}).get('job_request_id')
    plans = db.execute('''SELECT p.context,i.manifest,d.job_id,d.request_id FROM production_plans p
        JOIN desktop_plan_requests d ON d.job_id=p.request_id
        JOIN desktop_plan_inputs i ON i.request_id=d.request_id
        WHERE p.run=? OR (? IS NOT NULL AND json_extract(p.options,'$.job_request_id')=?)
        ORDER BY p.created LIMIT 51''', (run, job, job)).fetchall()
    known = set()
    current = db.execute('SELECT context FROM production_plans WHERE run=?', (run,)).fetchone()
    if current:
        known = {s['artifact'] for s in json.loads(current[0]).get('sources', [])}
    result = []
    seen = set()
    for plan in plans:
        allowed = known | {s['artifact'] for s in json.loads(plan['context']).get('sources', [])}
        for item in json.loads(plan['manifest']):
            token = identity('original', run, plan['request_id'], item['source'], item['path'], item['sha256'])
            if token in seen:
                continue
            seen.add(token)
            snapshot = Path(item['path'])
            root = paths.data / 'route-inputs' / str(plan['job_id']) / 'desktop-files'
            if not snapshot.is_absolute() or not snapshot.is_relative_to(root) or '..' in snapshot.parts:
                continue
            rows = db.execute('SELECT id FROM production_artifacts WHERE source=? AND sha256=? AND bytes=?',
                              (item['path'], item['sha256'], item['bytes'])).fetchall()
            artifacts = [r[0] for r in rows if r[0] in allowed]
            result.append(dict(token=token, name=item['name'], source=item['source'], snapshot=item['path'],
                               sha256=item['sha256'], bytes=item['bytes'], root=str(root),
                               artifacts=artifacts, scope_partial=len(plans)>=51))
    return result


def read_version(path, *, limit=MAX_BYTES, expected=None, grant_root=None):
    """Use the host adapter's exact-file grant and reject swaps and special files."""
    path = Path(path)
    if not path.is_absolute():
        raise DesktopPlanError('The recorded source location is unavailable.')
    root = Path(grant_root) if grant_root else path.parent
    grant = Grant(root, 'Inspect exact user-selected file version', reads=frozenset([path.relative_to(root).as_posix()]))
    with FILES.open(grant, str(path)) as fd:
        before = os.fstat(fd)
        if before.st_size > limit:
            raise DesktopPlanError('File exceeds the bounded inspection limit.')
        digest = hashlib.sha256()
        raw = bytearray() if before.st_size <= TEXT_BYTES else None
        size = 0
        while True:
            chunk = os.read(fd, min(65536, limit-size+1))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise DesktopPlanError('File grew beyond the inspection limit.')
            digest.update(chunk)
            if raw is not None:
                if size <= TEXT_BYTES:
                    raw.extend(chunk)
                else:
                    raw = None
        after = os.fstat(fd)
    stamp = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if stamp(before) != stamp(after) or size != after.st_size:
        raise DesktopPlanError('File changed during inspection. Check it again.')
    # Atomic saves can replace the pathname while the first descriptor remains
    # perfectly stable. Reopen through the same no-follow grant before reporting.
    with FILES.open(grant, str(path)) as current_fd:
        if stamp(os.fstat(current_fd)) != stamp(after):
            raise DesktopPlanError('File location changed during inspection. Check it again.')
    value = dict(sha256=digest.hexdigest(), bytes=size, raw=bytes(raw) if raw is not None else None)
    if expected and value['sha256'] != expected:
        raise DesktopPlanError('File version changed. Check and compare the current versions again.')
    return value


def check_sources(run, paths=PATHS):
    from .desktop_workspace import ReadState, _view
    if not isinstance(run, str) or len(run) > 80:
        raise DesktopPlanError('Choose an exact saved job.')
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        state = ReadState(db, paths)
        view = _view(state, run, paths)
        originals, changes, used = [], [], 0
        sources = bindings(state, run, paths)
        for source in sources[:10]:
            item = dict(token=source['token'], name=source['name'], old_sha256=source['sha256'])
            try:
                current = read_version(source['source'], limit=min(MAX_BYTES, MAX_TOTAL-used))
                used += current['bytes']
                item.update(status='unchanged' if current['sha256'] == source['sha256'] else 'changed',
                            new_sha256=current['sha256'], new_bytes=current['bytes'])
                if item['status'] == 'changed':
                    affected = set()
                    incomplete = not bool(source['artifacts'])
                    for artifact in source['artifacts']:
                        impact = impacts(db, run, metadata(db, artifact))
                        incomplete |= impact['incomplete']
                        # Result-free running consumers and produced results
                        # remain distinguishable in the inspection card.
                        affected.update((t['task'], t['attempt']) for t in impact['tasks'])
                    changes.append(dict(id=identity('external', source['token'], current['sha256']),
                        token=source['token'], kind='external', label='Source updated outside Relay',
                        old=dict(path=source['name'], sha256=source['sha256'], bytes=source['bytes'],
                                 id=source['artifacts'][0] if len(source['artifacts']) == 1 else None),
                        new=dict(path=source['name'], sha256=current['sha256'], bytes=current['bytes']),
                        tasks=[dict(task=t, attempt=a) for t,a in sorted(affected)], incomplete=incomplete))
            except (OSError, ValueError, UnsupportedHost) as exc:
                item.update(status='unavailable', reason=str(exc))
            originals.append(item)
        return dict(run=run, revision=view['revision'], checked_at=time.time(), originals=originals,
                    partial=len(sources)>10 or any(s['scope_partial'] for s in sources),
                    changes=changes, note=NOTE)


def compare(run, change, new_sha256=None, paths=PATHS):
    from .desktop_workspace import ReadState
    if not isinstance(run, str) or len(run) > 80 or not isinstance(change, str) or not re.fullmatch('[a-f0-9]{64}', change):
        raise DesktopPlanError('Choose an exact recorded file change.')
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        state = ReadState(db, paths)
        item = next((c for c in recorded(state, run) if c['id'] == change), None)
        if item:
            old, new = item['old'], item['new']
            versions = []
            from .production_control import root
            store = root(state).resolve()
            for a in (old,new):
                if a['bytes'] > MAX_BYTES:
                    versions.append(dict(raw=None))
                    continue
                blob = Path(db.execute('SELECT blob FROM production_artifacts WHERE id=?', (a['id'],)).fetchone()[0])
                version = read_version(blob, expected=a['sha256'], grant_root=store)
                if version['bytes'] != a['bytes']:
                    raise DesktopPlanError('Saved version metadata changed. Inspect the registered file.')
                versions.append(version)
        else:
            if not isinstance(new_sha256, str) or not re.fullmatch('[a-f0-9]{64}', new_sha256):
                raise DesktopPlanError('Check original source files before comparing a change.')
            source = next((s for s in bindings(state, run, paths)
                           if identity('external', s['token'], new_sha256) == change), None)
            if not source:
                raise DesktopPlanError('That change is outside this saved job.')
            old = dict(path=source['name'], sha256=source['sha256'], bytes=source['bytes'])
            before = read_version(source['snapshot'], expected=source['sha256'], grant_root=source['root'])
            after = read_version(source['source'], expected=new_sha256)
            new = dict(path=source['name'], sha256=after['sha256'], bytes=after['bytes'])
            versions = [before,after]
        result = dict(old=old, new=new, same_content=old['sha256'] == new['sha256'], diff=None,
                      truncated=False, note=NOTE)
        try:
            texts = [v['raw'].decode('utf-8') for v in versions]
            if any('\x00' in t for t in texts):
                raise ValueError('Binary content')
            lines = [t.splitlines(keepends=True) for t in texts]
            if any(len(t) > 4000 for t in lines):
                raise ValueError('Text preview limit')
            difference = ''.join(difflib.unified_diff(*lines, fromfile='Earlier saved version', tofile='Compared version'))
            result['diff'] = difference[:16000]
            result['truncated'] = len(difference) > 16000
            result['preview_note'] = 'Text changes' if result['diff'] else 'Content is identical.'
        except (AttributeError, UnicodeError, ValueError):
            result['preview_note'] = 'Recorded hashes differ; text comparison is unavailable for binary or larger files.' if not result['same_content'] else 'Recorded hashes are identical.'
        if any(a['bytes'] > MAX_BYTES for a in (old,new)):
            result['preview_note'] += ' Large-file contents were not rehashed in this comparison.'
        return result
