"""Read-only follow-up reviews: exact evidence, no producer gate or replay."""
from . import contracts as c

INSTRUCTIONS = '''A review_of for a new producer is its single completion gate.
A review_of for an already completed producer creates an independent snapshot
assessment when review_snapshot_version:1 is granted. Include all other exact
deliverables and evidence in inputs for a combined final review. Code pins their
versions; this review cannot reopen producers or replace earlier verdicts.
Do not declare outputs for either review. To review a still-running producer,
wait for its existing reviewer; never add another gate or an ordinary report
worker as a substitute. Ordinary worker outputs use [{name,media_type,purpose}].'''


def validate(spec):
    policy=spec.get('review_snapshot')
    if policy is None:return
    if (not spec.get('review_of') or not isinstance(policy,dict)
            or set(policy)!={'version','attempts'} or type(policy['version']) is not int
            or policy['version']!=1 or not isinstance(policy['attempts'],dict)
            or set(policy['attempts'])!={i['from_task'] for i in spec['inputs'] if 'from_task' in i}
            or spec['review_of'] not in policy['attempts']):
        raise ValueError('Invalid exact review snapshot')
    for ident,attempt in policy['attempts'].items():
        c.label(ident);c.nonempty(attempt,'Review snapshot attempt')


def pin(rt,run,spec):
    """Called after shared handoff/companion compilation, before atomic admission."""
    spec['review_snapshot']=dict(version=1,attempts={
        i['from_task']:rt.task(run,i['from_task'])['latest']
        for i in spec['inputs'] if 'from_task' in i})
    check(rt,run,spec)


def check(rt,run,spec):
    validate(spec)
    if not spec.get('review_snapshot'):return
    for ident,attempt in spec['review_snapshot']['attempts'].items():
        task=rt.task(run,ident)
        if task['latest']!=attempt or task['status']!='completed':
            raise ValueError('Review snapshot requires unchanged completed candidates: '+ident)

