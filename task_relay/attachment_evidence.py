"""Hash-scoped input receipts; registration is never a visual observation."""
import json

LIMIT = 20
INSTRUCTIONS = '''current_attachment_evidence identifies the exact current files by
full SHA-256. conversation_attachment_evidence supplies the same hash-scoped
input provenance for saved caption bindings during follow-ups; it does not select
one of those files or authorize work. Use the binding's exact request_id and IDs
to resolve the intended source; ask if competing versions remain ambiguous.
A filename, caption, earlier chat answer or upload registration does
not establish their contents. matching_worker_inputs proves only that those exact
bytes were bound as inputs to an attempt; it does not prove visual inspection or acceptance.
Read the attempt's actual report before attributing an observation to that file.
Never transfer a worker's findings between different hashes, even when filenames,
requests or captions are identical. A new upload can share a hash with an older
upload: identity depends on bytes, not upload ID or filename alone.
Historical conversation answers are not worker inspection receipts. If no matching
receipt/report establishes contents, describe those contents as uninspected, not
invalid. Missing inline vision does not block planning an authorized worker stage
that can inspect the saved image. Preserve the requested outcomes and exact current
attachment IDs; do not ask for a replacement upload based on an unrelated finding.
These facts grant no new work, replay, execution or acceptance authority.'''


def capture(state, ids, files):
    catalog = {f['id']: f for f in files}
    result = {'version': 1, 'files': [], 'missing_ids': [],
              'observation_state': 'No pixels or worker reports read by this capture.'}
    for ident in ids:
        file = catalog.get(ident)
        if file is None:
            result['missing_ids'].append(ident)
            continue
        item = {k: file[k] for k in ('id', 'filename', 'path', 'status', 'sha256', 'bytes') if k in file}
        digest = file.get('sha256')
        item['matching_worker_inputs'] = []
        item['complete'] = True
        # SQL narrows candidates, but only exact frozen input hashes establish
        # identity. A digest in prose, output metadata or a filename cannot match.
        if isinstance(digest, str) and len(digest) == 64:
            rows = state.db.execute('''SELECT id,run,task,state,frozen FROM production_attempts
                WHERE frozen LIKE ? ORDER BY rowid DESC LIMIT ?''', ('%' + digest + '%', LIMIT + 1)).fetchall()
            item['complete'] = len(rows) <= LIMIT
            for row in rows[:LIMIT]:
                try:
                    inputs = json.loads(row['frozen']).get('inputs', [])
                except (ValueError, TypeError, AttributeError):
                    continue
                matches = [{k: source[k] for k in ('artifact', 'path', 'sha256') if k in source}
                           for source in inputs if isinstance(source, dict) and source.get('sha256') == digest]
                if matches:
                    item['matching_worker_inputs'].append({'attempt_id': row['id'],
                        'run': row['run'], 'task': row['task'], 'state': row['state'], 'inputs': matches})
        result['files'].append(item)
    return result


def overview_scope(payload):
    """Reduce stale findings for fresh uploads; preserve original JSON pointers."""
    evidence = payload.get('current_attachment_evidence') or payload.get('conversation_attachment_evidence')
    snap = payload.get('snapshot', {})
    if (not evidence or snap.get('focus') or payload.get('reply_plan_id')
            or snap.get('pipeline_step') or payload.get('entry_context', {}).get('followup')):
        return payload
    runs = {}
    for file in evidence['files']:
        for receipt in file['matching_worker_inputs']:
            runs.setdefault(receipt['run'], []).append({
                'attachment_id':file['id'], 'sha256':file['sha256'],
                'attempt_id':receipt['attempt_id'], 'task':receipt['task']})
    scoped = dict(snap)
    for key, identity in (('production_runs', 'name'), ('production_plans', 'id')):
        scoped[key] = []
        for index, row in enumerate(snap.get(key, [])):
            if row.get('name' if key == 'production_runs' else 'run') in runs:
                run = row.get('name' if key == 'production_runs' else 'run')
                scoped[key].append({**row, 'attachment_input_receipts':runs[run],
                    'attachment_evidence_rule':'Attribute findings only to the exact matching attempt/input hash; other attachments are not established by this record.'})
            else:
                scoped[key].append({k: row[k] for k in (identity, 'status', 'run', 'request_id') if k in row} | {
                    'catalog_pointer': '/snapshot/' + key + '/' + str(index),
                    'attachment_relation': 'No captured matching worker input receipt for current files; findings do not establish their contents.'})
    history = []
    for index, row in enumerate(payload.get('history', [])):
        entry = dict(row)
        if 'answer' in entry:
            entry['answer'] = '[Historical chat answer, not a file inspection receipt. Read its answer_pointer when needed for the current request.]'
            entry['answer_pointer'] = '/history/' + str(index) + '/answer'
        history.append(entry)
    return {**payload, 'snapshot': scoped, 'history': history}
