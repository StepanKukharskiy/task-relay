"""Registered review obligations distinguish projections from indexed evidence."""
import math
from .record_lifecycle import definition


def candidates(frozen):
    paths=[i['path'] for i in frozen['inputs'] if i.get('from_task')==frozen.get('review_of') and frozen.get('review_of')]
    hooks=definition(frozen['operation_contract']) if frozen.get('operation_contract') else None
    if hooks and hooks.review_units and hooks.evidence_parameter:
        # A composed evidence container may be an output of the same producer.
        # Its registered source role still uses exact indexed per-item evidence;
        # it is not another authored projection requiring whole-file rereading.
        source=frozen['operation_contract']['parameters'][hooks.evidence_parameter]
        paths=[p for p in paths if p!=source]
    return paths


def interface(frozen,read):
    if not frozen.get('review_of') or not frozen.get('operation_contract'):return None
    hooks=definition(frozen['operation_contract'])
    if not hooks or not hooks.review_units:return None
    context=hooks.context(frozen,read) # verifies exact source bindings and projections
    paths=candidates(frozen)
    if not paths:raise ValueError('Registered review requires its authored candidate projection')
    remaining=96000;reads=0
    for path in paths:
        raw=read(path);text=raw.decode('utf-8');prefix=raw[:remaining].decode('utf-8',errors='ignore')
        remaining-=len(prefix.encode('utf-8'));reads+=math.ceil((len(text)-len(prefix))/24000)
    units=hooks.review_units(frozen,context)
    from .operation_contracts import identity
    batch=identity({k:frozen['operation_contract'][k] for k in ('id','version')})['batch']
    return dict(version=1,candidates=paths,indexed_evidence=[frozen['operation_contract']['parameters'][hooks.evidence_parameter]],
        units=units,read_requests=reads,submission_requests=math.ceil(units/batch),finalization_requests=1,
        required_requests=reads+math.ceil(units/batch)+1,
        authority='Candidate projections require complete literal inspection. Registered source containers retain exact hashes and per-item evidence access; indexed source text is not claimed to have been read in full. Every independent item judgment remains required.')


def requirements(frozen):
    """Describe inspection by declared representation, never by tool availability."""
    return ('Inspection requirements: read text/plain, text/markdown and JSON literally. '
            'The availability of image_view never creates a pixel obligation for text. '
            'Inspect pixels only for supplied images or registered visual representations. '
            'For execution provenance read execution-evidence/*.json or granted work_evidence; '
            'embedded observation IDs are citations into those records, not evidence_read IDs. '
            'Keep procedural completion, semantic quality, installation metadata and actual '
            'action evidence separate. Judge only the assigned criteria and exact supplied files; '
            'broader workflow qualifications absent from this assignment remain untested, not '
            'new defects to repair. A blocked prerequisite cannot be cured by rewriting a report.')
