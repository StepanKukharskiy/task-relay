"""Read-only research visibility from saved host/tool receipts, never draft URLs."""
from contextlib import closing
import hashlib
import json
from pathlib import Path

from .desktop_plans import DesktopPlanError, _database
from .relay_paths import PATHS

LIMIT = 100
NOTE = 'Recorded page visits and search results show retrieval, not factual verification. Links merely mentioned in an answer are not listed as consulted sources. Uninstrumented shell/network activity is outside this view.'


def research_task(task):
    return not task.get('review_of') and bool(task.get('browser') or task.get('computer') or
        task.get('execution', {}).get('capability') == 'web.sources')


def proposal(plan):
    steps = [{'id': t['id'], 'objective': t['objective']} for t in (plan or {}).get('tasks', []) if research_task(t)]
    return {'steps': steps, 'pages': [], 'files': [], 'partial': False, 'note': NOTE,
            'advice': (plan or {}).get('origin', {}).get('research_advice'),
            'status': 'proposed' if steps else 'none',
            'message': 'Research is proposed. Sources appear after recorded retrieval.' if steps else 'No separate web research step is proposed.'}


def _load(root, name, expected=None):
    from orchestrator.runtime import safe_file
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Saved receipt directory is linked.')
    path = safe_file(root, name)
    if path.stat().st_size > 1_000_000:
        raise ValueError('Receipt exceeds the bounded source view.')
    raw = path.read_bytes()
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Saved research evidence changed.')
    return json.loads(raw)


def inspect(db, run, plan):
    from .orchestrator_web import public_url
    result = proposal(plan)
    result['status'] = 'recorded'
    pages, files = {}, {}
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    states = {r['id']: r['status'] for r in db.execute('SELECT id,status FROM production_tasks WHERE run=?', (run,))}
    for step in result['steps']:
        step['status'] = states.get(step['id'], 'unknown')

    def add(value, kind, attempt, receipt):
        try:
            url = public_url(value.get('url'))
        except (ValueError, TypeError):
            return
        entry = dict(url=url, title=str(value.get('title') or url)[:500], kind=kind,
                     task=attempt['task'], attempt=attempt['id'], receipt=receipt,
                     retrieved_at=value.get('retrieved_at'), sha256=value.get('sha256'))
        entry['id'] = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        if len(pages) >= LIMIT:
            result['partial'] = True
        else:
            pages[entry['id']] = entry

    for row in db.execute('SELECT id,task,frozen,session FROM production_attempts WHERE run=? ORDER BY rowid', (run,)):
        attempt = dict(row)
        frozen = json.loads(row['frozen'])
        for item in frozen.get('inputs', []):
            if item['path'].startswith(('request/', 'prior-outputs/')) or item['path'].endswith('conversation.json'):
                continue
            saved = db.execute('SELECT id,path,sha256,bytes,purpose FROM production_artifacts WHERE id=? AND (run IS NULL OR run!=?)', (item.get('artifact'), run)).fetchone()
            if saved and saved['sha256'] == item.get('sha256'):
                files[saved['id']] = dict(saved)
        if 'general_browser_actions' in tables:
            receipts = db.execute("SELECT id,result,created FROM general_browser_actions WHERE job=? AND status='observed' ORDER BY created,id LIMIT ?", (row['id'], LIMIT + 1)).fetchall()
            if len(receipts) > LIMIT:
                result['partial'] = True
            for receipt in receipts[:LIMIT]:
                try:
                    value = json.loads(receipt['result'] or '{}')
                    if value.get('observation') and isinstance(value.get('text'), str):
                        add({**value, 'retrieved_at': receipt['created']}, 'page', attempt, 'browser:' + receipt['id'])
                except (ValueError, TypeError, AttributeError):
                    result['partial'] = True
        if {'relay_computer_actions', 'relay_computer_assignments'} <= tables:
            receipts = db.execute('''SELECT a.id,a.receipt,a.created FROM relay_computer_actions a
                JOIN relay_computer_assignments s ON s.id=a.assignment
                WHERE s.request_key=? AND a.state='completed' ORDER BY a.created,a.id LIMIT ?''', ('worker:' + row['id'], LIMIT + 1)).fetchall()
            if len(receipts) > LIMIT:
                result['partial'] = True
            for receipt in receipts[:LIMIT]:
                try:
                    saved = json.loads(receipt['receipt'] or '{}')
                    folder = Path(saved['folder'])
                    evidence = _load(folder, 'evidence.json', saved['files']['evidence.json']['sha256'])
                    from orchestrator.runtime import safe_file, file_hash
                    if file_hash(safe_file(folder, 'page.txt')) != saved['files']['page.txt']['sha256']:
                        raise ValueError('Saved page text changed.')
                    add({**evidence, 'retrieved_at': receipt['created'], 'sha256': saved['files']['page.txt']['sha256']}, 'page', attempt, 'computer:' + receipt['id'])
                except (OSError, ValueError, KeyError, TypeError):
                    result['partial'] = True
        if frozen.get('execution', {}).get('capability') == 'web.sources':
            control = json.loads(row['session']).get('control')
            if not control:
                result['partial'] = True
                continue
            for index in range(1, 21):
                root = Path(control) / f'query-{index:02d}'
                if not root.exists():
                    continue
                for kind, count in [('page', 6), ('search', 2)]:
                    for ordinal in range(1, count + 1):
                        name = f'{kind}-{ordinal}.json'
                        if not (root / name).exists():
                            continue
                        try:
                            value = _load(root, name)
                            receipt = f'web.sources:{index}:{name}'
                            if kind == 'page' and value.get('ok') is True and isinstance(value.get('text'), str):
                                add(value, 'page', attempt, receipt)
                            elif kind == 'search' and value.get('status') == 'responded':
                                for candidate in value.get('response', {}).get('candidates', []):
                                    for chunk in candidate.get('groundingMetadata', {}).get('groundingChunks', []):
                                        web = chunk.get('web', {})
                                        add({'url': web.get('uri'), 'title': web.get('title'), 'retrieved_at': value.get('retrieved_at')}, 'search_result', attempt, receipt)
                        except (OSError, ValueError, TypeError, KeyError):
                            result['partial'] = True
    result['pages'] = list(pages.values())
    result['files'] = list(files.values())[:LIMIT]
    result['partial'] |= len(files) > LIMIT
    result['message'] = ('Recorded web sources are listed below.' if pages else
        'No successful page read or search result is recorded for this job.')
    return result


def source_url(run, source, paths=PATHS):
    if not isinstance(run, str) or len(run) > 80 or not isinstance(source, str) or len(source) != 64:
        raise DesktopPlanError('Choose a recorded source from this job.')
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()
        if not row:
            raise DesktopPlanError('That saved job is unavailable.')
        view = inspect(db, run, json.loads(row[0]))
        page = next((p for p in view['pages'] if p['id'] == source), None)
        if not page:
            raise DesktopPlanError('That source receipt is unavailable. Refresh this job.')
        return {'url': page['url']}
