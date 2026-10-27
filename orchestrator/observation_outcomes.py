"""Separate completed read observations from later failed model generation.

Adapters normalize correlated terminal and tool receipts. This rule grants no
retry or acceptance, and cannot discharge an unfinished or unobserved tool call.
"""
def retained_reads(terminal, completed_ids, pending_ids):
    if (not isinstance(terminal,dict) or not terminal.get('id') or terminal.get('status')!='failed'
            or not isinstance(terminal.get('error'),dict) or not terminal['error']
            or pending_ids or not completed_ids
            or any(not isinstance(ident,str) or not ident for ident in completed_ids)):
        return None
    return dict(version=1,status='observed',generation_status='failed',
        generation_error=terminal['error'],turn=terminal['id'],completed_read_ids=sorted(set(completed_ids)),
        replayed=False,acceptance=False,provider_requests=None)
