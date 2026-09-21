"""Fresh standalone process for baseline, approved Python, or independent reopen."""
import hashlib
import json
from pathlib import Path
import sys
import traceback

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from orchestrator.rhino3dm_document import available
from orchestrator.rhino3dm_script_contract import validate_checks
from orchestrator.runtime import file_hash
from orchestrator.workers import atomic


def encoded_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def snapshot(model):
    if len(model.Objects)>100000:raise ValueError('Library model exceeds 100000-object verification bound')
    objects={}
    for obj in model.Objects:
        geometry=obj.Geometry;attrs=obj.Attributes
        if geometry is None or not geometry.IsValid or not attrs.IsValid:
            raise ValueError('Invalid library geometry or attributes: '+str(attrs.Id))
        box=geometry.GetBoundingBox()
        dimensions=[box.Max.X-box.Min.X,box.Max.Y-box.Min.Y,box.Max.Z-box.Min.Z] if box.IsValid else None
        objects[str(attrs.Id)]=dict(name=attrs.Name,type=type(geometry).__name__,dimensions=dimensions,
            geometry_sha256=encoded_hash(geometry.Encode()),attributes_sha256=encoded_hash(attrs.Encode()))
    return dict(objects=objects,units=str(model.Settings.ModelUnitSystem),
        tolerance=model.Settings.ModelAbsoluteTolerance,
        strings=[list(pair) for pair in model.Strings],
        scope='All object geometry/encoded attributes, model units/tolerance and document strings. Other document tables, opaque plugin data and external dependencies require task-specific review.')


def compare(before, prepared, saved, checks):
    errors=[];warnings=[];objects=saved['objects']
    if set(prepared['objects'])!=set(objects):errors.append('Objects were lost, added or reidentified while saving/reopening')
    for ident in set(prepared['objects']) & set(objects):
        if prepared['objects'][ident]!=objects[ident]:
            warnings.append('Serialization changed object '+ident+' ('+str(objects[ident]['name'])+'); review file-version conversion before accepting.')
    for key in ('units','tolerance','strings'):
        if prepared[key]!=saved[key]:errors.append('Document '+key+' changed during serialization')
    for ident in checks['preserve_objects']:
        if ident not in before['objects'] or objects.get(ident)!=before['objects'][ident]:
            errors.append('Preserved source object changed or is missing: '+ident)
    if checks['expected_units'] is not None and saved['units']!='UnitSystem.'+checks['expected_units']:
        errors.append('Expected units differ from saved model')
    if checks['expected_object_count'] is not None and len(objects)!=checks['expected_object_count']:
        errors.append('Expected object count differs from saved model')
    for name in set(checks['required_objects'])|set(checks['expected_dimensions']):
        matches=[o for o in objects.values() if o['name']==name]
        if len(matches)!=1:errors.append('Required object name is missing or ambiguous: '+name);continue
        if name in checks['expected_dimensions']:
            expected=checks['expected_dimensions'][name];actual=matches[0]['dimensions']
            tolerance=[max(1e-6,abs(n)*1e-4) for n in expected]
            if actual is None:errors.append('No measurable bounds for '+name)
            elif any(abs(a-b)>t for a,b,t in zip(actual,expected,tolerance)):
                warnings.append('Dimensions differ: '+name+'; expected XYZ='+str(expected)+', measured XYZ='+str(actual)+
                    ', tolerance XYZ='+str(tolerance)+' '+saved['units'])
    return errors,warnings


def perform(request):
    from orchestrator.rhino3dm_script import runtime_identity
    if request['library_runtime']!=runtime_identity():raise ValueError('Worker library/Python differs from the approved runtime')
    library=available();mode=request['mode'];out=Path(request['out'])
    checks=validate_checks(json.loads(Path(request['checks']).read_text()))
    if checks['expected_units'] is not None and not isinstance(getattr(library.UnitSystem,checks['expected_units'],None),library.UnitSystem):
        raise ValueError('Unknown rhino3dm UnitSystem')
    if mode=='verify':
        candidate=out/'candidate.3dm'
        model=library.File3dm.Read(str(candidate))
        if model is None:raise ValueError('Library could not reopen candidate')
        # openNURBS stores modern archive versions as 70/80; early versions as 2/3/4.
        actual=model.ArchiveVersion
        target=checks['file_version']
        if actual not in (target,target*10):raise ValueError('Saved .3dm archive version differs from approved target')
        saved=snapshot(model)
        before=json.loads(Path(request['baseline']).read_text())
        prepared=json.loads(Path(request['prepared']).read_text())
        errors,warnings=compare(before,prepared,saved,checks)
        report=dict(passed=not errors,errors=errors,warnings=warnings,inventory=saved,
            file_version=target,archive_version=actual,library_version=library.__version__,
            verification_engine='rhino3dm',native_rhino_verified=False,visual_review='not_performed',
            candidate_sha256=file_hash(candidate))
        atomic(out/'checks.json',report)
        if errors:raise ValueError('; '.join(errors))
        return dict(candidate_sha256=report['candidate_sha256'])
    model=library.File3dm.Read(request['source']) if request['source'] else library.File3dm()
    if model is None:raise ValueError('Library could not read selected source model')
    if mode=='before':
        baseline=snapshot(model)
        if set(checks['preserve_objects'])-set(baseline['objects']):raise ValueError('Preservation UUID absent from source')
        atomic(Path(request['baseline']),baseline)
        return dict(source_archive_version=model.ArchiveVersion)
    if mode!='model':raise ValueError('Unknown library worker phase')
    namespace=dict(__name__='__main__',__file__=request['script'],rhino3dm=library,model=model,
        input_paths=request['input_paths'],workspace=request['workspace'])
    exec(compile(Path(request['script']).read_bytes(),request['script'],'exec'),namespace)
    model=namespace.get('model')
    if not isinstance(model,library.File3dm):raise ValueError('Script must leave a File3dm in model')
    atomic(Path(request['prepared']),snapshot(model))
    candidate=out/'candidate.3dm'
    if candidate.exists() or candidate.is_symlink():raise ValueError('Script created reserved candidate output; Relay owns saving')
    if not model.Write(str(candidate),checks['file_version']):raise ValueError('Library could not save candidate')
    return dict(candidate_sha256=file_hash(candidate))


def main(path):
    request=json.loads(Path(path).read_text());result=dict(mode=request['mode'],token=request['token'],passed=False)
    try:result.update(details=perform(request),passed=True)
    except BaseException:result['error']=traceback.format_exc()[-8000:]
    atomic(Path(request['result']),result)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
