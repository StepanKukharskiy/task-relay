"""Read-only desktop discovery of saved workflows and registered operations."""
from contextlib import closing
import json

from .desktop_tasks import DesktopTaskError, _database, _table
from .relay_paths import PATHS


def _object(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def workflows(kind='linked', offset=0, paths=PATHS):
    tables = {'linked': 'workflows', 'runs': 'production_runs', 'plans': 'production_plans'}
    if kind not in tables or type(offset) is not int or not 0 <= offset <= 1000000:
        raise DesktopTaskError('Choose a workflow category and valid page.')
    result = {'items': [], 'total': 0, 'next_offset': None, 'kind': kind}
    if not paths.state.is_file():
        return result
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        table = tables[kind]
        if not _table(db, table):
            return result
        result['total'] = db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
        def channel(entity, category):
            if not _table(db, 'relay_channel_bindings'):
                return 'Channel not recorded'
            saved = db.execute('SELECT channel FROM relay_channel_bindings WHERE kind=? AND entity=? ORDER BY after_row DESC LIMIT 1', (category, entity)).fetchone()
            return saved[0] if saved else 'Channel not recorded'
        rows = db.execute(f'SELECT * FROM {table} ORDER BY rowid DESC LIMIT 40 OFFSET ?', (offset,))
        for row in rows:
            if kind == 'linked':
                data = _object(row['data'])
                item = dict(id=row['name'], title=row['name'], status=data.get('status', 'Unknown'),
                            detail=' · '.join(str(data.get(k) or '') for k in ('phase', 'cwd', 'reason')),
                            request=data.get('direction', ''), channel=channel(row['name'], 'workflow'), revision=row['revision'])
            elif kind == 'plans':
                item = dict(id=row['id'], title=row['request'].split('\n')[0][:180],
                            status=row['status'], request=row['request'], channel=row['channel'],
                            detail=row['error'] or ('Run: ' + row['run'] if row['run'] else 'No run started'))
            else:
                plan = _object(row['plan'])
                steps = [dict(r) for r in db.execute(
                    'SELECT id,status,attempts FROM production_tasks WHERE run=? ORDER BY rowid',
                    (row['id'],))] if _table(db, 'production_tasks') else []
                item = dict(id=row['id'], title=plan.get('title') or plan.get('name') or row['id'],
                            status=row['status'], request=plan.get('goal', ''), channel=channel(row['id'], 'production'),
                            detail='Recorded execution stages', steps=steps)
            result['items'].append(item)
        if offset + len(result['items']) < result['total']:
            result['next_offset'] = offset + len(result['items'])
    return result


def automation_tools():
    from orchestrator.execution import catalog
    from orchestrator.executors import catalog as executors
    from . import capabilities, file_tools, gemini, orchestrator_web
    names = {
        'text.bundle': 'Bundle text files with source identities', 'gemini.text': 'Generate text with Gemini',
        'blender.startup': 'Check Blender startup', 'blender.scene': 'Build a Blender scene from primitives',
        'blender.mesh_scene': 'Build a Blender scene from mesh data', 'blender.inspect': 'Inspect an existing Blender scene',
        'blender.run_python': 'Apply a reviewed Blender script', 'blender.import_asset': 'Import selected Blender assets',
        'blender.animate': 'Animate and render a bounded Blender scene',
        'rhino.startup': 'Check Rhino startup', 'rhino.inspect': 'Inspect a Rhino model',
        'rhino.run_python': 'Create or edit a Rhino model with reviewed code', 'rhino.render': 'Render a named Rhino view',
    }
    fields = ('id', 'version', 'kind', 'available', 'availability_evidence', 'input_types',
              'output_type', 'outputs', 'criteria', 'permissions', 'seconds', 'external_requests')
    from orchestrator.browser_contract import definitions as browser_definitions
    actions = [dict(id=d['name'], description=d['description'],
                    availability='Bounded browser executor; configuration and origin scope required',
                    route='Request a browser workflow, review its website and action scope, then Start. Not a general unrestricted browser control.')
               for d in browser_definitions()]
    for definition in (*file_tools.DEFINITIONS, orchestrator_web.SEARCH, orchestrator_web.FETCH):
        actions.append(dict(id=definition['name'], description=definition['description'],
                            availability='Requires a configured Gemini provider' if definition['name'] == 'web_search' and not gemini.read_config() else 'Available through the Relay assistant',
                            route='Ask in Telegram or Messages; file access follows the selected project scope.'))
    descriptions = {
        'generate_image': 'Generate or revise an image using selected references.',
        'collect_references': 'Freeze selected project references with version identities.',
        'delegate_task': 'Send a bounded instruction to an existing compatible agent job.',
        'plan_production': 'Draft a pipeline with steps, outputs, checks and limits.',
        'authorize_production_plan': 'Review a saved plan before starting its exact scope.',
        'replace_selection': 'Review replacing an accepted artifact version and its dependencies.',
        'continue_production': 'Propose the next bounded stage from selected outputs.',
        'resume_production': 'Resume eligible remaining work after an explicit decision.',
        'route_task': 'Route work to the selected existing job.',
        'choose_task': 'Choose among relevant existing jobs.',
        'create_production_folder': 'Create a managed folder for production work.',
        'import_production_research': 'Import selected research into the production context.',
        'start_production': 'Start the reviewed production scope.',
        'revise_production': 'Create a new revision without overwriting previous work.',
        'plan': 'Plan a bounded iteration of a linked workflow.',
        'run': 'Run the approved bounded linked workflow.',
        'pause': 'Pause future linked-workflow dispatch.',
        'resume': 'Resume an eligible paused linked workflow.',
        'stop': 'Stop future linked-workflow dispatch.',
    }
    for ident in (*capabilities.IMMEDIATE, *capabilities.GATED):
        actions.append(dict(id=ident, description=descriptions.get(ident, ident.replace('_', ' ').capitalize()),
                            availability=('Provider configuration required' if ident == 'generate_image' and not gemini.read_config() else 'Supported; scope and configuration checked when requested'),
                            route='Ask in the original Relay channel. Desktop planning is in Workflows.' if ident != 'generate_image' else 'Ask for an image in Telegram or Messages; generation may incur API charges.'))
    actions.extend([
        dict(id='discover_guides', description='Find reusable guides in known project folders.', availability='Read-only discovery', route='Ask the Relay assistant to find a guide; select it before use.'),
        dict(id='perplexity.search', description='Create and continue a Perplexity Search conversation.', availability='Account-browser pilot; live qualification incomplete', route='Connect the dedicated browser profile through Relay. No general Computer workflow or upload support.'),
        dict(id='desktop.jobs', description='Create provider jobs, send text or .md attachments, inspect history and decide pending Codex/Claude requests.', availability='Desktop controls; current service required for sending', route='Open Jobs. Review the exact request before Allow once or Deny.'),
    ])
    from . import api_providers, credentials
    providers = [dict(id=name, description=name.capitalize() + ' text jobs',
                      availability='Credential available locally; generation not verified' if credentials.status(PATHS.data / (name + '.json'))['available'] else 'Connect this provider in Setup',
                      route='Create a job in Jobs, then send your instruction.')
                 for name in ('gemini', *api_providers.SPECS)]
    providers.extend([
        dict(id='codex', description='Existing Codex jobs', availability='Requires a connected Codex desktop job', route='Choose an existing job in Jobs. Permission requests appear under Needs your decision.'),
        dict(id='claude', description='Claude jobs and tool permissions', availability='Requires the optional configured Claude runtime', route='Choose Claude when creating a job; review tool permissions in Jobs.'),
    ])
    return {'tools': [dict(title=names.get(entry['id'], entry['id']), **{k: entry[k] for k in fields if k in entry}) for entry in catalog()],
            'actions': actions, 'executors': providers + executors(),
            'automatic_extraction': False, 'scheduling': False}
