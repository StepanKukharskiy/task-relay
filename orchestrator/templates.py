"""Three small stage templates; all use the same factory and scheduler.

These are bounded starting assignments, not a claim of autonomous planning.
Input artifact IDs, their purposes, and the production model are supplied by the
caller. More production stages can be added as explicit graph assignments.
"""
from .contracts import plan

STAGES = {
    'competition': {
        'role': 'brief analyst',
        'objective': 'Produce one evidence-linked competition program and constraint matrix',
        'instruction': 'Read the supplied brief and references. Extract the required program, numerical constraints, source locations and unresolved interpretations into program.md and program.json. Keep dimensional authority separate from visual inspiration. Do not design, solve, invent compliance, or treat counts in a schedule as proof that an image contains those units.',
        'files': ['program.md', 'program.json'],
        'criteria': ['Every requirement cites its source and retains units, quantities and uncertainty.',
                     'Authority is purpose-specific; visual inspiration does not establish geometry or compliance.',
                     'Missing or conflicting constraints are explicit; no design or feasibility result is invented.'],
        'gate': 'program interpretation',
    },
    'carousel': {
        'role': 'storyboard editor',
        'objective': 'Prepare one carousel-to-reel storyboard from selected approved cards',
        'instruction': 'Read the selected cards, assets, current request and applicable guides. Resolve adaptation mode from the current request and established applicable preferences; ask only if evidence leaves it unresolved. Write storyboard.md and correspondence.json mapping every title, card order, image and background to source versions. In exact mode preserve approved material. Summarize only when authorized. Identify duration/readability conflicts. Do not render or regenerate assets in this stage.',
        'files': ['storyboard.md', 'correspondence.json'],
        'criteria': ['Every storyboard element maps to exact source cards/assets and preserves applicable requirements.',
                     'Adaptation mode follows scoped evidence; no unauthorized compression or inappropriate earlier-job carryover.',
                     'Timing, readability conflicts and unresolved decisions are explicit; no rendered quality is claimed.'],
        'gate': 'storyboard selection',
    },
    'office-anime': {
        'role': 'episode continuity editor',
        'objective': 'Prepare one bounded episode production handoff',
        'instruction': 'Read the current episode request, character references, selected performances and timing artifacts. Write episode-handoff.md and continuity.json specifying what is carried forward, what must be newly produced and what remains unverified. Voice IDs alone do not establish performance identity. Keep assistant-reported technical results distinct from user acceptance. Do not regenerate images, speech or render in this preparation stage.',
        'files': ['episode-handoff.md', 'continuity.json'],
        'criteria': ['Every carried-forward character, performance and timing reference identifies its artifact and purpose.',
                     'Current work is distinct from earlier reported completion and scoped user selections.',
                     'Uncertainty and remaining human judgments are explicit; no invented performance or visual acceptance.'],
        'gate': 'episode handoff selection',
    },
}


def build(name, run_id, inputs, backend):
    stage = STAGES[name]
    outputs = [{'path': p, 'purpose': stage['objective']} for p in stage['files']]
    producer = dict(id='produce', role=stage['role'], objective=stage['objective'], instruction=stage['instruction'],
        inputs=inputs, outputs=outputs, criteria=stage['criteria'], user_gate=stage['gate'], max_attempts=2)
    review = dict(id='review', role='independent reviewer', objective='Review the actual stage artifacts against their sources',
        instruction='Inspect the supplied candidate files and original references independently. Write review.md with evidence for every criterion. Return accept, a concrete scoped revise instruction, or blocked. Do not rewrite the candidate or infer user selection from your judgment.',
        review_of='produce', dependencies=['produce'], max_attempts=2, criteria=stage['criteria'],
        inputs=inputs + [{'from_task':'produce','output':o['path'],'path':'candidate/'+o['path'],
                          'purpose':o['purpose'],'authority':'Unaccepted candidate to review'} for o in outputs],
        outputs=[{'path':'review.md','purpose':'Independent model review'}])
    if backend.get('type')=='gemini-agent':
        from .executors import GEMINI_LIMITS
        for task in (producer,review):task.update(tools=['files'],limits=GEMINI_LIMITS.copy())
    return plan(dict(id=run_id, brief=stage['objective'], backend=backend, tasks=[producer,review], concurrency=2))
