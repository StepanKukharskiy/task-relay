"""Provider wire projection; original tool schemas still own local validation.

Gemini's constrained function decoder needs concrete object fields. Keep those
fields structured, and encode only open maps/heterogeneous unions as JSON text.
This does not turn an owner intent into an assignment or relax its local schema.
"""
import copy
import json


def object_union(schema):
    branches=schema.get('anyOf',schema.get('oneOf',[]))
    if not branches or any(b.get('type')!='object' or not b.get('properties') for b in branches):return None
    properties={};required=set(branches[0].get('required',[]))
    for branch in branches:
        required.intersection_update(branch.get('required',[]))
        for name,value in branch['properties'].items():
            if name in properties and properties[name]!=value:return None
            properties[name]=value
    return dict(type='object',properties=properties,required=sorted(required))


def opaque(schema):
    return (schema.get('type')=='object' and
            (not schema.get('properties') or isinstance(schema.get('additionalProperties'),dict))) or (
                ('anyOf' in schema or 'oneOf' in schema) and object_union(schema) is None)


def project(schema):
    if opaque(schema):
        return dict(type='string',description='JSON-encoded value following the registered tool contract. Code decodes and validates it before execution. Schema: '+json.dumps(schema,sort_keys=True,separators=(',',':')))
    value=object_union(schema) or schema
    result={k:copy.deepcopy(v) for k,v in value.items() if k in ('type','description','enum','minimum','maximum','minItems','maxItems')}
    if value.get('type')=='object':
        result['properties']={k:project(v) for k,v in value['properties'].items()}
        result['required']=list(value.get('required',[]))
    elif value.get('type')=='array':result['items']=project(value['items'])
    return result


def decode(value,schema):
    if opaque(schema):
        if isinstance(value,str):
            try:return json.loads(value)
            except ValueError:raise ValueError('Malformed JSON in a provider-encoded tool field') from None
        return value # native/scripted callers already provide structured values
    shape=object_union(schema) or schema
    if shape.get('type')=='object' and isinstance(value,dict):
        return {k:decode(v,shape['properties'][k]) if k in shape.get('properties',{}) else v for k,v in value.items()}
    if shape.get('type')=='array' and isinstance(value,list):return [decode(v,shape['items']) for v in value]
    return value


def declaration(tool):
    value=copy.deepcopy(tool);schema=value.pop('parametersJsonSchema',value.pop('parameters',None))
    if schema and schema.get('properties'):value['parameters']=project(schema)
    return value
