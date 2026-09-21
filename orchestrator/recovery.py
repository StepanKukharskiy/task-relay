"""Recovery policy for trusted adapter evidence, never provider-authored advice.

Decisions are recommendations for a new bounded plan, not execution grants.
Unknown or conflicting evidence always requires reconciliation before retry.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    execution: str = 'unknown'  # not_started, failed, completed, unknown
    quiescent: bool = False
    repairable: bool = False
    reason: str = 'Execution outcome is not established.'


def decide(evidence):
    if not evidence.quiescent or evidence.execution == 'unknown':
        action = 'reconcile'
    elif evidence.execution == 'not_started':
        action = 'retry_unchanged'
    elif evidence.execution == 'failed' and evidence.repairable:
        action = 'prepare_reviewed_repair'
    elif evidence.execution == 'completed':
        action = 'retain_result'
    else:
        action = 'resolve_environment'
    return {'policy_version': 1, 'action': action, 'reason': evidence.reason,
            'automatic_dispatch': False}
