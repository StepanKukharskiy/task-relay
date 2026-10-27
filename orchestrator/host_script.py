"""Shared, dependency-free bounds for prepared and executable host scripts."""
MAX_SCRIPT_BYTES = 100000


def preparation_context(capability):
    """Read context from the registered executor, never a model-created contract."""
    import copy
    from importlib import import_module
    from .native_apps import profile
    value = getattr(import_module('orchestrator.' + profile(capability).contract_module), 'SCRIPT_CONTEXT', None)
    return copy.deepcopy(value)


def bind_preparers(plan, *, graph=None, editable=None):
    """Supply consuming script runtimes to future producers, including Run node.

    This adds no task, tool, permission, artifact or execution allowance. Existing
    executed assignments are not passed here and must never be rewritten.
    """
    import json
    from .native_apps import SCRIPT_OPERATIONS, profile
    targets = {t['id']: t for t in plan['tasks']}
    editable = set(targets) if editable is None else set(editable)
    contexts = {}
    for consumer in (graph or plan)['tasks']:
        cap = consumer.get('execution', {}).get('capability')
        if cap not in SCRIPT_OPERATIONS: continue
        context = preparation_context(cap)
        if context is None: continue
        for item in consumer['inputs']:
            ident = item.get('from_task')
            if ident not in editable or ident not in targets or item.get('media_type') != profile(cap).script_media: continue
            source = targets[ident]
            if source.get('execution'): continue
            if not any(o['path'] == item['output'] and o.get('media_type') == profile(cap).script_media for o in source['outputs']):
                raise ValueError('Script preparation output binding changed')
            contexts.setdefault(ident, {})[(cap, item['output'])] = context
    marker = '\n\nRegistered script execution context (code-owned):\n'
    for ident, entries in contexts.items():
        source = targets[ident]
        # Recompilation is idempotent, and never duplicates a prior binding.
        document = [dict(operation=cap, output=output, runtime=value) for (cap, output), value in sorted(entries.items())]
        suffix = marker + json.dumps(document, ensure_ascii=False, sort_keys=True)
        if not source['instruction'].endswith(suffix):source['instruction'] += suffix


def validate_script_bytes(data):
    if not data or len(data) > MAX_SCRIPT_BYTES:
        raise ValueError('Host script must be 1–100000 bytes; got %s. Prepare a smaller script before execution.' % len(data))
    return data


def validate_prepared(frozen, workspace):
    """Check selected host-code drafts before a reviewer can accept them."""
    supported = ('blender.run_python', 'rhino.run_python', 'rhino.grasshopper', 'rhino3dm.run_python', 'sketchup.run_ruby')
    if frozen.get('execution') or frozen.get('review_of'):
        return
    if not any(i['path'] == 'operation-support/' + cap + '/contract.json'
               for i in frozen['inputs'] for cap in supported):
        return
    from .runtime import safe_file
    for name in frozen.get('selection_outputs', []):
        if name.endswith(('.py', '.rb')):
            validate_script_bytes(safe_file(workspace, name).read_bytes())
