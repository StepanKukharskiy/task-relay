"""Bounded data-only PPTX authoring. No application launch or network access."""
import io
import json
import math
import re

MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
VERSION = '1.0.2'
DESCRIPTION = '''Version 1 slide specification: {version:1,title:string,slides:[
{background?:"FFFFFF",notes?:string,elements:[...]}],size?:[width,height],font?:"Arial"}.
Dimensions and x,y,w,h are inches; default size is [13.333333,7.5].
Each element has type, x,y,w,h and optional name. Supported elements:
text: {text:string,font_size?:24,color?:"172B4D",bold?:false,align?:"left"|"center"|"right"}.
shape: {shape:"rectangle"|"ellipse",fill?:"E8EEF5",color?:"172B4D",text?:string,font_size?:24,bold?:false,align?:"left"|"center"|"right"}.
image: {path:exact staged PNG/JPEG input path}. Images fit without cropping/distortion.
table: {rows:[[string,...],...],font_size?:18,color?:"172B4D"}; first row is the header.
chart: {chart:"column"|"bar"|"line",categories:[string,...],series:[{name:string,values:[number,...]}]}.
Use native objects, readable text and uncluttered layouts. All boxes must fit the slide.
Limits: 1–50 slides, 1–50 elements/slide, 1000 elements/deck, 4000 characters/text,
20x10 table cells (300 characters each), 50 chart categories and 8 series.
No arbitrary code, URLs, templates, PPTX import, animations, or font installation.
Creation reopens and checks native objects, text, table/chart data and image bytes.
These are structural checks, not visual layout approval or Keynote qualification.
'''


def available():
    try:
        import pptx
        if pptx.__version__ != VERSION:
            raise ValueError('PPTX creation requires python-pptx==' + VERSION)
    except ImportError as exc:
        raise ValueError('PPTX dependency missing. Install task-relay[presentations] in the worker runtime.') from exc


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError('Invalid slide specification fields; see pptx.create slide_schema.')


def _text(value, maximum, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError('Missing or oversized presentation text.')
    # Avoid OOXML escaping/substitution changing exact source text on reopen.
    if any(ord(ch) < 32 and ch not in '\n\t' or 0xD800 <= ord(ch) <= 0xDFFF or ord(ch) in (0xFFFE, 0xFFFF) for ch in value):
        raise ValueError('Unsupported control character in presentation text.')


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Presentation numbers must be finite and within bounds.')


def _color(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9A-Fa-f]{6}', value):
        raise ValueError('Use six-digit RGB colors.')


def load(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate slide specification key: ' + key)
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def validate(document, image_paths=()):
    _object(document, ('version', 'title', 'slides'), ('size', 'font'))
    if type(document['version']) is not int or document['version'] != 1:
        raise ValueError('Unsupported slide specification version.')
    _text(document['title'], 300, False)
    _text(document.get('font', 'Arial'), 100, False)
    size = document.get('size', [13.333333, 7.5])
    if not isinstance(size, list) or len(size) != 2:
        raise ValueError('Slide size must contain width and height.')
    for n in size:
        _number(n, 1, 40)
    slides = document['slides']
    if not isinstance(slides, list) or not 1 <= len(slides) <= 50:
        raise ValueError('Expected 1–50 slides.')
    count = 0
    for slide in slides:
        _object(slide, ('elements',), ('background', 'notes'))
        _color(slide.get('background', 'FFFFFF'))
        _text(slide.get('notes', ''), 10000)
        if not isinstance(slide['elements'], list) or not 1 <= len(slide['elements']) <= 50:
            raise ValueError('Expected 1–50 elements per slide.')
        count += len(slide['elements'])
        if count > 1000:
            raise ValueError('Too many presentation elements.')
        for item in slide['elements']:
            if not isinstance(item, dict) or not isinstance(item.get('type'), str):
                raise ValueError('Missing presentation element type.')
            kind = item['type']
            fields = {
                'text': (('text',), ('font_size', 'color', 'bold', 'align')),
                'shape': (('shape',), ('fill', 'text', 'font_size', 'color', 'bold', 'align')),
                'image': (('path',), ()),
                'table': (('rows',), ('font_size', 'color')),
                'chart': (('chart', 'categories', 'series'), ()),
            }
            if kind not in fields:
                raise ValueError('Unsupported presentation element type.')
            required, optional = fields[kind]
            _object(item, ('type', 'x', 'y', 'w', 'h', *required), ('name', *optional))
            for key in ('x', 'y', 'w', 'h'):
                _number(item[key], 0 if key in ('x', 'y') else 0.01, 40)
            if item['x'] + item['w'] > size[0] + 1e-6 or item['y'] + item['h'] > size[1] + 1e-6:
                raise ValueError('Presentation element extends beyond slide bounds.')
            _text(item.get('name', ''), 100)
            if 'font_size' in item:
                _number(item['font_size'], 8, 96)
            for key in ('color', 'fill'):
                if key in item:
                    _color(item[key])
            if 'bold' in item and type(item['bold']) is not bool:
                raise ValueError('bold must be boolean.')
            if 'align' in item and item['align'] not in ('left', 'center', 'right'):
                raise ValueError('Unsupported text alignment.')
            if kind in ('text', 'shape'):
                _text(item.get('text', ''), 4000)
            if kind == 'shape' and item['shape'] not in ('rectangle', 'ellipse'):
                raise ValueError('Unsupported native shape.')
            if kind == 'image':
                from .contracts import relative
                path = relative(item['path'])
                if path not in image_paths:
                    raise ValueError('Image must name an exact declared PNG/JPEG input: ' + path)
            if kind == 'table':
                rows = item['rows']
                if not isinstance(rows, list) or not 1 <= len(rows) <= 20 or not isinstance(rows[0], list) or not 1 <= len(rows[0]) <= 10:
                    raise ValueError('Table must contain 1–20 rows and 1–10 columns.')
                for row in rows:
                    if not isinstance(row, list) or len(row) != len(rows[0]):
                        raise ValueError('Table rows must have the same width.')
                    for cell in row:
                        _text(cell, 300)
            if kind == 'chart':
                if item['chart'] not in ('column', 'bar', 'line'):
                    raise ValueError('Unsupported native chart.')
                categories, series = item['categories'], item['series']
                if not isinstance(categories, list) or not 1 <= len(categories) <= 50 or not isinstance(series, list) or not 1 <= len(series) <= 8:
                    raise ValueError('Invalid chart dimensions.')
                for category in categories:
                    _text(category, 100, False)
                    if category.startswith('='):
                        raise ValueError('Chart labels must be literal text, not spreadsheet formulas.')
                for entry in series:
                    _object(entry, ('name', 'values'))
                    _text(entry['name'], 100, False)
                    if entry['name'].startswith('='):
                        raise ValueError('Chart labels must be literal text, not spreadsheet formulas.')
                    if not isinstance(entry['values'], list) or len(entry['values']) != len(categories):
                        raise ValueError('Chart series must match categories.')
                    for n in entry['values']:
                        _number(n, -1e12, 1e12)
    return document


def _register_notes_master(deck):
    """Register the notes relationship omitted by python-pptx 1.0.2.

    Keynote requires this presentation-level reference even though python-pptx
    can reopen the notes through slide relationships without it (upstream #1051).
    Keep the standard CT_Presentation element order and the existing notes bytes.
    """
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.oxml.ns import qn
    relations = [r for r in deck.part.rels.values() if r.reltype == RT.NOTES_MASTER]
    if not relations:
        return
    if len(relations) != 1:
        raise ValueError('PPTX must have one notes master.')
    root = deck.part._element
    lists = root.findall(qn('p:notesMasterIdLst'))
    if not lists:
        listing = OxmlElement('p:notesMasterIdLst')
        masters = root.find(qn('p:sldMasterIdLst'))
        root.insert(root.index(masters) + 1 if masters is not None else 0, listing)
        entry = OxmlElement('p:notesMasterId')
        entry.set(qn('r:id'), relations[0].rId)
        listing.append(entry)
    _inspect_notes_master(deck)


def _inspect_notes_master(deck):
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.oxml.ns import qn
    relations = [r for r in deck.part.rels.values() if r.reltype == RT.NOTES_MASTER]
    lists = deck.part._element.findall(qn('p:notesMasterIdLst'))
    if not relations and not lists:
        return
    if (len(relations) != 1 or len(lists) != 1 or len(lists[0]) != 1
            or lists[0][0].tag != qn('p:notesMasterId')
            or lists[0][0].get(qn('r:id')) != relations[0].rId
            or relations[0].is_external):
        raise ValueError('PPTX reopen failed: notes master registration is missing or invalid.')
    root = deck.part._element
    if any(root.index(e) < root.index(lists[0]) for e in root
           if e.tag not in (qn('p:sldMasterIdLst'), qn('p:notesMasterIdLst'))):
        raise ValueError('PPTX reopen failed: notes master registration is out of order.')


def create(document, images=None, max_bytes=50000000):
    """Return checked PPTX bytes and structural evidence, before any output write."""
    available()
    images = images or {}
    validate(document, images)
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
    from pptx.util import Inches, Pt
    from PIL import Image

    dimensions = {}
    for path, raw in images.items():
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 40000000:
                raise ValueError('Only bounded PNG/JPEG images are supported.')
            image.verify()
            dimensions[path] = image.size
    deck = Presentation()
    width, height = document.get('size', [13.333333, 7.5])
    deck.slide_width, deck.slide_height = Inches(width), Inches(height)
    deck.core_properties.title = document['title']
    deck.core_properties.author = 'Task Relay'

    def text(frame, value, item, default_size=24):
        frame.text = value
        frame.word_wrap = True
        frame.auto_size = MSO_AUTO_SIZE.NONE
        frame.margin_left = frame.margin_right = Inches(0.06)
        frame.margin_top = frame.margin_bottom = Inches(0.03)
        for paragraph in frame.paragraphs:
            paragraph.font.name = document.get('font', 'Arial')
            paragraph.font.size = Pt(item.get('font_size', default_size))
            paragraph.font.bold = item.get('bold', False)
            paragraph.font.color.rgb = RGBColor.from_string(item.get('color', '172B4D'))
            paragraph.alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}[item.get('align', 'left')]

    for spec in document['slides']:
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(spec.get('background', 'FFFFFF'))
        if 'notes' in spec:
            slide.notes_slide.notes_text_frame.text = spec['notes']
        for index, item in enumerate(spec['elements']):
            box = [Inches(item[k]) for k in ('x', 'y', 'w', 'h')]
            kind = item['type']
            if kind == 'text':
                shape = slide.shapes.add_textbox(*box)
                text(shape.text_frame, item['text'], item)
            elif kind == 'shape':
                shape = slide.shapes.add_shape({'rectangle': MSO_SHAPE.RECTANGLE, 'ellipse': MSO_SHAPE.OVAL}[item['shape']], *box)
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor.from_string(item.get('fill', 'E8EEF5'))
                shape.line.fill.background()
                text(shape.text_frame, item.get('text', ''), item)
            elif kind == 'image':
                iw, ih = dimensions[item['path']]
                scale = min(box[2] / iw, box[3] / ih)
                w, h = round(iw * scale), round(ih * scale)
                shape = slide.shapes.add_picture(io.BytesIO(images[item['path']]), round(box[0] + (box[2] - w) / 2), round(box[1] + (box[3] - h) / 2), w, h)
            elif kind == 'table':
                rows = item['rows']
                shape = slide.shapes.add_table(len(rows), len(rows[0]), *box)
                for r, row in enumerate(rows):
                    for col, value in enumerate(row):
                        cell = shape.table.cell(r, col)
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = RGBColor.from_string('E8EEF5' if r == 0 else 'FFFFFF')
                        text(cell.text_frame, value, {**item, 'bold': r == 0}, 18)
            else:
                data = CategoryChartData()
                data.categories = item['categories']
                for series in item['series']:
                    data.add_series(series['name'], series['values'])
                shape = slide.shapes.add_chart({'column': XL_CHART_TYPE.COLUMN_CLUSTERED, 'bar': XL_CHART_TYPE.BAR_CLUSTERED, 'line': XL_CHART_TYPE.LINE}[item['chart']], *box, data)
                shape.chart.has_legend = len(item['series']) > 1
                shape.chart.font.name = document.get('font', 'Arial')
                shape.chart.font.size = Pt(16)
            shape.name = item.get('name') or f'{kind}-{index + 1}'
    _register_notes_master(deck)
    buffer = io.BytesIO()
    deck.save(buffer)
    raw = buffer.getvalue()
    if len(raw) > max_bytes:
        raise ValueError('PPTX output exceeds its byte limit.')
    evidence = inspect(raw, document, images)
    return raw, evidence


def inspect(raw, document, images):
    """Reopen the actual saved bytes and compare semantic native content."""
    from pptx import Presentation
    from pptx.util import Inches
    deck = Presentation(io.BytesIO(raw))
    _inspect_notes_master(deck)
    if len(deck.slides) != len(document['slides']) or deck.core_properties.title != document['title']:
        raise ValueError('PPTX reopen failed: slide count or title changed.')
    size = document.get('size', [13.333333, 7.5])
    if (deck.slide_width, deck.slide_height) != tuple(Inches(n) for n in size):
        raise ValueError('PPTX reopen failed: slide dimensions changed.')
    counts = dict(text=0, shape=0, table=0, chart=0, image=0)
    for slide, spec in zip(deck.slides, document['slides']):
        if len(slide.shapes) != len(spec['elements']):
            raise ValueError('PPTX reopen failed: native objects changed.')
        if 'notes' in spec and slide.notes_slide.notes_text_frame.text != spec['notes']:
            raise ValueError('PPTX reopen failed: notes changed.')
        for shape, item in zip(slide.shapes, spec['elements']):
            kind = item['type']
            counts[kind] += 1
            if kind in ('text', 'shape') and (not shape.has_text_frame or shape.text != item.get('text', '')):
                raise ValueError('PPTX reopen failed: editable text changed.')
            if kind == 'table':
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows] if shape.has_table else None
                if rows != item['rows']:
                    raise ValueError('PPTX reopen failed: editable table data changed.')
            if kind == 'chart':
                if not shape.has_chart or list(shape.chart.plots[0].categories) == []:
                    raise ValueError('PPTX reopen failed: missing chart.')
                series = [{'name': s.name, 'values': list(s.values)} for s in shape.chart.series]
                labels = [category.label for category in shape.chart.plots[0].categories]
                matches = len(series) == len(item['series']) and all(
                    actual['name'] == expected['name'] and len(actual['values']) == len(expected['values']) and all(
                        math.isclose(a, b, rel_tol=1e-14, abs_tol=0) for a, b in zip(actual['values'], expected['values']))
                    for actual, expected in zip(series, item['series']))
                if labels != item['categories'] or not matches:
                    raise ValueError('PPTX reopen failed: editable chart data changed.')
            if kind == 'image' and shape.image.blob != images[item['path']]:
                raise ValueError('PPTX reopen failed: image content changed.')
    return {'slide_count': len(deck.slides), 'native_objects': counts, 'reopened': True,
            'visual_review': 'not_performed', 'keynote_import': 'not_tested', 'python_pptx': VERSION,
            'chart_numeric_relative_tolerance': 1e-14}
