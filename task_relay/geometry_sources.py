"""Compile source-derived native modeling into explicit source/review contracts."""
import copy
from pathlib import Path

from orchestrator import source_fidelity
from orchestrator.native_apps import SCRIPT_OPERATIONS

INSTRUCTIONS = '''
geometry_source_policy=1 requires geometry_basis for every ready native modeling
or script-preparation plan: {"mode":"procedural","artifacts":[],"checks":[]}
only for work designed from scratch; or {"mode":"source_derived","kind":"terrain","artifacts":
["exact source artifact ID"],"checks":[{"metric":"contour_deviation",
"tolerance":0.05,"unit":"m"}]} for geometry based on drawings, surveys or models.
Classify from the original request AND conversation: "follow this workflow" does
not erase its source requirements. A file path or conversation summary is not the
file. If original source bytes are missing, return needs_input naming the exact
file to bind via project_files/artifact_ids/reference_ids, with plan=null.
Missing format tooling must block work, never justify an invented substitute.
For source-derived geometry, kind is terrain for landscape/relief modeling, or
general for other geometry. Declare meaningful numerical error checks and units
before execution. Use user tolerances where provided; otherwise label proposed
tolerances in the plan for approval. For terrain include contour_deviation,
boundary_deviation, elevation_span_error and missing_source_entities (zero count).
Preserve block transforms, units, curved boundary segments and source elevations;
record datum assumptions and separate interpolation from extrapolation. An entity
count, valid file, bounding box or schema alone cannot prove a terrain matches.
During script preparation, require a source audit with actual extracted geometry,
entity handles, transforms, units and elevations, and review the script's use of
that data. Data needed by later host execution must be carried in supported exact
inputs (e.g. bounded script data or a prepared native scene), not an unfrozen local
path. If those inputs cannot carry it, return blocked. Do not simplify real data
to fit script limits. Preparation review does not certify final native geometry.
Native output review requires independently measured source/candidate error checks;
declare a format-capable reviewer. It must block if it cannot measure the saved
candidate. Native inspection counts/bounds are insufficient for these checks.
'''

CAD_SUFFIXES={'.dxf','.dwg','.3dm','.blend','.skp','.ifc','.step','.stp','.obj','.ply','.stl'}
TERRAIN_METRICS={'contour_deviation','boundary_deviation','elevation_span_error','missing_source_entities'}


def is_source(item):
    if item.get('request_context') or item.get('operation_support') or item.get('diagnostic_evidence'):return False
    path=Path(item['path'])
    if path.name in ('conversation.json','USER-REQUEST.txt','CONTEXT.json','sources.json'):return False
    return not str(path).startswith(('operation-support/','request/'))


def basis(result,payload,known):
    if not payload.get('geometry_source_policy'):return None  # Preserve frozen legacy proposals.
    value=result.get('geometry_basis')
    if (not isinstance(value,dict) or set(value)-{'kind'}!={'mode','artifacts','checks'}
        or value['mode'] not in ('procedural','source_derived')):
        raise ValueError('Declare geometry_basis: procedural or source_derived with exact source artifacts; summaries are not geometry.')
    ids=value['artifacts']
    if (not isinstance(ids,list) or len(ids)>10 or any(not isinstance(i,str) or i not in known for i in ids)
        or len(set(ids))!=len(ids)):
        raise ValueError('geometry_basis must name distinct captured source artifacts.')
    selected_cad=[s for s in payload['sources'] if s['artifact'] in payload['required_artifacts']
                  and is_source(s) and Path(s['path']).suffix.lower() in CAD_SUFFIXES]
    if value['mode']=='procedural':
        if ids or value['checks'] or selected_cad:
            raise ValueError('Selected CAD sources require source_derived geometry_basis; procedural work has no source checks.')
    else:
        if not ids or any(not is_source(known[i]) for i in ids):
            raise ValueError('Source-derived geometry requires original source artifacts, not conversation/request/contract summaries.')
        if not {s['artifact'] for s in selected_cad}<=set(ids):
            raise ValueError('geometry_basis omits selected CAD source geometry.')
        source_fidelity.validate_metrics(value['checks'])
        if value.get('kind') not in ('terrain','general'):
            raise ValueError('Source-derived geometry_basis requires kind terrain or general.')
        if value['kind']=='terrain':
            checks={x['metric']:x for x in value['checks']}
            if not TERRAIN_METRICS<=set(checks):
                raise ValueError('Terrain review requires contour, boundary, elevation-span and source-entity coverage comparisons.')
            if checks['missing_source_entities']['tolerance']!=0 or checks['missing_source_entities']['unit']!='count':
                raise ValueError('Terrain source entity coverage requires zero missing entities (unit count).')
            if any(checks[k]['unit'] not in ('m','mm','cm','ft') for k in TERRAIN_METRICS-{'missing_source_entities'}):
                raise ValueError('Terrain geometry errors require explicit length units: m, mm, cm or ft.')
    return copy.deepcopy(value)


def bind(tasks,geometry,known):
    if not geometry or geometry['mode']!='source_derived':return
    sources=[{k:known[aid][k] for k in ('artifact','sha256')} for aid in geometry['artifacts']]
    for reviewer in tasks:
        if not reviewer.get('review_of'):continue
        producer=next(t for t in tasks if t['id']==reviewer['review_of'])
        capability=producer.get('execution',{}).get('capability')
        if capability and capability not in SCRIPT_OPERATIONS:continue
        phase='comparison' if capability else 'source_audit'
        policy=dict(version=1,phase=phase,sources=copy.deepcopy(sources),checks=copy.deepcopy(geometry['checks']))
        # Do not weaken or mask a mismatched planner reviewer criterion list.
        criterion=source_fidelity.CRITERION
        if not capability:producer['criteria'].append(criterion)
        reviewer['criteria'].append(criterion)
        policy['criterion']=len(reviewer['criteria'])
        reviewer['source_fidelity']=policy
        for task in (producer,reviewer):
            task['instruction']+='\nRead the original geometry files and preserve their entity geometry, units and transforms. Missing data or format tooling means blocked, never synthetic geometry. Review source correspondence independently; file validity/counts/bounds alone are insufficient.'
        reviewer['instruction']+=source_fidelity.instructions(policy)
        # The native operation may not accept the original format, but its
        # independent reviewer must receive those frozen bytes.
        existing={i.get('artifact') for i in reviewer['inputs']}
        for aid in geometry['artifacts']:
            if aid not in existing:
                reviewer['inputs'].append({k:known[aid][k] for k in ('artifact','path','purpose','authority')})
