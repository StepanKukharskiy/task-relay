# -*- coding: utf-8 -*-
"""Executed inside Rhino 7/8, using only the selected installation's GH APIs."""
from __future__ import unicode_literals
import json
import os
import re

try:
    text_type = unicode
except NameError:
    text_type = str


def load_script(path, major):
    from rhino_worker import load_code, read_text
    if major != 7:
        return load_code(path)
    # IronPython compile(bytes) can interpret UTF-8 literals as ANSI. Decode
    # explicitly; compile(unicode) requires removal of the encoding cookie.
    source = read_text(path)
    if source.startswith('\ufeff'):source = source[1:]
    lines = source.splitlines(True)
    for index in range(min(2, len(lines))):
        if re.match(r'^[ \t\f]*#.*?coding[:=]', lines[index]):
            lines[index] = '# UTF-8 source decoded by Relay\n'
    return compile(''.join(lines), path, 'exec')


def snapshot(document, GH):
    graph, outputs, errors, warnings = {}, {}, [], []
    if document.Objects.Count > 1000:
        raise ValueError('Grasshopper document exceeds 1000 objects')
    for obj in document.Objects:
        ident = str(obj.InstanceGuid)
        params = getattr(obj, 'Params', None)
        inputs = list(params.Input) if params is not None else [obj] if hasattr(obj, 'Sources') else []
        result = list(params.Output) if params is not None else [obj] if hasattr(obj, 'VolatileDataCount') else []
        graph[ident] = dict(type=str(obj.ComponentGuid), nickname=text_type(obj.NickName), name=text_type(obj.Name),
                           inputs=[[str(p.InstanceGuid) for p in port.Sources] for port in inputs],
                           output_ids=[str(p.InstanceGuid) for p in result])
        outputs[ident] = [int(p.VolatileDataCount) for p in result]
        if getattr(obj, 'Locked', False):
            errors.append('Locked Grasshopper object: ' + text_type(obj.NickName))
        if hasattr(obj, 'RuntimeMessages'):
            for level, target in ((GH.Kernel.GH_RuntimeMessageLevel.Error, errors),
                                  (GH.Kernel.GH_RuntimeMessageLevel.Warning, warnings)):
                target.extend(text_type(obj.NickName) + ': ' + text_type(m) for m in obj.RuntimeMessages(level))
    return dict(graph=graph, outputs=outputs, errors=errors, warnings=warnings)


def perform(request):
    import Rhino
    import System
    import clr
    import scriptcontext
    from grasshopper_contract import validate_checks, evaluate
    # Loaded by Relay's private module loader, never through workspace imports.
    from rhino_worker import read_text, write, file_hash

    checks = validate_checks(json.loads(read_text(request['checks'])))
    Rhino.RhinoApp.GetPlugInObject('Grasshopper')
    for library in request['grasshopper_libraries']:
        if request['rhino_major'] == 7:
            # Rhino may already have loaded these assemblies for its plugin.
            # IronPython's path loader can introduce a second type identity.
            selected_hash = file_hash(library)
            name = os.path.splitext(os.path.basename(library))[0]
            loaded = [a for a in System.AppDomain.CurrentDomain.GetAssemblies()
                      if not a.IsDynamic and a.GetName().Name == name]
            if any(not a.Location or file_hash(a.Location) != selected_hash for a in loaded):
                raise ValueError('Loaded Grasshopper assembly differs from the selected Rhino installation: ' + name)
            assembly = loaded[0] if loaded else System.Reflection.Assembly.LoadFrom(library)
            # Rhino 7 shadow-copies plugins; bind their bytes, not the cache path.
            if not assembly.Location or file_hash(assembly.Location) != selected_hash:
                raise ValueError('Grasshopper assembly differs from the selected Rhino installation: ' + name)
            clr.AddReference(assembly)
        else:
            clr.AddReference(library)
    import Grasshopper as GH
    if not GH.Kernel.GH_Document.EnableSolutions:
        raise ValueError('Grasshopper solver is disabled; Relay will not change its global setting')
    out = request['out']
    context = scriptcontext.doc
    rhino_doc = Rhino.RhinoDoc.CreateHeadless(None)
    if rhino_doc is None:
        raise ValueError('Cannot create Grasshopper Rhino context')
    try:
        scriptcontext.doc = rhino_doc
        if request['mode'] == 'gh_build':
            document = GH.Kernel.GH_Document()
            try:
                document.Enabled = True
                namespace = dict(__name__='__main__', __file__=request['script'],
                                 Grasshopper=GH, Rhino=Rhino, System=System,
                                 ghdoc=document, doc=rhino_doc, workspace=request['workspace'])
                eval(load_script(request['script'], request['rhino_major']), namespace)
                if namespace['ghdoc'] is not document or namespace['doc'] is not rhino_doc or scriptcontext.doc != rhino_doc:
                    raise ValueError('Grasshopper script replaced an assigned document')
                document.NewSolution(False)
                baseline = snapshot(document, GH)
                errors = evaluate(baseline, checks)
                write(request['baseline'], baseline)
                if errors:
                    raise ValueError('; '.join(errors))
                writer = GH.Kernel.GH_DocumentIO()
                writer.Document = document
                for suffix in ('gh', 'ghx'):
                    path = os.path.join(out, 'candidate.' + suffix)
                    if os.path.exists(path) or not writer.SaveQuiet(path):
                        raise ValueError('Grasshopper native save failed or destination exists: ' + suffix)
                return dict(candidate_hashes={s:file_hash(os.path.join(out, 'candidate.' + s)) for s in ('gh', 'ghx')})
            finally:
                document.Dispose()
        if request['mode'] != 'gh_verify':
            raise ValueError('Unknown Grasshopper phase')
        baseline = json.loads(read_text(request['baseline']))
        results, errors, warnings, hashes = {}, [], [], {}
        for suffix in ('gh', 'ghx'):
            path = os.path.join(out, 'candidate.' + suffix)
            hashes[suffix] = file_hash(path)
            reader = GH.Kernel.GH_DocumentIO()
            try:
                if not reader.Open(path) or reader.Document is None:
                    raise ValueError('Cannot independently reopen Grasshopper ' + suffix)
                document = reader.Document
                document.Enabled = True
                document.NewSolution(False)
                current = snapshot(document, GH)
                results[suffix] = current
                errors.extend(suffix + ': ' + e for e in evaluate(current, checks, baseline))
                warnings.extend(suffix + ': ' + w for w in current['warnings'])
                if hashes[suffix] != file_hash(path):
                    errors.append('Grasshopper candidate changed during solve: ' + suffix)
            finally:
                if reader.Document is not None:
                    reader.Document.Dispose()
        report = dict(passed=not errors, checks=checks, before=baseline, after=results,
                      candidate_hashes=hashes, errors=errors, warnings=warnings)
        write(os.path.join(out, 'checks.json'), report)
        if errors:
            raise ValueError('; '.join(errors))
        return dict(candidate_hashes=hashes)
    finally:
        scriptcontext.doc = context
        rhino_doc.Dispose()
