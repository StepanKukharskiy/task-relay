"""Compose task workers from frozen, registered execution profiles.

Roles and assignments are generated per request. This registry describes actual
adapter abilities, not permissions inferred from a role or a model's knowledge.
Resolution only proposes a binding; approval and dispatch retain their own checks.
"""
import copy
from pathlib import PurePosixPath

from . import executors

CAPABILITIES = {
    'images.view': 'Visually inspect declared local image pixels, not just metadata or Python statistics.',
    'files.text': 'Read declared text and write text deliverables.',
    'files.binary': 'Inspect or produce binary files using local file/code tools; format libraries must be checked separately.',
    'code.execute': 'Execute local code within the selected adapter boundaries (Codex shell or isolated Python); native registered operations remain separate.',
    'browser.use': 'Use browser tools with an explicit origin, action and transfer contract.',
    'browser.capture': 'Save explicitly granted viewport PNG screenshots and provenance; inspect PNG metadata, not visual content.',
}
TEXT_TYPES = {'text/plain', 'text/markdown', 'text/x-python', 'text/x-ruby', 'application/json', 'text/csv'}
TEXT_SUFFIXES = {'.txt', '.md', '.json', '.csv', '.py', '.rb', '.js', '.html', '.css', '.xml', '.yaml', '.yml'}


def abilities(backend):
    tools = executors.validate(backend)
    result = ['files.text']
    if 'shell' in tools or 'python' in tools:result += ['files.binary', 'code.execute']
    if backend['type']=='codex-cli':result += ['images.view']
    if 'browser' in tools:result += ['browser.use','browser.capture']
    return result


def entry(backend):
    return dict(id=backend['type'], backend=copy.deepcopy(backend),
                capabilities=abilities(backend), tools=executors.validate(backend),
                limits=executors.limits_for(backend) if backend['type'] in executors.API_TYPES
                else dict(seconds=1800, tool_calls=60, output_bytes=100000000))


def capture(state, default, locked=False):
    """Read local availability only. No model calls, probes or installation."""
    result = [entry(default)]
    if not locked:
        for candidate in executors.catalog(state):
            if candidate['available'] and candidate['id'] != default['type']:
                result.append(entry(candidate['backend']))
    from task_relay import code_runtime
    for item in result:
        if item['backend']['type'] in executors.CODE_TYPES:
            runtime=code_runtime.available(item['backend']['runtime'])
            item['runtime_tools']=runtime['tools']
            item['restrictions']='Python only; no network, subprocesses, package installation or native apps. 120 seconds per code call. Binary inputs stay local; code logs and read text may be sent to the selected model.'
    return result


def requirements(value):
    if (not isinstance(value, list) or not value or len(value) > len(CAPABILITIES)
        or any(not isinstance(x, str) or x not in CAPABILITIES for x in value)
        or len(set(value)) != len(value)):
        raise ValueError('Worker requires distinct registered capabilities: '+', '.join(CAPABILITIES))
    return value


def has_binary(task):
    for item in task.get('inputs', []) + task.get('outputs', []):
        mime = item.get('media_type')
        suffix = PurePosixPath(item['path']).suffix.lower()
        if (mime and mime not in TEXT_TYPES) or (suffix and suffix not in TEXT_SUFFIXES):return True
    return False


def matches(task, required, backend):
    caps = set(abilities(backend))
    if any(i.get('visual_reference') for i in task.get('inputs',[])) and 'images.view' not in caps:return False
    # Never grant website access merely to satisfy a text-only role.
    if ('browser.use' in caps) != ('browser.use' in required):return False
    if any(i['path'].startswith('operation-support/') and i['path'].endswith('/validate.py')
           for i in task.get('inputs',[])) and 'code.execute' not in caps:return False
    capture_files=False
    if 'browser.capture' in caps:
        from .browser_contract import png_input,validate_files
        try:
            validate_files(task)
            capture_files=all(png_input(i) or not has_binary({'inputs':[i]}) for i in task.get('inputs',[]))
        except ValueError:pass
    return (set(required) <= caps and (not has_binary(task) or 'files.binary' in caps or capture_files)
            and (not task.get('browser') or 'browser.use' in required))


def resolve(task, catalog, default):
    """Replace an untrusted requirement with an exact service-owned binding."""
    request = task.get('worker')
    if not isinstance(request, dict) or set(request)-{'requires','executor'} or 'requires' not in request:
        raise ValueError('Worker specifies requires and optionally a frozen executor ID; no model, command or tool injection.')
    required = requirements(request['requires'])
    preferred = request.get('executor')
    if preferred is not None and (not isinstance(preferred,str) or not any(x['id']==preferred for x in catalog)):
        raise ValueError('Requested worker executor is outside the frozen catalog; no fallback.')
    candidates = [x for x in catalog if (preferred is None or x['id']==preferred)
                  and matches(task, required, x['backend'])]
    if not candidates:
        detail=''
        if any(i['path'].startswith('operation-support/') and i['path'].endswith('/validate.py')
               for i in task.get('inputs',[])):
            detail=' Bound operation validator inputs require code.execute; a text-only worker cannot run validation.'
        offered='; '.join(x['id']+': '+', '.join(x['capabilities']) for x in catalog
                          if preferred is None or x['id']==preferred)
        raise ValueError('No eligible worker for '+', '.join(required)+'.'+detail+
                         ' Frozen profiles: '+offered+'. Check required file formats and available executors; no fallback or installation.')
    # Automatic composition uses the narrowest suitable adapter, preferring
    # bounded API file/Python workers over a general shell. Named executors are
    # filtered above; locked catalogs contain only the user's chosen profile.
    # Model names are configured, never invented or ranked by guessed cost.
    candidates.sort(key=lambda x: (len(x['capabilities']), x['backend']['type'].split('-')[0]!=default['type'].split('-')[0], x['id']=='codex-cli',
                                   x['backend'] != default, x['id']))
    chosen = candidates[0]
    expected = executors.validate(chosen['backend'])
    if 'tools' in task and task['tools'] != expected:
        raise ValueError('Worker tools conflict with the resolved executor/provider; omit tools when using worker requirements.')
    task['tools'] = expected
    task['worker'] = dict(version=1, requires=list(required), executor=chosen['id'], backend=copy.deepcopy(chosen['backend']))
    validate(task)
    return task


def validate(task):
    worker = task.get('worker')
    if not isinstance(worker,dict) or set(worker)!={'version','requires','executor','backend'} or type(worker['version']) is not int or worker['version']!=1:
        raise ValueError('Invalid frozen worker binding.')
    if task.get('execution'):raise ValueError('Registered operations cannot carry an agent worker binding.')
    required = requirements(worker['requires'])
    backend = worker['backend']
    profile = executors.validate(backend)
    if worker['executor'] != backend['type'] or task.get('tools') != profile or not matches(task,required,backend):
        raise ValueError('Frozen worker capabilities, inputs or tools do not match its executor.')
    if 'browser.use' in required and not task.get('browser'):
        raise ValueError('Browser workers require an explicit browser contract.')


def backend_for(task, default):
    if 'worker' in task:
        validate(task)
        return task['worker']['backend']
    return default


def needs_approval(plan):
    """Whole-workflow grants cannot silently change the execution provider."""
    return any('worker' in t and backend_for(t,plan['backend']) != plan['backend'] for t in plan['tasks'])
