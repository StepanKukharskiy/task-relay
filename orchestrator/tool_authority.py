"""Provider-neutral authority checks before model submission and tool effects.

A prompt, sandbox setting or after-start event is not an execution gate. A
transport that executes tools itself must supply a qualified enforcement path;
otherwise the same rule that protects Relay dispatch stops that transport.
"""
from .runtime_outcomes import Hold


CONTRACT = 'relay-tool-authority-v1'


def manifest(declarations, *, hosted_tools=()):
    names=[tool['name'] for tool in declarations]
    if any(not isinstance(name,str) or not name for name in names) or len(names)!=len(set(names)):
        raise ValueError('Tool authority needs distinct nonempty declaration names')
    hosted=list(hosted_tools)
    if len(hosted)!=len(set(hosted)) or set(names)&set(hosted):
        raise ValueError('Ambiguous hosted and Relay tool authority')
    return dict(version=1,dynamic_tools=sorted(names),hosted_tools=sorted(hosted))


def ceiling(*surfaces):
    """Register the finite lifecycle surface; current dispatch stays narrower."""
    import copy
    registered={}
    for surface in surfaces:
        manifest(surface)
        for tool in surface:
            if tool['name'] in registered and registered[tool['name']]!=tool:
                raise ValueError('Conflicting lifecycle declaration: '+tool['name'])
            registered[tool['name']]=copy.deepcopy(tool)
    return list(registered.values())


def require_relay_dispatch(execution_owner, enforcement=None):
    qualified=(isinstance(enforcement,dict) and enforcement.get('contract')==CONTRACT
               and enforcement.get('pre_execution') is True and enforcement.get('qualified') is True
               and isinstance(enforcement.get('evidence_sha256'),str) and len(enforcement['evidence_sha256'])==64)
    if execution_owner != 'relay' and not qualified:
        raise Hold('tool_boundary_unqualified',
            'The selected transport can execute tools outside Relay and has no '
            'qualified pre-execution authority gate. No model request may be '
            'submitted. A prompt, tool-hiding settings or after-start detection '
            'does not establish isolation.', phase='compile')


class Denied(ValueError):
    """A received proposal was refused before any local tool effect."""


def validate_batch(calls, declarations):
    """Reject the entire received batch before any of its calls have effects.

    Recovery uses its current registered declarations too. There is no
    namespace/prefix exception and a model cannot extend this authority.
    """
    names = {tool['name'] for tool in declarations}
    denied = sorted({call['name'] for call in calls if call['name'] not in names})
    if denied:
        raise Denied('Tools outside the current Relay authority: '+', '.join(denied)+
                     '. No calls from this response executed.')
