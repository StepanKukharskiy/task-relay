"""Shared, dependency-free bounds for prepared and executable host scripts."""
MAX_SCRIPT_BYTES = 100000


def validate_script_bytes(data):
    if not data or len(data) > MAX_SCRIPT_BYTES:
        raise ValueError('Host script must be 1–100000 bytes; got %s. Prepare a smaller script before execution.' % len(data))
    return data


def validate_prepared(frozen, workspace):
    """Check selected host-code drafts before a reviewer can accept them."""
    supported = ('blender.run_python', 'rhino.run_python')
    if frozen.get('execution') or frozen.get('review_of'):
        return
    if not any(i['path'] == 'operation-support/' + cap + '/contract.json'
               for i in frozen['inputs'] for cap in supported):
        return
    from .runtime import safe_file
    for name in frozen.get('selection_outputs', []):
        if name.endswith('.py'):
            validate_script_bytes(safe_file(workspace, name).read_bytes())
