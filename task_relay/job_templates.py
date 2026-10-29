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
        tools=['Perplexity', 'Codex', 'Blender', 'Gemini', 'PowerPoint export'],
        filename='cellular-aggregation.workflow.json'),
    'support-first-ca': dict(
        title='Support-first CA · cells to timber reel',
        description='Replay the bundled support-first CA graph as cells becoming timber, synthesize graph-driven music, and assemble a 12-second vertical reel with a new AI visualization.',
        requirements='Includes the saved CA graph, Blender script, scene checks and brief. Configure Codex, isolated Local Python, Blender, Gemini and the local HyperFrames runtime. Review native and paid execution before Run. Run Preview before selecting Export final reel.',
        tools=['Codex', 'Python', 'Blender', 'Gemini', 'HyperFrames', 'FFmpeg'],
        filename='support-first-ca.workflow.zip'),
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
    path = files('task_relay').joinpath('assets', 'job-templates', item['filename'])
    if item['filename'].endswith('.zip'):
        from .workflow_transfer import preview
        package = preview({'path': str(path)})
        if package['missing_files']:
            raise ValueError('Bundled template inputs are missing')
        return dict(title=package['title'], package=dict(path=str(path), sha256=package['sha256'], files={}),
                    execution_authorized=False)
    raw = path.read_bytes()
    checked = node_spec.resolve_workflow(json.loads(raw))
    return dict(title=item['title'], workflow=checked['document'],
                template=dict(id=value['id'], sha256=hashlib.sha256(raw).hexdigest()),
                execution_authorized=False)
