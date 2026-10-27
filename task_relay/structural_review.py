"""Prospective compiler policy for code-verified composition, never acceptance.

Policies select registered native adapters, not task names or business domains.
Only compiler-generated structural reviews may be elided. Semantic partition
reviews, explicit user gates and requested review artifacts remain in the graph.
"""
import copy


POLICIES={'reviewed-record-merge': 'exact reviewed partitions, complete coverage and preserved source versions'}


def elide(plan, producer, reviewer, native, scope, deliverables):
    if scope.get('structural_review_policy_version')!=1:return None
    reason=POLICIES.get(native.get('native_adapter'))
    if (not reason or native.get('kind')!='procedure' or native.get('external_requests')!=0
            or producer.get('user_gate') or reviewer.get('user_gate')
            or reviewer.get('final_quality') or reviewer.get('outcome_review')
            or any(c.get('validation') for c in producer.get('output_contracts',[]))
            or reviewer.get('criteria')!=native.get('criteria')):return None
    rid=reviewer['id']
    # A review report may itself be a promised output or exact downstream input.
    # Never substitute native evidence for a requested model-authored artifact.
    if any(v.get('task')==rid for v in deliverables.values()):return None
    if any(i.get('from_task')==rid for task in plan['tasks'] for i in task.get('inputs',[])):return None
    receipt=dict(producer=producer['id'],removed_review=copy.deepcopy(reviewer),
        native_adapter=native['native_adapter'],verification=reason,acceptance=False,
        source='frozen structural_review_policy_version=1')
    plan['tasks'].remove(reviewer)
    for task in plan['tasks']:
        task['dependencies']=list(dict.fromkeys(producer['id'] if dep==rid else dep
                                                for dep in task.get('dependencies',[])))
    return receipt
