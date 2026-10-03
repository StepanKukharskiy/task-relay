"""Shared, read-only evidence links and conservative impact records.

Typed adapters establish facts and interpret source changes. This module only
normalizes their committed records and checks claims about reviewed coverage.
It never discovers dependencies from a file or authorizes a revision.
"""

import json


SCHEMA = 'task-relay.reviewed-links'
IMPACT_SCHEMA = 'task-relay.reviewed-impact'
VERSION = 1


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_reviewed_impacts(
        candidate_artifact TEXT PRIMARY KEY, job TEXT NOT NULL,
        plan_digest TEXT NOT NULL, record TEXT NOT NULL)''')


def save_impact(db, *, candidate_artifact, plan):
    """Save the exact normalized plan with a candidate in its caller's transaction."""
    record = plan['reviewed_impact']
    if record['job'] != plan['job'] or record['baseline_artifact'] != plan['baseline_artifact']:
        raise ValueError('Reviewed impact does not match the candidate plan.')
    db.execute('INSERT INTO relay_reviewed_impacts VALUES (?,?,?,?)',
               (candidate_artifact, plan['job'], plan['digest'],
                json.dumps(record, sort_keys=True, ensure_ascii=False)))


def saved_impacts(db, job):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_reviewed_impacts'").fetchone()
    if not exists:
        return []
    return [{'candidate_artifact': row['candidate_artifact'],
             'plan_digest': row['plan_digest'], 'record': json.loads(row['record'])}
            for row in db.execute('''SELECT * FROM relay_reviewed_impacts
                                     WHERE job=? ORDER BY rowid''', (job,))]


def verify_saved_impact(db, *, candidate_artifact, plan):
    """Check new candidates; earlier candidates retain their original plan digest."""
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_reviewed_impacts'").fetchone()
    if not exists:
        return
    row = db.execute('SELECT * FROM relay_reviewed_impacts WHERE candidate_artifact=?',
                     (candidate_artifact,)).fetchone()
    if row is None:
        return
    if (row['job'] != plan['job'] or row['plan_digest'] != plan['digest']
            or json.loads(row['record']) != plan['reviewed_impact']):
        raise ValueError('Saved reviewed impact changed; create a fresh candidate.')


def from_records(facts, translations, presentations=None, native=None):
    from . import translation_revisions as translations_adapter
    presentations = presentations or {}
    native = native or {}
    links = []
    coverage = []
    for row in facts.get('bindings', []):
        links.append({
            'id': row['id'], 'kind': 'material_cell',
            'entity': {'type': row['entity_type'], 'key': row['entity_key']},
            'predicate': row['predicate'], 'source_value': json.loads(row['value']),
            'output_value': json.loads(row['value']),
            'source': {'artifact': row['source_artifact'], 'sha256': row['source_sha256'],
                       'locator': {'type': 'xlsx_cell', 'sheet': row['source_sheet'],
                                   'cell': row['source_cell']}},
            'output': {'artifact': row['output_artifact'], 'sha256': row['output_sha256'],
                       'locator': {'type': 'xlsx_cell', 'sheet': row['output_sheet'],
                                   'cell': row['output_cell']}},
            'evidence': {'reference': row['evidence']},
            'review': {'state': row['review_state'], 'actor': row['reviewer'],
                       'note': row['review_note']},
            'check': row['check_kind'],
        })
    for row in facts.get('coverage', []):
        coverage.append({
            'kind': 'material_cell', 'output_artifact': row['output_artifact'],
            'output_location': row['output_sheet'] + '!' + row['output_cell'],
            'state': row['state'], 'reason': row['note'],
        })
    for row in translations.get('links', []):
        supported = row['status'] == translations_adapter.SUPPORTED
        source_locator = ({'type': 'txt_field', 'row': row['source_row'], 'field': 'name'}
                          if row['source_kind'] == 'yamaha_txt' else
                          {'type': 'xlsx_cell', 'sheet': 'Лист1',
                           'cell': 'B' + str(row['source_row'])})
        output_location = translations_adapter.SHEET + '!F' + str(row['output_row'])
        links.append({
            'id': row['id'], 'kind': 'parts_translation',
            'entity': {'type': 'motorcycle_part', 'key': row['part_number']},
            'predicate': 'russian_part_name', 'source_value': row['source_name'],
            'output_value': row['russian_name'],
            'source': {'artifact': row['source_artifact'], 'sha256': row['source_sha256'],
                       'locator': source_locator, 'record_sha256': row['source_record_sha256']},
            'output': {'artifact': row['output_artifact'], 'sha256': row['output_sha256'],
                       'locator': {'type': 'xlsx_cell', 'sheet': translations_adapter.SHEET,
                                   'cell': 'F' + str(row['output_row'])}},
            'evidence': {'reference': row['evidence_title'], 'url': row['evidence_url'],
                         'locator': row['evidence_locator'],
                         'report_artifact': row['review_report_artifact'],
                         'report_sha256': row['review_report_sha256']},
            'review': {'state': 'reviewed' if supported else 'pending',
                       'actor': None, 'note': row['status'],
                       'receipt': row['review_receipt']},
            'check': 'selected_translation_evidence' if supported else 'unverified_translation',
        })
        coverage.append({
            'kind': 'parts_translation', 'output_artifact': row['output_artifact'],
            'output_location': output_location,
            'state': 'complete' if supported else 'incomplete',
            'reason': ('Selected name and catalog evidence were reviewed.' if supported
                       else 'Original pilot left the Russian name unverified.'),
        })
    for row in presentations.get('links', []):
        locator = {'type': 'pptx_text_run', 'slide': row['slide'],
                   'shape_id': row['shape_id'], 'text': json.loads(row['value'])}
        links.append({
            'id': row['id'], 'kind': 'presentation_text',
            'entity': {'type': 'presentation_subject', 'key': row['entity_key']},
            'predicate': row['predicate'], 'source_value': json.loads(row['value']),
            'output_value': json.loads(row['value']),
            'source': {'artifact': row['source_artifact'], 'sha256': row['source_sha256'],
                       'locator': {'type': 'xlsx_cell', 'sheet': row['source_sheet'],
                                   'cell': row['source_cell']}},
            'output': {'artifact': row['output_artifact'], 'sha256': row['output_sha256'],
                       'locator': locator},
            'evidence': {'reference': row['evidence']},
            'review': {'state': row['review_state'], 'actor': row['reviewer'], 'note': ''},
            'check': 'exact_text_run',
        })
    for row in presentations.get('coverage', []):
        coverage.append({'kind': 'presentation_text',
                         'output_artifact': row['output_artifact'],
                         'output_location': location({'type': 'pptx_text_run',
                             'slide': row['slide'], 'shape_id': row['shape_id']}),
                         'state': row['state'], 'reason': row['note']})
    for row in native.get('links', []):
        output_locator = json.loads(row['output_locator'])
        links.append({
            'id': row['id'], 'kind': 'native_subject',
            'entity': {'type': 'presentation_subject', 'key': row['entity_key']},
            'predicate': row['predicate'], 'source_value': None,
            'output_value': output_locator.get('text', output_locator.get('sha256')),
            'source': {'artifact': row['source_artifact'], 'sha256': row['source_sha256'],
                       'locator': json.loads(row['source_locator'])},
            'output': {'artifact': row['output_artifact'], 'sha256': row['output_sha256'],
                       'locator': output_locator},
            'evidence': {'reference': row['evidence']},
            'review': {'state': row['review_state'], 'actor': row['reviewer'],
                       'note': row['note']},
            'check': 'exact_native_locator',
        })
    for row in native.get('coverage', []):
        coverage.append({'kind': 'native_subject', 'output_artifact': row['output_artifact'],
                         'output_location': location(json.loads(row['output_locator']), exact_run=True),
                         'state': row['state'], 'reason': row['note']})
    links.sort(key=lambda link: (link['kind'], link['output']['artifact'],
                                 location(link['output']['locator']), link['id']))
    coverage.sort(key=lambda item: (item['kind'], item['output_artifact'],
                                    item['output_location']))
    return {'schema': SCHEMA, 'version': VERSION, 'links': links, 'coverage': coverage,
            'scope': 'Explicitly recorded locations only; no inferred file dependencies.'}


def location(locator, *, exact_run=False):
    if locator['type'] == 'xlsx_cell':
        return locator['sheet'] + '!' + locator['cell']
    if locator['type'] == 'txt_field':
        return 'TXT row ' + str(locator['row']) + ' · ' + locator['field']
    if locator['type'] == 'pptx_text_run':
        base = 'Slide ' + str(locator['slide']) + ' / shape ' + str(locator['shape_id'])
        if exact_run and 'text' in locator:
            return base + ' / run ' + json.dumps(locator['text'], ensure_ascii=False)
        return base
    if locator['type'] == 'pptx_table_cell':
        return ('Slide ' + str(locator['slide']) + ' / shape ' + str(locator['shape_id'])
                + ' / cell ' + str(locator['row']) + ',' + str(locator['column'])
                + ' / run ' + json.dumps(locator['text'], ensure_ascii=False))
    if locator['type'] == 'pptx_picture':
        return 'Slide ' + str(locator['slide']) + ' / picture ' + str(locator['shape_id'])
    if locator['type'] == 'pptx_notes_run':
        return ('Slide ' + str(locator['slide']) + ' / notes run '
                + str(locator['index']) + ' / '
                + json.dumps(locator['text'], ensure_ascii=False))
    if locator['type'] == 'pptx_slide':
        return 'Slide ' + str(locator['slide'])
    raise ValueError('Unknown reviewed locator type.')


def records(db, job):
    from . import fact_revisions, translation_revisions, presentation_revisions, native_links
    return from_records(fact_revisions.records(db, job), translation_revisions.records(db, job),
                        presentation_revisions.records(db, job), native_links.records(db, job))


def impact_record(model, *, kind, plan, source_sha256, replacement_sha256):
    """Normalize one adapter plan and reject unsupported unaffected claims."""
    if kind not in ('material_cell', 'parts_translation', 'presentation_text'):
        raise ValueError('Unknown reviewed impact adapter.')
    baseline = plan['baseline_artifact']
    indexed = {}
    for link in model['links']:
        if link['kind'] == kind and link['output']['artifact'] == baseline:
            key = location(link['output']['locator'])
            indexed.setdefault(key, []).append(link)
    declared = {(row['kind'], row['output_artifact'], row['output_location']): row
                for row in model['coverage']}
    outcomes = []
    seen = set()
    for state in ('affected', 'unaffected', 'unknown'):
        for item in plan[state]:
            key = item['translation_cell'] if kind == 'parts_translation' else item['location']
            if key in seen:
                raise ValueError('Impact plan classifies an output location more than once.')
            seen.add(key)
            cover = declared.get((kind, baseline, key))
            supporting = indexed.get(key, [])
            if cover is None:
                raise ValueError('Impact location lacks declared output coverage.')
            if state == 'unaffected' and (cover['state'] != 'complete' or not supporting
                                          or any(link['review']['state'] != 'reviewed'
                                                 for link in supporting)):
                raise ValueError('Unaffected requires complete reviewed links.')
            outcomes.append({'output_location': key, 'status': state,
                             'reason': item['reason'], 'coverage': cover['state'],
                             'link_ids': [link['id'] for link in supporting]})
    expected = {key[2] for key in declared if key[:2] == (kind, baseline)}
    if seen != expected:
        raise ValueError('Impact plan omits a declared output location.')
    return {'schema': IMPACT_SCHEMA, 'version': VERSION, 'kind': kind,
            'job': plan['job'], 'old_source': plan['old_source'],
            'old_source_sha256': source_sha256,
            'replacement_source': plan['replacement_source'],
            'replacement_sha256': replacement_sha256,
            'baseline_artifact': baseline, 'baseline_sha256': plan['baseline_sha256'],
            'outcomes': outcomes,
            'scope': 'Declared output locations only; no rebuild or selection authorized.'}
