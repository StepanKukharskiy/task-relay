"""Explicit model judgments; deterministic distinct-design counts, never acceptance.

Visual suitability is independent of buying facts. Hashes identify the pixels a
judge used; they do not make that judge correct. Independent review is required.
"""
import re

STATUSES=('provisional','visually_suitable','excluded','unavailable')
SCHEMA=dict(type='object',properties={
    'status':dict(type='string',enum=list(STATUSES)),
    'design_id':dict(type='string',maxLength=120,description='Same ID for the same design across sellers, sizes and color variants. Different designs need distinct IDs.'),
    'reason':dict(type='string',maxLength=600),
    'photo_sha256':dict(type='string',description='Exact source image SHA-256 from image_view; empty if uninspected.'),
    'reference_sha256':dict(type='string',description='Exact source reference image SHA-256 from image_view; empty if uninspected.')},
    required=['status','design_id','reason','photo_sha256','reference_sha256'],additionalProperties=False)

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(SCHEMA['properties']):raise ValueError('Visual selection needs status, design identity, reason and exact pixel references')
    if value['status'] not in STATUSES:raise ValueError('Unknown visual selection status')
    for key,limit in [('design_id',120),('reason',600)]:
        if not isinstance(value[key],str) or not value[key].strip() or len(value[key])>limit:raise ValueError('Missing bounded visual selection '+key)
    for key in ('photo_sha256','reference_sha256'):
        if not isinstance(value[key],str) or value[key] and not re.fullmatch('[a-f0-9]{64}',value[key]):raise ValueError('Visual evidence needs exact SHA-256')
    if bool(value['photo_sha256'])!=bool(value['reference_sha256']):raise ValueError('Visual assessment needs both candidate and reference pixels')
    if value['status']=='visually_suitable' and not value['photo_sha256']:raise ValueError('Suitable visual selection requires inspected candidate and reference images')

def counts(options,goal):
    groups={s:set() for s in STATUSES}
    for option in options:
        v=option['selection'];validate(v)
        groups[v['status']].add(' '.join(v['design_id'].casefold().split()))
    # Contradictory judgments for one design cannot silently select the nicer one.
    for s,ids in groups.items():
        if any(ids & other for key,other in groups.items() if key!=s):raise ValueError('Conflicting visual judgments for the same design')
    return dict(suitable=len(groups['visually_suitable']),provisional=len(groups['provisional']),
        excluded=len(groups['excluded']),unavailable=len(groups['unavailable']),
        shortfall=max(0,goal-len(groups['visually_suitable'])))

def description(option):
    v=option['selection']
    photo='Candidate and reference pixels inspected; buying details remain separate.' if v['photo_sha256'] else 'Product pixels not yet assessed against the reference.'
    return v['status'].replace('_',' ').capitalize()+'. '+v['reason']+' '+photo

def verify_observations(store,document):
    """A claim requires actual supplied image parts and a subsequent response.

    Called at finalization, not when replaying an immutable document projection.
    This checks observation identity only; independent judges assess suitability.
    """
    if document.get('parameters',{}).get('selection_policy')!='visual':return
    from pathlib import Path
    import json
    from .visual_files import confirmed_pixels
    with store.connection(write=False) as db:
        row=db.execute('SELECT session FROM production_attempts WHERE id=?',(store.attempt,)).fetchone()
    session=json.loads(row[0] or '{}');control=session.get('control')
    claims={v[k] for item in document['items'] for o in item['options'] for v in [o['selection']] for k in ('photo_sha256','reference_sha256') if v[k]}
    if not claims:return
    if not control:raise ValueError('Visual selection has no original observation journal')
    observed=confirmed_pixels(control);sources=set(observed)
    for path in Path(control).glob('tool-*.json'):
        d=json.loads(path.read_text())
        if d.get('name')!='image_view':continue
        for image in d.get('result',{}).get('images',[]):
            if image['sha256'] in observed:sources.add(image.get('source_sha256',image['sha256']))
    if not claims<=sources:raise ValueError('Visual selection cites pixels not confirmed supplied to this worker')
