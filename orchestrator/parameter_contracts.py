"""Small, explicit JSON Schema vocabulary for registered operation parameters.

No provider dependency or executable schema supplied by a job. Unsupported
keywords fail registration instead of silently skipping a declared constraint.
Content/effect validators remain separate adapter hooks.
"""
import json
import math
import re

TYPES = {'object': (dict,), 'array': (list,), 'string': (str,),
         'integer': (int,), 'number': (int, float), 'boolean': (bool,),
         'null': (type(None),)}
KEYWORDS = {'type', 'description', 'properties', 'required', 'additionalProperties',
            'items', 'minItems', 'maxItems', 'uniqueItems', 'minLength', 'maxLength',
            'pattern', 'minimum', 'maximum', 'enum', 'anyOf'}


def check(schema):
    """Reject malformed/unsupported trusted registrations before advertising them."""
    if not isinstance(schema, dict) or set(schema) - KEYWORDS:
        raise ValueError('Unsupported parameter schema vocabulary')
    kind = schema.get('type')
    if kind not in TYPES and not (kind is None and 'anyOf' in schema):
        raise ValueError('Parameter schema needs an explicit type or anyOf')
    if 'anyOf' in schema:
        if not isinstance(schema['anyOf'], list) or not schema['anyOf']:
            raise ValueError('Invalid parameter schema alternatives')
        for branch in schema['anyOf']: check(branch)
    if 'description' in schema and not isinstance(schema['description'], str):
        raise ValueError('Invalid parameter description')
    if 'enum' in schema:
        if not isinstance(schema['enum'], list) or not schema['enum']:
            raise ValueError('Invalid parameter enum')
        json.dumps(schema['enum'], allow_nan=False)
    groups = {'object': {'properties', 'required', 'additionalProperties'},
              'array': {'items', 'minItems', 'maxItems', 'uniqueItems'},
              'string': {'minLength', 'maxLength', 'pattern'},
              'number': {'minimum', 'maximum'}}
    for owner, keys in groups.items():
        if set(schema) & keys and kind not in ({'number', 'integer'} if owner == 'number' else {owner}):
            raise ValueError('Parameter schema keyword has the wrong type')
    for low, high in (('minItems', 'maxItems'), ('minLength', 'maxLength')):
        for name in (low, high):
            if name in schema and (type(schema[name]) is not int or schema[name] < 0):
                raise ValueError('Invalid parameter schema bound')
        if low in schema and high in schema and schema[low] > schema[high]:
            raise ValueError('Reversed parameter schema bounds')
    for name in ('minimum', 'maximum'):
        if name in schema and (type(schema[name]) not in (int, float) or not math.isfinite(schema[name])):
            raise ValueError('Invalid numeric parameter bound')
    if 'minimum' in schema and 'maximum' in schema and schema['minimum'] > schema['maximum']:
        raise ValueError('Reversed numeric parameter bounds')
    if 'pattern' in schema:
        if not isinstance(schema['pattern'], str): raise ValueError('Invalid parameter pattern')
        try: re.compile(schema['pattern'])
        except re.error as exc: raise ValueError('Invalid parameter pattern') from exc
    if kind == 'object':
        props = schema.get('properties', {})
        required = schema.get('required', [])
        if (not isinstance(props, dict) or any(not isinstance(k, str) for k in props)
                or not isinstance(required, list) or any(not isinstance(k, str) for k in required)
                or len(set(required)) != len(required) or set(required) - set(props)):
            raise ValueError('Invalid parameter object fields')
        for rule in props.values(): check(rule)
        extra = schema.get('additionalProperties', True)
        if isinstance(extra, dict): check(extra)
        elif type(extra) is not bool: raise ValueError('Invalid additional parameter fields')
    if kind == 'array':
        check(schema.get('items'))
        if 'uniqueItems' in schema and type(schema['uniqueItems']) is not bool:
            raise ValueError('Invalid uniqueItems declaration')


def validate(value, schema, path='parameters'):
    """Validate the declared wire shape; never coerce or repair submitted data."""
    def fail(reason): raise ValueError(path + ': ' + reason)
    kind = schema.get('type')
    if kind and type(value) not in TYPES[kind]: fail('expected ' + kind)
    if type(value) is float and not math.isfinite(value): fail('expected a finite number')
    if 'anyOf' in schema:
        errors=[]
        for branch in schema['anyOf']:
            try: validate(value, branch, path)
            except ValueError as exc:
                errors.append((branch,str(exc)));continue
            break
        else:
            # Select diagnostics only after every alternative has failed. Tags
            # narrow the explanation, never the accepted JSON Schema language.
            selected=[]
            if isinstance(value,dict):
                for branch,error in errors:
                    tags={name:rule['enum'][0] for name,rule in branch.get('properties',{}).items()
                          if name in branch.get('required',[]) and isinstance(rule,dict) and len(rule.get('enum',[]))==1}
                    if tags and all(name in value and type(value[name]) is type(tag) and value[name]==tag for name,tag in tags.items()):selected.append(error)
            messages=selected if len(selected)==1 else [error for _,error in errors]
            fail('does not match any declared alternative; '+ '; '.join(dict.fromkeys(messages))[:4000])
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        fail('unsupported value; expected one of '+json.dumps(schema['enum'],ensure_ascii=False)[:500])
    if kind == 'object':
        props = schema.get('properties', {})
        errors=[]
        for name in schema.get('required', []):
            if name not in value: errors.append(path+': missing '+name)
        for name, item in value.items():
            if not isinstance(name, str):errors.append(path+': field names must be strings');continue
            rule = props.get(name, schema.get('additionalProperties', True))
            if rule is False:errors.append(path+': unsupported field '+name)
            if isinstance(rule, dict):
                try:validate(item, rule, path + '.' + name)
                except ValueError as exc:errors.append(str(exc))
        if errors:raise ValueError('; '.join(errors[:12])[:4000])
    elif kind == 'array':
        if len(value) < schema.get('minItems', 0): fail('too few items: '+str(len(value))+'; minimum '+str(schema['minItems']))
        if 'maxItems' in schema and len(value) > schema['maxItems']: fail('too many items: '+str(len(value))+'; maximum '+str(schema['maxItems']))
        for index, item in enumerate(value): validate(item, schema['items'], path + '[' + str(index) + ']')
        if schema.get('uniqueItems'):
            keys = [json.dumps(item, sort_keys=True, allow_nan=False) for item in value]
            if len(set(keys)) != len(keys): fail('duplicate items')
    elif kind == 'string':
        if len(value) < schema.get('minLength', 0): fail('text is too short: '+str(len(value))+' characters; minimum '+str(schema['minLength']))
        if 'maxLength' in schema and len(value) > schema['maxLength']: fail('text is too long: '+str(len(value))+' characters; maximum '+str(schema['maxLength']))
        if 'pattern' in schema and re.search(schema['pattern'], value) is None: fail('invalid text format')
    elif kind in ('integer', 'number'):
        if 'minimum' in schema and value < schema['minimum']: fail('below minimum')
        if 'maximum' in schema and value > schema['maximum']: fail('above maximum')
