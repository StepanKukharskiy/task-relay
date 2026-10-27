"""Attach artifact-tool-authored data snapshots after its chart export.

This packaging repair accepts only complete, one-series, local literal snapshot
references. It never modifies slide layouts, chart styles or cached chart data.
It refuses external/source-workbook formulas and incomplete cache mappings.
"""
import re
import json
import posixpath as pp
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"c": C, "a": A, "r": R}
ET.register_namespace("c", C)
ET.register_namespace("a", A)
ET.register_namespace("r", R)

src, out, manifest = map(Path, sys.argv[1:])
if out.exists():
    raise ValueError("Packaging output already exists")
bindings = json.loads(manifest.read_text())
with zipfile.ZipFile(src) as z:
    parts = {n: z.read(n) for n in z.namelist()}
chart_parts = [n for n in parts if n.endswith('.xml') and '/charts/chart' in n and '/_rels/' not in n]
if len(chart_parts) != len(bindings):
    raise ValueError("Every chart must have a complete snapshot binding")
matched = set()
for n in chart_parts:
    root = ET.fromstring(parts[n])
    title = ''.join(root.findall('.//c:title//a:t', NS)[i].text or '' for i in range(len(root.findall('.//c:title//a:t', NS))))
    selected = [b for b in bindings if title.startswith(b['title_prefix'])]
    if len(selected) != 1:
        raise ValueError("Ambiguous chart snapshot binding")
    b = selected[0]
    if b['title_prefix'] in matched:
        raise ValueError("Duplicate chart snapshot binding")
    matched.add(b['title_prefix'])
    series = root.findall('.//c:ser', NS)
    if len(series) != 1:
        raise ValueError("This adapter supports exactly one fully mapped series")
    count = len(b['values'])
    formulas = [x.text for x in series[0].findall('.//c:f', NS)]
    formula_nodes = series[0].findall('.//c:f', NS)
    if len(formulas) != 2:
        raise ValueError("Exactly two literal category/value references required")
    prior_ends=[]
    for node,col in zip(formula_nodes,['A','B']):
        m=re.fullmatch(r"'Chart Data'!\$"+col+r"\$2:\$"+col+r"\$(\d+)",node.text or '')
        if not m or int(m[1])<2:
            raise ValueError("Formula lineage is outside local literal snapshot contract")
        prior_ends.append(int(m[1]))
    if len(set(prior_ends))!=1:
        raise ValueError("Category/value snapshot ranges differ")
    # Explicit snapshot replacement permits the observed trend to grow 2 to 3.
    # Cache verification below must pass before this package is written.
    for node,col in zip(formula_nodes,['A','B']):
        node.text=f"'Chart Data'!${col}$2:${col}${count+1}"
    cats = [x.text for x in series[0].findall('.//c:cat//c:pt/c:v', NS)]
    nums = [float(x.text) for x in series[0].findall('.//c:val//c:pt/c:v', NS)]
    if cats != b['categories'] or nums != b['values']:
        raise ValueError("Chart caches differ from the complete source binding")
    if root.find('c:externalData', NS) is not None:
        raise ValueError("Existing embedded workbook must be preserved through another adapter")
    wb = f"ppt/embeddings/report-snapshot-{len(matched):03d}.xlsx"
    parts[wb] = Path(b['workbook']).read_bytes()
    rel = ET.Element(f'{{{PKG}}}Relationships')
    ET.SubElement(rel, f'{{{PKG}}}Relationship', Id='rIdReportSnapshot', Type=R+'/package', Target=pp.relpath(wb, pp.dirname(n)))
    relpath = pp.join(pp.dirname(n), '_rels', pp.basename(n)+'.rels')
    if relpath in parts:
        raise ValueError("Unexpected existing chart relationships")
    ET.register_namespace('', PKG)
    parts[relpath] = ET.tostring(rel, encoding='utf-8', xml_declaration=True)
    ext = ET.SubElement(root, f'{{{C}}}externalData', {f'{{{R}}}id': 'rIdReportSnapshot'})
    ET.SubElement(ext, f'{{{C}}}autoUpdate', val='0')
    parts[n] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
types = ET.fromstring(parts['[Content_Types].xml'])
if not any(x.get('Extension') == 'xlsx' for x in types):
    ET.SubElement(types, f'{{{CT}}}Default', Extension='xlsx', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
ET.register_namespace('', CT)
parts['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for n, data in parts.items():
        z.writestr(n, data)
print(json.dumps({'snapshot_workbooks_attached': len(matched), 'live_source_links': False}))
