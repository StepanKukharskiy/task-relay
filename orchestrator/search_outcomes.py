"""Provider-neutral stop policy for a confirmed unavailable search batch.

Adapters prove rejection; this boundary never derives certainty from prose or
HTTP codes alone. Retaining partial evidence is not acceptance or retry authority.
"""


def unavailable(error):
    if error.uncertain or error.status not in (429, 503, 'serverOverloaded'):
        return None
    return dict(version=1, status='unavailable', external_outcome='rejected',
        provider_status=error.status, evidence=error.detail, usage=None,
        retry_allowed=False, acceptance=False,
        recovery='Retain earlier observations; stop remaining batch submissions. '
                 'Use already observed evidence or a separately authorized alternative. '
                 'This receipt grants no replay or additional capacity.')
