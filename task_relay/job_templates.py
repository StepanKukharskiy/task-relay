"""Bundled editable jobs; selecting a template never grants execution authority."""
import hashlib
import json
from importlib.resources import files

from orchestrator import node_spec


CATALOG = {
    'cellular-aggregation': dict(
        title='Cellular aggregation · from Chat',
        description='Research a timber pavilion, write its cellular-automata script, build and animate it in Blender, visualize it with Gemini, and export an editable PowerPoint.',
        requirements='Requires configured Codex, Perplexity, Blender and Gemini connections. Run reviews native execution and paid generation separately.',
        filename='cellular-aggregation.workflow.json'),
}


def dispatch(action, value):
    if not isinstance(value, dict):
        raise ValueError('Expected template selection')
    if action == 'node-templates' and not value:
        return dict(items=[dict(id=key, **{k: v for k, v in item.items() if k != 'filename'})
                           for key, item in CATALOG.items()], execution_authorized=False)
    if action != 'node-template' or set(value) != {'id'} or not isinstance(value['id'], str) or value['id'] not in CATALOG:
        raise ValueError('Choose an available job template')
    item = CATALOG[value['id']]
    raw = files('task_relay').joinpath('assets', 'job-templates', item['filename']).read_bytes()
    checked = node_spec.resolve_workflow(json.loads(raw))
    return dict(title=item['title'], workflow=checked['document'],
                template=dict(id=value['id'], sha256=hashlib.sha256(raw).hexdigest()),
                execution_authorized=False)
