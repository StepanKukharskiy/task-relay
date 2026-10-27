# -*- coding: utf-8 -*-
"""Portable physical-coordinate metadata shared by registered native adapters.

Units describe each coordinate, without rescaling geometry or inferring accuracy.
Legacy documents without metadata remain explicitly unspecified.
"""
import json

METERS_PER_UNIT={'Meters':1.0,'Millimeters':.001,'Centimeters':.01,'Feet':.3048,'Inches':.0254}
BASES=('estimated','measured','nominal')
SCHEMA=dict(type='object',properties=dict(units=dict(type='string',enum=list(METERS_PER_UNIT)),
    basis=dict(type='string',enum=list(BASES)),note=dict(type='string',minLength=1,maxLength=600)),
    required=['units','basis','note'],additionalProperties=False,
    description='Physical unit of every coordinate, scale/accuracy basis and human-readable disclosure. Estimated means inferred, not fabrication measurements. This metadata never rescales geometry.')


def validate_spatial(value):
    try:text_types=(str,unicode)
    except NameError:text_types=(str,)
    if not isinstance(value,dict) or set(value)!=set(('units','basis','note')):raise ValueError('Spatial metadata needs units, basis and note')
    if not isinstance(value['units'],text_types) or not isinstance(value['basis'],text_types) or value['units'] not in METERS_PER_UNIT or value['basis'] not in BASES:raise ValueError('Unsupported spatial units or basis')
    if not isinstance(value['note'],text_types) or not value['note'].strip() or len(value['note'])>600 or '\x00' in value['note']:raise ValueError('Spatial disclosure needs bounded text')
    return value


def spatial_receipt(value,bounds=None):
    if value is None:return dict(units='unspecified',basis='unspecified',meters_per_unit=None)
    validate_spatial(value);result=dict(value,meters_per_unit=METERS_PER_UNIT[value['units']])
    if bounds is not None:
        result['bounds_native']=bounds
        result['bounds_meters']=[[n*result['meters_per_unit'] for n in point] for point in bounds]
    return result


def portable_source():
    import inspect
    return 'METERS_PER_UNIT='+repr(METERS_PER_UNIT)+'\nBASES='+repr(BASES)+'\n'+inspect.getsource(validate_spatial)+'\n'+inspect.getsource(spatial_receipt)+'\n'
