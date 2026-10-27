# -*- coding: utf-8 -*-
"""Data-only Rhino document operations, shared by admission and native workers.

No model-supplied Python, imports, commands or API member names. RhinoScriptSyntax
is the compatibility facade over RhinoCommon 7/8. Native execution still uses the
existing isolated document/save/reopen lifecycle, never an exception-driven replay.
"""
import math
import json
try:
    from .spatial_contract import validate_spatial
except (ImportError,ValueError):
    from spatial_contract import validate_spatial

try:
    TEXT = (str, unicode)
except NameError:
    TEXT = (str,)


def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('Rhino document fields differ: ' + ', '.join(required))


def number(value, lo=-1000000, hi=1000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value) or not lo <= value <= hi:
        raise ValueError('Rhino document numbers must be finite and bounded')


def point(value):
    if not isinstance(value, list) or len(value) != 3:raise ValueError('Expected XYZ point')
    for n in value:number(n)


def text(value, maximum=200):
    if not isinstance(value, TEXT) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError('Invalid Rhino document text')


def validate(value):
    fields(value, ('version','units','objects','views','preview')+(('spatial',) if isinstance(value,dict) and 'spatial' in value else ()))
    if 'spatial' in value:
        validate_spatial(value['spatial'])
        if value['spatial']['units']!=value['units']:raise ValueError('Spatial and Rhino document units differ')
    if type(value['version']) is not int or value['version'] != 1:raise ValueError('Unsupported Rhino document version')
    if value['units'] not in ('Meters','Millimeters','Centimeters','Feet','Inches'):raise ValueError('Unsupported units')
    objects=value['objects']
    if not isinstance(objects,list) or not 1 <= len(objects) <= 500:raise ValueError('Expected 1–500 objects')
    names=set();geometry=False
    for obj in objects:
        if not isinstance(obj,dict):raise ValueError('Invalid Rhino object')
        kind=obj.get('type')
        extra={'box':('min','max'),'polyline':('points',),'text':('text','position','height'),
               'dimension':('start','end','offset','height')}.get(kind)
        if extra is None:raise ValueError('Unsupported typed Rhino operation: '+str(kind))
        fields(obj, ('type','name')+extra);text(obj['name'])
        if obj['name'] in names:raise ValueError('Duplicate Rhino object name')
        names.add(obj['name'])
        if kind=='box':
            point(obj['min']);point(obj['max'])
            if any(a>=b for a,b in zip(obj['min'],obj['max'])):raise ValueError('Box extents must be increasing')
            geometry=True
        elif kind=='polyline':
            points=obj['points']
            if not isinstance(points,list) or not 2<=len(points)<=2000:raise ValueError('Polyline needs 2–2000 points')
            for p in points:point(p)
            if any(a==b for a,b in zip(points,points[1:])):raise ValueError('Polyline contains zero-length segment')
            geometry=True
        elif kind=='text':
            text(obj['text'],2000);point(obj['position']);number(obj['height'],.000001,10000)
        else:
            for k in ('start','end','offset'):point(obj[k])
            number(obj['height'],.000001,10000)
            a,b,o=(obj[k] for k in ('start','end','offset'))
            if a==b:raise ValueError('Dimension endpoints coincide')
            u=[b[i]-a[i] for i in range(3)];v=[o[i]-a[i] for i in range(3)]
            if sum((u[(i+1)%3]*v[(i+2)%3]-u[(i+2)%3]*v[(i+1)%3])**2 for i in range(3))<=1e-20:
                raise ValueError('Dimension offset must define a plane')
    if not geometry:raise ValueError('Document requires box or polyline geometry')
    views=value['views']
    if not isinstance(views,list) or not 1<=len(views)<=10:raise ValueError('Expected 1–10 named views')
    names=set()
    for view in views:
        fields(view,('name','projection'));text(view['name'])
        if view['name'] in names:raise ValueError('Duplicate named view')
        names.add(view['name'])
        if view['projection'] not in ('Top','Front','Right','Perspective'):raise ValueError('Unsupported projection')
    fields(value['preview'],('resolution','named_view'))
    resolution=value['preview']['resolution']
    if not isinstance(resolution,list) or len(resolution)!=2 or any(type(n) is not int or not 64<=n<=1024 for n in resolution):
        raise ValueError('Preview resolution must be 64–1024 pixels')
    if value['preview']['named_view'] not in names:raise ValueError('Preview must select a declared view')
    return value


def checks(value):
    validate(value);dimensions={}
    for obj in value['objects']:
        if obj['type']=='box':dimensions[obj['name']]=[b-a for a,b in zip(obj['min'],obj['max'])]
        elif obj['type']=='polyline':dimensions[obj['name']]=[max(p[i] for p in obj['points'])-min(p[i] for p in obj['points']) for i in range(3)]
    return dict(mode='create',units=value['units'],changed_objects=[],allow_additions=True,
        expected_object_count=len(value['objects']),expected_dimensions=dimensions,
        expected_named_views=[v['name'] for v in value['views']],preview=value['preview'])


def preflight(value):
    validate(value)
    import Rhino
    import rhinoscriptsyntax as rs
    if int(Rhino.RhinoApp.Version.Major) not in (7,8):raise ValueError('Typed Rhino document requires Rhino 7/8')
    methods={'box':('AddBox',),'polyline':('AddPolyline',),'text':(),
        'dimension':('AddAlignedDimension','AddDimStyle','DimStyleTextHeight','DimStyleArrowSize','DimensionValue')}
    required={'ObjectName'}
    if 'spatial' in value:required.update(('SetDocumentUserText','GetDocumentUserText'))
    for obj in value['objects']:required.update(methods[obj['type']])
    missing=[name for name in sorted(required) if not callable(getattr(rs,name,None))]
    if any(obj['type']=='text' for obj in value['objects']):
        entity=getattr(getattr(Rhino,'Geometry',None),'TextEntity',None)
        for name in ('PlainTextToRtf','CreateWithRichText'):
            if not callable(getattr(entity,name,None)):missing.append('TextEntity.'+name)
    if missing:raise ValueError('Rhino capability unavailable before execution: '+', '.join(missing))


def build(doc,value):
    preflight(value)
    import Rhino
    import rhinoscriptsyntax as rs
    from System.Drawing import Size
    if 'spatial' in value:
        rs.SetDocumentUserText('TaskRelay.Spatial',json.dumps(value['spatial'],sort_keys=True,ensure_ascii=True))
    for obj in value['objects']:
        kind=obj['type']
        if kind=='box':
            a,b=obj['min'],obj['max']
            corners=[(a[0],a[1],a[2]),(b[0],a[1],a[2]),(b[0],b[1],a[2]),(a[0],b[1],a[2]),
                     (a[0],a[1],b[2]),(b[0],a[1],b[2]),(b[0],b[1],b[2]),(a[0],b[1],b[2])]
            ident=rs.AddBox(corners)
        elif kind=='polyline':ident=rs.AddPolyline(obj['points'])
        elif kind=='text':
            entity=native_text(doc,obj)
            try:ident=doc.Objects.AddText(entity)
            finally:entity.Dispose()
        else:
            style=rs.AddDimStyle('Relay '+obj['name'])
            if not style:raise ValueError('Cannot create dimension style')
            rs.DimStyleTextHeight(style,obj['height']);rs.DimStyleArrowSize(style,obj['height']*.6)
            ident=rs.AddAlignedDimension(obj['start'],obj['end'],obj['offset'],style)
        if not ident:raise ValueError('Rhino failed to create '+obj['name'])
        rs.ObjectName(ident,obj['name'])
    bounds=Rhino.Geometry.BoundingBox.Empty
    for obj in doc.Objects:bounds.Union(obj.Geometry.GetBoundingBox(True))
    if not bounds.IsValid:raise ValueError('Cannot frame invalid geometry')
    margin=max(bounds.Diagonal.Length*.08,.001);bounds.Inflate(margin)
    for view in value['views']:
        vp=Rhino.Display.RhinoViewport();vp.Size=Size(*value['preview']['resolution'])
        vp.SetProjection(getattr(Rhino.Display.DefinedViewportProjection,view['projection']),view['name'],False)
        if not vp.ZoomBoundingBox(bounds):raise ValueError('Cannot frame named view')
        info=Rhino.DocObjects.ViewInfo(vp);info.Name=view['name']
        if doc.NamedViews.Add(info)<0:raise ValueError('Cannot save named view')


def native_text(doc,obj):
    """Compile literal content to native text without adding it to a document."""
    import Rhino
    # Explicit plane works headlessly; code owns all RTF escaping and style.
    plane=Rhino.Geometry.Plane(Rhino.Geometry.Point3d(*obj['position']),Rhino.Geometry.Vector3d.ZAxis)
    encoded=Rhino.Geometry.TextEntity.PlainTextToRtf(obj['text'])
    entity=Rhino.Geometry.TextEntity.CreateWithRichText(encoded,plane,doc.DimStyles.Current,False,0,0)
    if entity is None:raise ValueError('Cannot encode literal text: '+obj['name'])
    entity.TextHeight=obj['height']
    return entity


def verify(doc,value):
    """Independent reopened geometry/content checks, not copied authoring claims."""
    import rhinoscriptsyntax as rs
    objects={o.Attributes.Name:o for o in doc.Objects};errors=[]
    if 'spatial' in value and rs.GetDocumentUserText('TaskRelay.Spatial')!=json.dumps(value['spatial'],sort_keys=True,ensure_ascii=True):errors.append('Spatial disclosure changed')
    if len(objects)!=len(value['objects']):errors.append('Named object coverage differs')
    for expected in value['objects']:
        obj=objects.get(expected['name'])
        if obj is None:errors.append('Missing object: '+expected['name']);continue
        kind=expected['type'];geo=obj.Geometry
        if kind=='text':
            # Native PlainText projects LF as CRLF and may add a space before
            # slash-containing paragraphs. Compare the independently compiled
            # representation, including rich content, not lossy string cleanup.
            probe=native_text(doc,expected)
            try:
                if geo.RichText!=probe.RichText or geo.PlainText!=probe.PlainText or abs(geo.TextHeight-expected['height'])>1e-8:
                    errors.append('Text differs: '+expected['name'])
            finally:probe.Dispose()
        elif kind=='dimension':
            measured=rs.DimensionValue(obj.Id)
            target=math.sqrt(sum((a-b)**2 for a,b in zip(expected['start'],expected['end'])))
            if measured is None or abs(measured-target)>max(1e-8,target*1e-9):errors.append('Dimension differs: '+expected['name'])
        elif kind=='polyline':
            ok,points=geo.TryGetPolyline()
            actual=[[p.X,p.Y,p.Z] for p in points] if ok else []
            if len(actual)!=len(expected['points']) or any(abs(a-b)>1e-8 for p,q in zip(actual,expected['points']) for a,b in zip(p,q)):
                errors.append('Polyline differs: '+expected['name'])
        else:
            box=geo.GetBoundingBox(True)
            if not geo.IsSolid or any(abs(a-b)>1e-8 for p,q in ((box.Min,expected['min']),(box.Max,expected['max'])) for a,b in zip((p.X,p.Y,p.Z),q)):
                errors.append('Box differs: '+expected['name'])
    return errors
