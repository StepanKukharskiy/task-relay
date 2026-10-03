"""Reviewed source-to-native-output links for a bounded presentation subject.

Registration verifies exact artifact bytes and native locators. It does not
infer facts, accept source claims or authorize editing or external dispatch.
"""

import hashlib
import io
import json
from pathlib import Path
import time
import uuid

from orchestrator import pptx_edit
from orchestrator.storage import transaction


KIND = "native_subject"


class VerifierUnavailable(ValueError):
    """A required source reader is absent; evidence has not changed."""


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_native_links(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, entity_key TEXT NOT NULL,
        predicate TEXT NOT NULL, source_artifact TEXT NOT NULL,
        source_sha256 TEXT NOT NULL, source_locator TEXT NOT NULL,
        output_artifact TEXT NOT NULL, output_sha256 TEXT NOT NULL,
        output_locator TEXT NOT NULL, evidence TEXT NOT NULL,
        review_state TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL,
        created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_native_coverage(
        job TEXT NOT NULL, output_artifact TEXT NOT NULL,
        output_locator TEXT NOT NULL, state TEXT NOT NULL, note TEXT NOT NULL,
        PRIMARY KEY(job,output_artifact,output_locator))''')


def _artifact(db, ident):
    row = db.execute('SELECT * FROM production_artifacts WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Unknown registered artifact.')
    row = dict(row)
    path = Path(row['blob'])
    if (not path.is_file() or path.is_symlink() or row['bytes'] > 50_000_000
            or path.stat().st_size != row['bytes']
            or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']):
        raise ValueError('Registered artifact is missing, changed or too large.')
    return row


def _encoded(locator):
    return json.dumps(locator, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate source JSON key.')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _source(raw, locator, entity_key):
    if not isinstance(locator, dict):
        raise ValueError('Source locator must be typed.')
    if locator.get('type') == 'json_line':
        if set(locator) != {'type', 'field', 'prefix'} or not all(
                isinstance(locator[k], str) and locator[k] for k in ('field', 'prefix')):
            raise ValueError('Invalid JSON-line source locator.')
        data = _json(raw)
        value = data.get(locator['field'])
        lines = ([line for line in value.splitlines() if line.startswith(locator['prefix'])]
                 if isinstance(value, str) else [])
        if len(lines) != 1 or entity_key.casefold() not in lines[0].casefold():
            raise ValueError('Exact source line is missing or ambiguous.')
    elif locator.get('type') == 'photo_manifest_entry':
        if set(locator) != {'type', 'id', 'sha256'} or not all(
                isinstance(locator[k], str) and locator[k] for k in ('id', 'sha256')):
            raise ValueError('Invalid photo-manifest source locator.')
        data = _json(raw)
        photos = data.get('photos')
        if not isinstance(photos, list) or sum(
                isinstance(item, dict) and item.get('id') == locator['id']
                and item.get('sha256') == locator['sha256']
                and str(item.get('query', '')).casefold() == entity_key.casefold()
                for item in photos) != 1:
            raise ValueError('Exact photo-manifest entry is missing or ambiguous.')
    elif locator.get('type') == 'pdf_text':
        if (set(locator) != {'type', 'page', 'needle'}
                or type(locator['page']) is not int or locator['page'] < 1
                or not isinstance(locator['needle'], str)
                or not 4 <= len(locator['needle']) <= 2000):
            raise ValueError('Invalid PDF text locator.')
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise VerifierUnavailable('PDF evidence requires pypdf in the Relay runtime.') from exc
        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if (reader.is_encrypted or locator['page'] > len(reader.pages)
                    or len(reader.pages) > 100):
                raise ValueError('PDF evidence page is missing or unsupported.')
            page = reader.pages[locator['page']-1].extract_text() or ''
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF evidence could not be read.') from exc
        if (page.count(locator['needle']) != 1
                or entity_key.casefold() not in page.casefold()):
            raise ValueError('Exact PDF evidence text is missing or ambiguous.')
    else:
        raise ValueError('Unsupported native source locator.')


def _output(listing, locator):
    if not isinstance(locator, dict) or locator.get('type') not in (
            'pptx_table_cell', 'pptx_text_run', 'pptx_picture', 'pptx_slide',
            'pptx_notes_run'):
        raise ValueError('Unsupported native output locator.')
    kind = locator['type']
    keys = {'pptx_table_cell': {'type', 'slide', 'shape_id', 'row', 'column', 'text'},
            'pptx_text_run': {'type', 'slide', 'shape_id', 'text'},
            'pptx_picture': {'type', 'slide', 'shape_id', 'sha256'},
            'pptx_slide': {'type', 'slide'},
            'pptx_notes_run': {'type', 'slide', 'index', 'text'}}
    if set(locator) != keys[kind] or type(locator['slide']) is not int or not 1 <= locator['slide'] <= len(listing['slides']):
        raise ValueError('Invalid native output locator.')
    if kind == 'pptx_slide':
        return
    if kind == 'pptx_notes_run':
        runs = listing['slides'][locator['slide']-1].get('notes_text_runs', [])
        if (type(locator['index']) is not int or not 0 <= locator['index'] < len(runs)
                or not isinstance(locator['text'], str)
                or runs[locator['index']] != locator['text']):
            raise ValueError('Exact native notes run is missing or changed.')
        return
    if type(locator['shape_id']) is not int or locator['shape_id'] < 1:
        raise ValueError('Invalid native shape ID.')
    matches = [shape for shape in listing['slides'][locator['slide']-1]['shapes']
               if shape['shape_id'] == locator['shape_id']]
    if len(matches) != 1:
        raise ValueError('Exact native shape is missing or ambiguous.')
    shape = matches[0]
    if kind == 'pptx_table_cell':
        if (type(locator['row']) is not int or type(locator['column']) is not int
                or locator['row'] < 0 or locator['column'] < 0):
            raise ValueError('Invalid native table coordinates.')
        cells = [cell for cell in shape.get('table_cells', [])
                 if (cell['row'], cell['column']) == (locator['row'], locator['column'])]
        if len(cells) != 1 or cells[0]['text_runs'].count(locator['text']) != 1:
            raise ValueError('Exact native table-cell run is missing or ambiguous.')
    elif kind == 'pptx_text_run':
        if shape['text_runs'].count(locator['text']) != 1:
            raise ValueError('Exact native text run is missing or ambiguous.')
    elif shape.get('image_sha256') != locator['sha256']:
        raise ValueError('Exact native picture changed.')


def record_link(db, *, job, entity_key, predicate, source_artifact, source_locator,
                output_artifact, output_locator, evidence, reviewer,
                review_state='pending', note=''):
    if db.execute('SELECT 1 FROM relay_pipelines WHERE id=?', (job,)).fetchone() is None:
        raise ValueError('Unknown job.')
    if (not all(isinstance(value, str) and value.strip() for value in
                (entity_key, predicate, evidence, reviewer))
            or review_state not in ('pending', 'reviewed') or not isinstance(note, str)):
        raise ValueError('Link needs an entity, evidence and explicit review state.')
    source = _artifact(db, source_artifact)
    output = _artifact(db, output_artifact)
    if not output['path'].lower().endswith('.pptx'):
        raise ValueError('Native output must be a registered PPTX.')
    _source(Path(source['blob']).read_bytes(), source_locator, entity_key)
    _output(pptx_edit.inspect(Path(output['blob']).read_bytes()), output_locator)
    ident = uuid.uuid4().hex
    with transaction(db):
        db.execute('''INSERT INTO relay_native_links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (ident, job, entity_key, predicate, source_artifact,
                    source['sha256'], _encoded(source_locator), output_artifact,
                    output['sha256'], _encoded(output_locator), evidence,
                    review_state, reviewer, note, time.time()))
    return ident


def record_coverage(db, *, job, output_artifact, output_locator, state, note):
    if db.execute('SELECT 1 FROM relay_pipelines WHERE id=?', (job,)).fetchone() is None:
        raise ValueError('Unknown job.')
    output = _artifact(db, output_artifact)
    _output(pptx_edit.inspect(Path(output['blob']).read_bytes()), output_locator)
    if state not in ('complete', 'incomplete') or not isinstance(note, str) or not note.strip():
        raise ValueError('Coverage needs an explicit state and reason.')
    if state == 'complete' and output_locator['type'] == 'pptx_slide':
        raise ValueError('Whole-slide completeness is unsupported by native subject links.')
    locator = _encoded(output_locator)
    if state == 'complete':
        links = [row for row in db.execute('''SELECT review_state FROM relay_native_links
            WHERE job=? AND output_artifact=? AND output_locator=?''',
            (job, output_artifact, locator))]
        if len(links) != 1 or links[0]['review_state'] != 'reviewed':
            raise ValueError('Complete native coverage requires one reviewed link.')
    with transaction(db):
        db.execute('''INSERT INTO relay_native_coverage VALUES (?,?,?,?,?)
            ON CONFLICT(job,output_artifact,output_locator)
            DO UPDATE SET state=excluded.state,note=excluded.note''',
            (job, output_artifact, locator, state, note))


def records(db, job):
    return {'links': [dict(row) for row in db.execute(
                'SELECT * FROM relay_native_links WHERE job=? ORDER BY created,id', (job,))],
            'coverage': [dict(row) for row in db.execute(
                'SELECT * FROM relay_native_coverage WHERE job=? ORDER BY output_artifact,output_locator',
                (job,))]}


def plan_withdrawal(db, *, job, entity_key, baseline_artifact):
    """Classify only declared locations; absent or uncertain links stay unknown."""
    baseline = _artifact(db, baseline_artifact)
    listing = pptx_edit.inspect(Path(baseline['blob']).read_bytes())
    registered = records(db, job)
    affected, unaffected, unknown = [], [], []
    for cover in registered['coverage']:
        if cover['output_artifact'] != baseline_artifact:
            continue
        locator = json.loads(cover['output_locator'])
        links = [link for link in registered['links']
                 if link['output_artifact'] == baseline_artifact
                 and link['output_locator'] == cover['output_locator']]
        item = {'location': locator, 'link_ids': [link['id'] for link in links]}
        try:
            _output(listing, locator)
            for link in links:
                source = _artifact(db, link['source_artifact'])
                if (source['sha256'] != link['source_sha256']
                        or baseline['sha256'] != link['output_sha256']):
                    raise ValueError('Recorded artifact version changed.')
                _source(Path(source['blob']).read_bytes(), json.loads(link['source_locator']),
                        link['entity_key'])
            if (len(links) == 1 and links[0]['entity_key'] == entity_key
                    and links[0]['review_state'] == 'reviewed'):
                affected.append({**item, 'reason': 'Exact linked subject is withdrawn.',
                                 'review_state': links[0]['review_state']})
            elif (cover['state'] == 'complete' and len(links) == 1
                  and links[0]['review_state'] == 'reviewed'):
                unaffected.append({**item, 'reason': 'Independent complete reviewed link.'})
            else:
                unknown.append({**item, 'reason': 'Incomplete or absent reviewed coverage: '
                                + cover['note']})
        except VerifierUnavailable:
            raise
        except (ValueError, OSError, KeyError, TypeError) as exc:
            unknown.append({**item, 'reason': str(exc)})
    return {'schema': 'task-relay.native-subject-impact', 'version': 1,
            'job': job, 'entity_key': entity_key, 'baseline_artifact': baseline_artifact,
            'baseline_sha256': baseline['sha256'], 'affected': affected,
            'unaffected': unaffected, 'unknown': unknown,
            'coverage_scope': 'Declared native locations only; unlisted deck content is unassessed.',
            'authorization': 'Planning only; no edit, selection or dispatch.'}
