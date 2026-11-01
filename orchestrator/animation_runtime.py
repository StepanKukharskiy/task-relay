"""Registered animation dependencies and initialization, owned by Relay."""
import hashlib
import json
from pathlib import Path

GSAP_VERSION='3.15.0'
GSAP_SHA256='92bb9a96476f983d212a2bc4f54c889039c1696dd4461d40a736860938570fbb'
VENDOR=Path(__file__).resolve().parents[1]/'task_relay/assets/vendor'
PREFIX='relay-runtime/'


def files(value):
    if value.get('version')!=2 or value['animation_runtime']!='gsap':return {}
    library=VENDOR/('gsap-'+GSAP_VERSION+'.min.js')
    raw=library.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=GSAP_SHA256:raise ValueError('Bundled GSAP dependency changed')
    return {PREFIX+'gsap.min.js':raw,PREFIX+'gsap.LICENSE':(VENDOR/('gsap-'+GSAP_VERSION+'.LICENSE')).read_bytes()}


def identity():
    return {name:hashlib.sha256(raw).hexdigest() for name,raw in files(dict(version=2,animation_runtime='gsap')).items()}


def initialization(value,root):
    if value.get('version')!=2:return ''
    if value['animation_runtime']=='waapi':return ''
    ident=json.dumps(root).replace('<','\\u003c')
    return ('<script src="relay-runtime/gsap.min.js"></script><script>'
            'if(!window.gsap || gsap.version!=='+json.dumps(GSAP_VERSION)+')throw new Error("Relay GSAP runtime unavailable");'
            'window.__timelines=window.__timelines||{};'
            'window.relayTimeline=gsap.timeline({paused:true});'
            'window.__timelines['+ident+']=window.relayTimeline;'
            '</script>')


def receipt(value):
    if value.get('version')!=2:return dict(id='legacy',managed=False)
    engine=value['animation_runtime']
    return dict(id=engine,managed=True,version=GSAP_VERSION if engine=='gsap' else 'browser',
                files=identity() if engine=='gsap' else {})
