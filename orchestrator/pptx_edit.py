"""Guarded, package-preserving edits to an existing PowerPoint file."""
import hashlib
import copy
import io
import json
import posixpath
import re
import zipfile
try:
    from lxml import etree as ET
except ImportError:
    ET = None

MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS = {'p': P, 'a': A, 'r': R}
DESCRIPTION = '''Existing PPTX edit manifest, version 1:
{"version":1,"source_sha256":"64 lowercase hex characters","edits":[
 {"kind":"replace_text","slide":1,"shape_id":2,"old":"Exact current text run","new":"Replacement"},
 {"kind":"replace_text","slide":1,"shape_id":3,"row":0,"column":1,
  "old":"Exact native table-cell text run","new":"Replacement"},
 {"kind":"replace_image","slide":2,"shape_id":5,"old_sha256":"old image hash",
  "path":"exact declared image input path","new_sha256":"new image hash","fit":"contain"},
 {"kind":"remove_table_row","slide":2,"shape_id":6,"row":3,
  "old_runs":["Exact text from each run in that row"]},
 {"kind":"remove_shape","slide":2,"shape_id":7,"old_xml_sha256":"shape XML hash from inspect"},
 {"kind":"remove_notes_run","slide":2,"index":1,"old":"Exact notes run"},
 {"kind":"replace_notes_text","slide":2,"index":2,"old":"Exact notes run","new":"New text"}
]}. Slide numbers are one-based. Inspect the baseline with `presentation inspect` to find
shape IDs, exact text runs and embedded image hashes. Each old value must identify
one text run in that shape; stale or ambiguous edits fail. Text inside native table
cells is supported; row and column are zero-based and select one cell when present.
Replacement pictures use exact declared PNG/JPEG input paths. Optional
`fit: contain` centers the full image in the existing picture bounds.
No slide is rebuilt. Untouched package parts retain their exact uncompressed bytes.
The original PPTX is never overwritten; each edit produces a new version.
This version changes exact text and selected pictures, removes exact table rows
or shapes, and changes or removes exact notes runs. It does not edit charts,
masters, animations or slide order. Picture geometry and crop settings are
retained by default for replacement pictures; a different aspect ratio needs
visual review. Contain changes only the selected picture shape's geometry.
'''


def available():
    if ET is None:
        raise ValueError('PPTX editing requires lxml in the presentations worker runtime.')
    try:
        import PIL.Image
    except ImportError as exc:
        raise ValueError('PPTX picture editing requires Pillow in the presentations worker runtime.') from exc


def load(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate PPTX edit key: '+key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def validate(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {'version', 'source_sha256', 'edits'} or type(manifest['version']) is not int or manifest['version'] != 1:
        raise ValueError('Invalid PPTX edit manifest.')
    if not isinstance(manifest['source_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', manifest['source_sha256']):
        raise ValueError('PPTX edit needs the exact baseline SHA-256.')
    edits = manifest['edits']
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        raise ValueError('PPTX edit needs 1–100 changes.')
    image_targets=set()
    notes_targets=set()
    for edit in edits:
        if not isinstance(edit, dict) or edit.get('kind') not in (
                'replace_text','replace_image','replace_notes_text','remove_notes_run',
                'remove_table_row','remove_shape'):
            raise ValueError('Unsupported PPTX edit kind.')
        if edit['kind']=='replace_text' and set(edit) not in (
                {'kind','slide','shape_id','old','new'},
                {'kind','slide','shape_id','row','column','old','new'}):
            raise ValueError('Invalid replace_text fields.')
        if edit['kind']=='replace_image' and set(edit) not in (
                {'kind','slide','shape_id','old_sha256','path','new_sha256'},
                {'kind','slide','shape_id','old_sha256','path','new_sha256','fit'}):
            raise ValueError('Invalid replace_image fields.')
        if edit['kind']=='replace_image' and edit.get('fit', 'stretch') not in ('stretch', 'contain'):
            raise ValueError('Unsupported replacement picture fit.')
        if edit['kind']=='replace_notes_text' and set(edit) != {'kind','slide','index','old','new'}:
            raise ValueError('Invalid replace_notes_text fields.')
        if edit['kind']=='remove_notes_run' and set(edit) != {'kind','slide','index','old'}:
            raise ValueError('Invalid remove_notes_run fields.')
        if edit['kind']=='remove_table_row' and set(edit) != {
                'kind','slide','shape_id','row','old_runs'}:
            raise ValueError('Invalid remove_table_row fields.')
        if edit['kind']=='remove_shape' and set(edit) != {
                'kind','slide','shape_id','old_xml_sha256'}:
            raise ValueError('Invalid remove_shape fields.')
        if type(edit['slide']) is not int or not 1 <= edit['slide'] <= 500:
            raise ValueError('Invalid slide number.')
        if edit['kind'] in ('replace_notes_text','remove_notes_run'):
            if (type(edit['index']) is not int or not 0 <= edit['index'] <= 1000
                    or not isinstance(edit['old'],str) or not edit['old']
                    or len(edit['old']) > 4000
                    or any(ord(c) < 32 and c not in '\n\t'
                           or 0xD800 <= ord(c) <= 0xDFFF for c in edit['old'])):
                raise ValueError('Native notes edit needs an exact run index and old text.')
            target=(edit['slide'],edit['index'])
            if target in notes_targets:
                raise ValueError('Duplicate notes edit target.')
            notes_targets.add(target)
            if edit['kind']=='replace_notes_text' and (
                    not isinstance(edit['new'],str) or not edit['new']
                    or len(edit['new']) > 4000 or edit['new']==edit['old']
                    or any(ord(c) < 32 and c not in '\n\t'
                           or 0xD800 <= ord(c) <= 0xDFFF for c in edit['new'])):
                raise ValueError('Native notes replacement needs different nonempty text.')
            continue
        if type(edit['shape_id']) is not int or not 1 <= edit['shape_id'] <= 1000000:
            raise ValueError('Invalid slide number or shape ID.')
        if edit['kind']=='remove_table_row':
            if (type(edit['row']) is not int or not 1 <= edit['row'] <= 100
                    or not isinstance(edit['old_runs'],list)
                    or not 1 <= len(edit['old_runs']) <= 100
                    or any(not isinstance(value,str) or not value or len(value)>4000
                           for value in edit['old_runs'])):
                raise ValueError('Table row removal needs its exact non-header runs.')
            continue
        if edit['kind']=='remove_shape':
            if (not isinstance(edit['old_xml_sha256'],str)
                    or not re.fullmatch('[0-9a-f]{64}',edit['old_xml_sha256'])):
                raise ValueError('Shape removal needs an exact old XML hash.')
            continue
        if edit['kind']=='replace_text':
            if 'row' in edit and (type(edit['row']) is not int or type(edit['column']) is not int
                                  or not 0 <= edit['row'] <= 100 or not 0 <= edit['column'] <= 100):
                raise ValueError('Native table row and column must be zero-based integers.')
            for key in ('old', 'new'):
                value = edit[key]
                if not isinstance(value, str) or not value or len(value) > 4000 or any(ord(c) < 32 and c not in '\n\t' or 0xD800 <= ord(c) <= 0xDFFF for c in value):
                    raise ValueError('PPTX edit text must be nonempty, valid XML text of at most 4000 characters.')
            if edit['old'] == edit['new']:
                raise ValueError('PPTX edit must change the selected text.')
        else:
            target=(edit['slide'],edit['shape_id'])
            if target in image_targets:raise ValueError('Duplicate picture replacement target.')
            image_targets.add(target)
            if any(not isinstance(edit[k],str) or not re.fullmatch('[0-9a-f]{64}',edit[k]) for k in ('old_sha256','new_sha256')):
                raise ValueError('Picture replacement needs exact old and new SHA-256 hashes.')
            if not isinstance(edit['path'],str) or not edit['path'] or edit['path'].startswith('/') or '..' in edit['path'].split('/') or '\\' in edit['path']:
                raise ValueError('Picture replacement needs a safe declared input path.')
            if edit['old_sha256']==edit['new_sha256']:
                raise ValueError('Picture replacement must change the selected image.')
    return manifest


def _package(raw):
    if len(raw) > 50000000:
        raise ValueError('Baseline PPTX exceeds 50 MB.')
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(names) != len(set(names)) or len(names) > 10000 or sum(m.file_size for m in members) > 250000000:
            raise ValueError('Unsafe PPTX package size or duplicate entries.')
        if any(n.startswith('/') or '\\' in n or '..' in n.split('/') for n in names):
            raise ValueError('Unsafe PPTX package member path.')
        if '[Content_Types].xml' not in names or 'ppt/presentation.xml' not in names or 'ppt/_rels/presentation.xml.rels' not in names:
            raise ValueError('Incomplete PPTX package.')
        return archive
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid PPTX ZIP package.') from exc


def _xml(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('PPTX XML declarations with entities are unsupported.')
    return ET.fromstring(raw,parser=ET.XMLParser(resolve_entities=False,no_network=True,huge_tree=False))


def _slides(archive):
    presentation = _xml(archive.read('ppt/presentation.xml'))
    rels = _xml(archive.read('ppt/_rels/presentation.xml.rels'))
    targets = {r.get('Id'): r.get('Target') for r in rels if r.get('Type', '').endswith('/slide')}
    result = []
    for item in presentation.findall('p:sldIdLst/p:sldId', NS):
        target = targets.get(item.get('{'+R+'}id'))
        if not target:
            raise ValueError('PPTX slide relationship is missing.')
        path = posixpath.normpath(posixpath.join('ppt', target.lstrip('/'))) if not target.startswith('/') else target.lstrip('/')
        if not path.startswith('ppt/slides/') or path not in archive.namelist():
            raise ValueError('PPTX slide path is invalid.')
        result.append(path)
    if not result:
        raise ValueError('PPTX contains no slides.')
    return result


def _shape(root, shape_id):
    found = []
    for item in root.iter():
        if item.tag not in ('{'+P+'}sp', '{'+P+'}graphicFrame', '{'+P+'}pic', '{'+P+'}cxnSp'):
            continue
        meta = item.find('p:nvSpPr/p:cNvPr', NS)
        if meta is None: meta = item.find('p:nvGraphicFramePr/p:cNvPr', NS)
        if meta is None: meta = item.find('p:nvPicPr/p:cNvPr', NS)
        if meta is not None and meta.get('id') == str(shape_id):
            found.append(item)
    if len(found) != 1:
        raise ValueError('Shape ID is missing or ambiguous in baseline slide.')
    return found[0]


def _relation_path(slide_path):
    return posixpath.join(posixpath.dirname(slide_path),'_rels',posixpath.basename(slide_path)+'.rels')


def _notes_path(archive, slide_path):
    rel_path = _relation_path(slide_path)
    if rel_path not in archive.namelist():
        return None
    rels = _xml(archive.read(rel_path))
    found = [item for item in rels if item.get('Type', '').endswith('/notesSlide')
             and item.get('TargetMode') != 'External']
    if not found:
        return None
    if len(found) != 1:
        raise ValueError('Slide has ambiguous notes relationships.')
    target = found[0].get('Target', '')
    path = posixpath.normpath(posixpath.join(posixpath.dirname(slide_path), target))
    if not path.startswith('ppt/notesSlides/') or path not in archive.namelist():
        raise ValueError('Slide notes path is invalid.')
    return path


def _image_target(archive, slide_path, rid, changed=None):
    rel_path=_relation_path(slide_path)
    if rel_path not in archive.namelist() and (not changed or rel_path not in changed):
        raise ValueError('Picture relationship file is missing.')
    rels=_xml(changed[rel_path] if changed and rel_path in changed else archive.read(rel_path))
    found=[r for r in rels if r.get('Id')==rid and r.get('Type','').endswith('/image')]
    if len(found)!=1 or found[0].get('TargetMode')=='External':
        raise ValueError('Picture relationship is missing or external.')
    target=found[0].get('Target','')
    path=posixpath.normpath(posixpath.join(posixpath.dirname(slide_path),target))
    if not path.startswith('ppt/media/') or path not in archive.namelist():
        raise ValueError('Embedded picture target is invalid.')
    return path,rels,rel_path


def _picture_blip(shape):
    if shape.tag!='{'+P+'}pic':
        raise ValueError('replace_image targets a native picture shape.')
    hits=shape.findall('.//a:blip',NS)
    if len(hits)!=1 or not hits[0].get('{'+R+'}embed'):
        raise ValueError('Picture shape has no single embedded image.')
    return hits[0]


def _checked_image(raw, path):
    import PIL.Image
    if len(raw)>20000000:
        raise ValueError('Replacement picture exceeds 20 MB.')
    expected='PNG' if path.lower().endswith('.png') else 'JPEG' if path.lower().endswith(('.jpg','.jpeg')) else None
    if expected is None:
        raise ValueError('Replacement picture must be PNG or JPEG.')
    try:
        image=PIL.Image.open(io.BytesIO(raw))
        if image.format!=expected or image.width*image.height>40000000:
            raise ValueError('Replacement picture format or pixel count is invalid.')
        image.verify()
    except (OSError,ValueError) as exc:
        raise ValueError('Replacement picture is invalid.') from exc
    return 'png' if expected=='PNG' else 'jpeg'


def inspect(raw):
    available()
    with _package(raw) as archive:
        slides = []
        for number, path in enumerate(_slides(archive), 1):
            root = _xml(archive.read(path))
            shapes = []
            for item in root.iter():
                if item.tag not in ('{'+P+'}sp', '{'+P+'}graphicFrame', '{'+P+'}pic'):
                    continue
                meta = item.find('p:nvSpPr/p:cNvPr', NS)
                if meta is None: meta = item.find('p:nvGraphicFramePr/p:cNvPr', NS)
                if meta is None: meta = item.find('p:nvPicPr/p:cNvPr', NS)
                if meta is not None:
                    summary={'shape_id': int(meta.get('id')), 'name': meta.get('name', ''),
                             'xml_sha256': hashlib.sha256(ET.tostring(item,method='c14n')).hexdigest(),
                             'text_runs': [t.text or '' for t in item.findall('.//a:t', NS)]}
                    if item.tag == '{'+P+'}graphicFrame':
                        cells = []
                        for row_index, row in enumerate(item.findall('.//a:tbl/a:tr', NS)):
                            for column_index, cell in enumerate(row.findall('a:tc', NS)):
                                cells.append({'row': row_index, 'column': column_index,
                                              'text_runs': [t.text or '' for t in cell.findall('.//a:t', NS)]})
                        if cells:
                            summary['table_cells'] = cells
                    if item.tag=='{'+P+'}pic':
                        blip=_picture_blip(item)
                        target,_,_=_image_target(archive,path,blip.get('{'+R+'}embed'))
                        summary['image_sha256']=hashlib.sha256(archive.read(target)).hexdigest()
                    shapes.append(summary)
            notes_path = _notes_path(archive, path)
            notes = ([t.text or '' for t in _xml(archive.read(notes_path)).findall('.//a:t', NS)]
                     if notes_path else [])
            slides.append({'slide': number, 'shapes': shapes,
                           'notes_text_runs': notes})
        return {'source_sha256': hashlib.sha256(raw).hexdigest(), 'slides': slides}


def edit(raw, manifest, max_bytes=50000000, images=None):
    available()
    validate(manifest)
    baseline = hashlib.sha256(raw).hexdigest()
    if baseline != manifest['source_sha256']:
        raise ValueError('Baseline PPTX hash changed; edit was not applied.')
    images=images or {}
    declared={e['path'] for e in manifest['edits'] if e['kind']=='replace_image'}
    if set(images)!=declared:
        raise ValueError('Replacement pictures must match exact declared inputs.')
    with _package(raw) as archive:
        slides = _slides(archive)
        changed = {}
        added = {}
        removed = set()
        removable_media = set()
        edits_by_slide = {}
        for item in manifest['edits']:
            edits_by_slide.setdefault(item['slide'], []).append(item)
        for number, edits in edits_by_slide.items():
            if number > len(slides): raise ValueError('Edit targets a slide outside the baseline.')
            path = slides[number-1]
            root = _xml(archive.read(path))
            notes_path = _notes_path(archive, path)
            notes_root = _xml(archive.read(notes_path)) if notes_path else None
            notes_runs = notes_root.findall('.//a:t', NS) if notes_root is not None else []
            slide_changed = False
            notes_changed = False
            for item in edits:
                if item['kind'] in ('replace_notes_text','remove_notes_run'):
                    if item['index'] >= len(notes_runs):
                        raise ValueError('Native notes run is missing.')
                    run = notes_runs[item['index']]
                    if (run.text or '') != item['old']:
                        raise ValueError('Exact old notes run changed.')
                    if item['kind']=='replace_notes_text':
                        run.text = item['new']
                    else:
                        paragraph = next((node for node in run.iterancestors()
                                          if node.tag == '{'+A+'}p'), None)
                        if (paragraph is None or paragraph.getparent() is None
                                or len(paragraph.findall('.//a:t', NS)) != 1):
                            raise ValueError('Notes run cannot be removed as one paragraph.')
                        paragraph.getparent().remove(paragraph)
                    notes_changed = True
                    continue
                shape = _shape(root, item['shape_id'])
                if item['kind']=='remove_table_row':
                    if shape.tag != '{'+P+'}graphicFrame':
                        raise ValueError('Row removal targets a native table shape.')
                    rows = shape.findall('.//a:tbl/a:tr', NS)
                    if item['row'] >= len(rows):
                        raise ValueError('Native table row is missing.')
                    row = rows[item['row']]
                    old_runs = [t.text or '' for t in row.findall('.//a:t', NS)]
                    if old_runs != item['old_runs']:
                        raise ValueError('Exact native table row content changed.')
                    extent = shape.find('p:xfrm/a:ext', NS)
                    if extent is None or not row.get('h'):
                        raise ValueError('Native table height cannot be adjusted safely.')
                    height = int(extent.get('cy')) - int(row.get('h'))
                    if height <= 0:
                        raise ValueError('Native table row height is invalid.')
                    row.getparent().remove(row)
                    extent.set('cy', str(height))
                    slide_changed = True
                elif item['kind']=='remove_shape':
                    actual = hashlib.sha256(ET.tostring(shape,method='c14n')).hexdigest()
                    if actual != item['old_xml_sha256']:
                        raise ValueError('Exact native shape XML changed.')
                    if shape.tag == '{'+P+'}pic':
                        blip = _picture_blip(shape)
                        rid = blip.get('{'+R+'}embed')
                        media_path, rels, rel_path = _image_target(archive,path,rid,changed)
                    else:
                        rid = None
                    shape.getparent().remove(shape)
                    if rid and not any(node.get('{'+R+'}embed') == rid
                                       for node in root.findall('.//a:blip', NS)):
                        for relation in list(rels):
                            if relation.get('Id') == rid:
                                rels.remove(relation)
                        changed[rel_path] = ET.tostring(rels,encoding='utf-8',xml_declaration=True)
                        removable_media.add(media_path)
                    slide_changed = True
                elif item['kind']=='replace_text':
                    target = shape
                    if 'row' in item:
                        if shape.tag != '{'+P+'}graphicFrame':
                            raise ValueError('Table-cell edit targets a native table shape.')
                        rows = shape.findall('.//a:tbl/a:tr', NS)
                        if item['row'] >= len(rows):
                            raise ValueError('Native table row is missing.')
                        cells = rows[item['row']].findall('a:tc', NS)
                        if item['column'] >= len(cells):
                            raise ValueError('Native table column is missing.')
                        target = cells[item['column']]
                    hits = [t for t in target.findall('.//a:t', NS) if (t.text or '') == item['old']]
                    if len(hits) != 1:
                        raise ValueError('Exact old text run is missing or ambiguous; inspect the baseline again.')
                    hits[0].text = item['new']
                    slide_changed = True
                else:
                    picture=images[item['path']]
                    if hashlib.sha256(picture).hexdigest()!=item['new_sha256']:
                        raise ValueError('Replacement picture hash changed.')
                    extension=_checked_image(picture,item['path'])
                    blip=_picture_blip(shape)
                    old_rid=blip.get('{'+R+'}embed')
                    old_path,rels,rel_path=_image_target(archive,path,old_rid,changed)
                    if hashlib.sha256(archive.read(old_path)).hexdigest()!=item['old_sha256']:
                        raise ValueError('Original embedded picture hash changed.')
                    new_path='ppt/media/relay-'+item['new_sha256']+'.'+extension
                    if new_path in archive.namelist() and archive.read(new_path)!=picture:
                        raise ValueError('Replacement picture package path collides.')
                    if new_path not in archive.namelist():added[new_path]=picture
                    if item.get('fit') == 'contain':
                        import PIL.Image
                        with PIL.Image.open(io.BytesIO(picture)) as replacement:
                            width,height=replacement.size
                        transform=shape.find('p:spPr/a:xfrm',NS)
                        offset=transform.find('a:off',NS) if transform is not None else None
                        extent=transform.find('a:ext',NS) if transform is not None else None
                        if offset is None or extent is None:
                            raise ValueError('Picture geometry cannot be fitted safely.')
                        x,y,cx,cy=(int(offset.get('x')),int(offset.get('y')),
                                   int(extent.get('cx')),int(extent.get('cy')))
                        if cx <= 0 or cy <= 0:
                            raise ValueError('Picture geometry is invalid.')
                        if width * cy < height * cx:
                            fitted_cx=max(1,round(cy * width / height))
                            fitted_cy=cy
                        else:
                            fitted_cx=cx
                            fitted_cy=max(1,round(cx * height / width))
                        offset.set('x',str(x+(cx-fitted_cx)//2))
                        offset.set('y',str(y+(cy-fitted_cy)//2))
                        extent.set('cx',str(fitted_cx))
                        extent.set('cy',str(fitted_cy))
                        source_rect=shape.find('p:blipFill/a:srcRect',NS)
                        if source_rect is not None:
                            source_rect.getparent().remove(source_rect)
                    used={r.get('Id') for r in rels}
                    rid=next('rIdRelay'+str(i) for i in range(1,10001) if 'rIdRelay'+str(i) not in used)
                    ET.SubElement(rels,'{'+PKG+'}Relationship',Id=rid,
                        Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',
                        Target='../media/'+posixpath.basename(new_path))
                    blip.set('{'+R+'}embed',rid)
                    if not any(node.get('{'+R+'}embed') == old_rid
                               for node in root.findall('.//a:blip', NS)):
                        for relation in list(rels):
                            if relation.get('Id') == old_rid:
                                rels.remove(relation)
                        removable_media.add(old_path)
                    changed[rel_path]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
                    types=_xml(changed.get('[Content_Types].xml',archive.read('[Content_Types].xml')))
                    if not any(c.get('Extension','').lower()==extension for c in types):
                        ET.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Default',
                                      Extension=extension,ContentType='image/png' if extension=='png' else 'image/jpeg')
                        changed['[Content_Types].xml']=ET.tostring(types,encoding='utf-8',xml_declaration=True)
                    slide_changed = True
            if slide_changed:
                changed[path] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            if notes_changed:
                changed[notes_path] = ET.tostring(notes_root, encoding='utf-8', xml_declaration=True)
        for media_path in removable_media:
            referenced = False
            for name in archive.namelist():
                if not name.endswith('.rels'):
                    continue
                rels = _xml(changed.get(name, archive.read(name)))
                base = posixpath.dirname(posixpath.dirname(name))
                for relation in rels:
                    if (relation.get('Type','').endswith('/image')
                            and relation.get('TargetMode') != 'External'):
                        target = relation.get('Target','')
                        resolved = posixpath.normpath(posixpath.join(base, target))
                        if resolved == media_path:
                            referenced = True
                            break
                if referenced:
                    break
            if not referenced:
                removed.add(media_path)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as dest:
            for info in archive.infolist():
                if info.filename not in removed:
                    dest.writestr(copy.copy(info), changed.get(info.filename, archive.read(info)))
            for name,data in added.items():dest.writestr(name,data,compress_type=zipfile.ZIP_DEFLATED)
        data = output.getvalue()
        if len(data) > max_bytes: raise ValueError('Edited PPTX exceeds the output limit.')
        with _package(data) as result:
            if _slides(result) != slides: raise ValueError('Edited PPTX slide structure changed.')
            for info in archive.infolist():
                if (info.filename not in changed and info.filename not in removed
                        and archive.read(info) != result.read(info.filename)):
                    raise ValueError('Unedited PPTX package content changed.')
            for item in manifest['edits']:
                if item['kind'] in ('replace_notes_text','remove_notes_run'):
                    source_notes = _notes_path(archive, slides[item['slide']-1])
                    result_notes = _notes_path(result, slides[item['slide']-1])
                    if not source_notes or source_notes != result_notes:
                        raise ValueError('Edited PPTX notes structure changed.')
                    before = [t.text or '' for t in _xml(archive.read(source_notes)).findall('.//a:t', NS)]
                    after = [t.text or '' for t in _xml(result.read(result_notes)).findall('.//a:t', NS)]
                    if item['kind']=='replace_notes_text' and item['new'] not in after:
                        raise ValueError('Edited PPTX did not retain requested notes text.')
                    if item['kind']=='remove_notes_run' and after.count(item['old']) >= before.count(item['old']):
                        raise ValueError('Edited PPTX did not remove the notes run.')
                    continue
                root = _xml(result.read(slides[item['slide']-1]))
                if item['kind']=='remove_shape':
                    try:
                        _shape(root, item['shape_id'])
                    except ValueError:
                        continue
                    raise ValueError('Edited PPTX retained a removed shape.')
                shape = _shape(root, item['shape_id'])
                if item['kind']=='remove_table_row':
                    before_shape = _shape(_xml(archive.read(slides[item['slide']-1])),
                                          item['shape_id'])
                    if len(shape.findall('.//a:tbl/a:tr', NS)) != len(
                            before_shape.findall('.//a:tbl/a:tr', NS))-1:
                        raise ValueError('Edited PPTX retained a removed table row.')
                    continue
                if item['kind']=='replace_text':
                    if sum((t.text or '') == item['new'] for t in shape.findall('.//a:t', NS)) < 1:
                        raise ValueError('Edited PPTX did not retain requested text.')
                else:
                    blip=_picture_blip(shape)
                    target,_,_=_image_target(result,slides[item['slide']-1],blip.get('{'+R+'}embed'))
                    if hashlib.sha256(result.read(target)).hexdigest()!=item['new_sha256']:
                        raise ValueError('Edited PPTX did not retain replacement picture.')
        return data, {'baseline_sha256': baseline, 'slide_count':len(slides),'changed_slides': sorted(edits_by_slide),
                      'edit_count': len(manifest['edits']), 'changed_parts':sorted(changed),
                      'added_parts':sorted(added), 'removed_parts':sorted(removed),
                      'untouched_parts_preserved': True,
                      'structural_review': 'passed', 'visual_review': 'not_performed'}
