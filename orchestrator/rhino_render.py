"""Binding for a fixed Rhino renderer; no arbitrary code or future manifest."""
import json
from pathlib import Path
from .rhino_contract import validate_render
from .runtime import file_hash


def bind_registered(rt, spec):
    for item in spec['inputs']:
        artifact=rt.artifact(item['artifact'])
        if file_hash(artifact['blob'])!=artifact['sha256']:raise ValueError('Rhino render source changed')
        if item['media_type']=='application/json':
            if artifact['sha256']!=spec['execution']['parameters']['manifest_sha256']:
                raise ValueError('Rhino render manifest hash differs from selected artifact')
            validate_render(json.loads(Path(artifact['blob']).read_text()))
