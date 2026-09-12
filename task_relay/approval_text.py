"""Human-readable approval cards with literal action details and native entities."""
import re

from task_relay.telegram_text import Text


def label(key):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', str(key)).replace('_', ' ').capitalize()


def fields(out, values, prefix=''):
    """Display nested scope fields without JSON syntax or silently dropping values."""
    for key, value in values.items():
        if value is None:
            continue
        name = prefix + label(key)
        if isinstance(value, dict) and value:
            fields(out, value, name + ' / ')
        elif isinstance(value, list):
            if not value:
                out.add(name + ': none\n')
            for item in value:
                if isinstance(item, dict):
                    fields(out, item, name + ' / ')
                else:
                    out.add(name + ': ')
                    out.styled(str(item), 'code')
                    out.add('\n')
        else:
            out.add(name + ': ')
            rendered = ('yes' if value else 'no') if isinstance(value, bool) else ('none' if value == {} else str(value))
            out.styled(rendered, 'code')
            out.add('\n')


def render(title, request, detail, allow, too_large=False):
    from task_relay.codex_approvals import COMMAND, FILE, PERMISSIONS, METHODS
    out = Text()
    p, method = request['params'], request['method']
    network = method == COMMAND and p.get('networkApprovalContext')
    heading = 'Network access' if network else {
        FILE: 'Approve file changes?', COMMAND: 'Run this command?',
        PERMISSIONS: 'Grant permissions for this turn?'}.get(method, 'Codex needs your input')
    out.styled(heading, 'bold')
    out.add('\n' + title[:160] + '\n\n')
    if p.get('reason') and not too_large:
        out.add(str(p['reason']) + '\n\n')
    if too_large:
        out.add('This request is too large to review here. Open the task in Codex to inspect the complete details.\n')
    elif method not in (COMMAND, FILE, PERMISSIONS):
        out.add('Answer this question or connector request in the desktop app.\n')
    elif method == FILE:
        changes = detail.get('fileChange', {}).get('changes', [])
        if not changes:
            out.add('The proposed changes are unavailable here. Review them in Codex.\n')
        for change in changes:
            kind = change.get('kind', {})
            operation = kind.get('type', 'change') if isinstance(kind, dict) else str(kind)
            out.styled({'update': 'Edit', 'add': 'Create', 'delete': 'Delete'}.get(operation, label(operation)), 'bold')
            out.add(' ')
            out.styled(str(change.get('path', '(path unavailable)')), 'code')
            out.add('\n')
            if isinstance(kind, dict):
                fields(out, {k: v for k, v in kind.items() if k != 'type'})
            diff = change.get('diff')
            if isinstance(diff, str) and diff:
                lines = diff.splitlines()
                added = sum(s.startswith('+') and not s.startswith('+++') for s in lines)
                removed = sum(s.startswith('-') and not s.startswith('---') for s in lines)
                out.add(f'+{added} / −{removed} lines\n\n')
                out.styled(diff, 'pre', {'language': 'diff'})
                out.add('\n\n')
            fields(out, {k: v for k, v in change.items() if k not in ('kind', 'path', 'diff')})
        if p.get('grantRoot'):
            fields(out, {'Requested folder access': p['grantRoot']})
    elif method == COMMAND:
        if network:
            fields(out, p['networkApprovalContext'], 'Destination / ')
            out.add('\n')
        if p.get('cwd'):
            out.add('Folder: ')
            out.styled(str(p['cwd']), 'code')
            out.add('\n\n')
        if p.get('command'):
            out.styled(str(p['command']), 'pre')
            out.add('\n\n')
        if not p.get('command') and not network:
            fields(out, {'Command actions': p.get('commandActions')})
    elif method == PERMISSIONS:
        if p.get('cwd'):
            fields(out, {'Folder': p['cwd']})
        fields(out, p.get('permissions', {}))
    # Omit routing IDs, timing, duplicated parsed commands, and proposals for
    # persistent rules: the relay only submits accept/decline or turn scope.
    # Additional permissions and unfamiliar fields must still be visible.
    known = {'threadId', 'turnId', 'itemId', 'startedAtMs', 'reason'}
    known |= {FILE: {'grantRoot'}, COMMAND: {'command', 'cwd', 'commandActions',
                'networkApprovalContext', 'availableDecisions', 'proposedExecpolicyAmendment',
                'proposedNetworkPolicyAmendments'}, PERMISSIONS: {'permissions', 'cwd'}}.get(method, set())
    if not too_large and method in (COMMAND, FILE, PERMISSIONS):
        fields(out, {k: v for k, v in p.items() if k not in known})
    out.add('\n')
    if allow:
        scope = ('Grant the displayed permissions for this turn only.' if method == PERMISSIONS else
                 'Allow these changes once.' if method == FILE else
                 'Allow this destination request; it may unblock multiple queued connections.' if network else
                 'Run once. No command rule will be saved.')
        out.add(scope + '\nUse the buttons below.')
    elif method in METHODS:
        out.add('Approval requires desktop review. You can deny below.')
    return out.result()
