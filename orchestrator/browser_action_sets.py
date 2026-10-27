"""Registered DOM action descriptions; no site execution, scheduling or authority."""
from urllib.parse import urlsplit, parse_qs


ACTION_SETS = {
    'xFigura actions': {
        'origin': 'https://app.xfigura.ai',
        'path': '/designer',
        'selection_parameter': 'nodeId',
        'actions': ({
            'id': 'generate',
            'label': 'Generate',
            'selector': 'div.cursor-pointer.pointer-events-auto.bg-brand:has(> div > div > p)',
        },),
    },
}


def validate_grants(grants):
    if not isinstance(grants, list) or len(grants) > len(ACTION_SETS):
        raise ValueError('Choose registered custom browser action sets')
    names = set()
    for grant in grants:
        if (not isinstance(grant, dict) or set(grant) != {'name', 'mode'}
                or not isinstance(grant['name'], str) or grant['name'] not in ACTION_SETS
                or grant['mode'] not in ('observe', 'interact') or grant['name'] in names):
            raise ValueError('Custom browser actions need a unique registered name and observe/interact mode')
        names.add(grant['name'])
    return grants


def applicable(policy, url):
    """Exact website/route and an explicit selected node; never arbitrary selectors."""
    parsed = urlsplit(url)
    for grant in validate_grants(policy.get('custom_actions', [])):
        spec = ACTION_SETS[grant['name']]
        if parsed.scheme + '://' + parsed.netloc != spec['origin'] or parsed.path != spec['path']:
            continue
        selected = parse_qs(parsed.query).get(spec['selection_parameter'], [])
        if len(selected) != 1 or not selected[0] or len(selected[0]) > 256:
            continue
        yield grant, spec, selected[0]


def check_interaction(policy, descriptor, operation):
    name = descriptor.get('action_set')
    if not name:
        return
    grant = next((g for g in validate_grants(policy.get('custom_actions', [])) if g['name'] == name), None)
    if not grant or grant['mode'] != 'interact':
        raise ValueError('Custom browser action is observation-only; no click is authorized')
    if operation != 'click':
        raise ValueError('Registered custom browser actions support only browser_click')
    if descriptor.get('disabled'):
        raise ValueError('Custom browser action is disabled')
