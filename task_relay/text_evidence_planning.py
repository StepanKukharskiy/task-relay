"""New text plans preserve exploration and bind factual review to source inputs.

These are bounded planning checks, not a semantic truth classifier. Existing
saved plans retain their original contracts. Native and Safari audits remain
owned by their existing contracts.
"""
import re

INSTRUCTIONS = '''Preserve the requested level of work. An ideas or feasibility
question calls for a concise options/feasibility answer with useful concepts and
clear limits. Do not turn it into a comprehensive engineering blueprint, wiring
instructions, firmware, bill of materials or implementation phases unless asked.
For text outputs, distinguish proposals and illustrative code from verified facts.
Criteria promising technical/factual accuracy, architectural feasibility, current
prices or independently verified facts require source evidence supplied to BOTH
author and reviewer. Use selected source documents or declared outputs of a scoped
browser/computer/web.sources research task; model-written prose is not independent
evidence. If evidence is unavailable, narrow the proposed outcome honestly to
ideas with unverified limits, or report the specific missing evidence. Do not
pretend a file-only worker researched current information. The reviewer must audit
material factual claims against independent inputs, including contradictions,
and state limits. Source citations cannot establish compilation, electrical safety
or physical measurements: those require actual execution/measurement receipts.
Never use document section references as proof of factual correctness.'''

RESEARCH_INSTRUCTIONS = {
    'suggest': 'Research is optional. Keep creative ideas concise and engaging. When current projects, compatibility, specifications or prices would materially help, explain that a source-backed answer is available as a separate choice; do not turn every request into research. Without source reads, label specific unknown claims instead of putting an UNVERIFIED disclaimer over the entire answer. Do not call documented specifications theoretical just because a proposed build is untested.',
    'none': 'The user chose no new web research. Use supplied sources or give concise ideas with claim-specific unknowns. Do not propose new browser/computer/web.sources steps. If research is essential to the exact request, return needs_input explaining the conflict.',
    'sources': 'The user chose a source-backed answer. Use supplied independent documentation or propose a separate bounded research producer and reviewer before writing. Feed exact source evidence to the final author AND reviewer, and verify material factual claims. Do not substitute blanket unverified disclaimers or disconnected research for source verification. If no research route/source is available, return needs_input. This choice approves planning only; existing review/Start approves exact sites, actions and budgets. Preserve the original exploratory level of work.',
}

ADVICE_INSTRUCTIONS = '''For this default-choice request, return research_advice in
the same planning response. Judge the user's requested outcome, supplied evidence
and frozen capabilities; do not use a keyword rule or turn every request into
research. Set recommended_mode to none or sources, requirement to unnecessary,
optional or required, give a concise request-specific reason, and list the concrete
questions source checking would resolve. Pure creative work usually needs no
research (none/unnecessary, questions=[]). Exploratory ideas can recommend a quick
answer (none/optional) with an optional source-backed alternative and specific
checks. Current comparisons, fact checking, compatibility or engineering claims
may require sources to satisfy the exact request (sources/required). Supplied
independent documentation can meet that need without new web research.
The ready graph must implement the recommended approach. A sources recommendation
uses the same source-backed handoff and independent reviews as an explicit source
choice; an unavailable route returns needs_input. A none recommendation proposes
no new web research. Optional alternatives are choices for a separate draft,
not extra assignments in the recommended graph. Explain tradeoffs without making
all ideas sound unverified. Advice grants no execution authority: the user still
reviews the exact plan, sites, actions and budgets before Start.'''


def advice(value, payload):
    """Validate recorded planner judgment; never infer advice for historical jobs."""
    if payload.get('research_advice_version') != 1:
        if value is not None:
            raise ValueError('Research advice was not included in the saved planning contract.')
        return None
    if not isinstance(value, dict) or set(value) != {'recommended_mode', 'requirement', 'reason', 'questions'}:
        raise ValueError('Declare request-specific research_advice in the planning response.')
    mode, need = value['recommended_mode'], value['requirement']
    if mode not in ('none', 'sources') or need not in ('unnecessary', 'optional', 'required'):
        raise ValueError('Invalid research recommendation.')
    if not isinstance(value['reason'], str) or not 1 <= len(value['reason'].strip()) <= 800:
        raise ValueError('Explain why the recommendation fits this request.')
    questions = value['questions']
    if not isinstance(questions, list) or len(questions) > 4 or any(not isinstance(q, str) or not 1 <= len(q.strip()) <= 300 for q in questions):
        raise ValueError('List at most four concise questions research would resolve.')
    if (need == 'required' and mode != 'sources') or (need == 'unnecessary' and (mode != 'none' or questions)) or (need != 'unnecessary' and not questions):
        raise ValueError('Research requirement, recommendation and questions must agree.')
    return value


def research_mode(payload):
    return payload.get('recommended_research_mode', payload.get('research_mode')) if payload.get('research_choice_version') == 1 else None

# Deliberately narrow recognition; ambiguous requests still use the instruction
# above. Explicit deliverable requests take precedence over exploratory wording.
_EXPLORE = re.compile(r'\b(?:any ideas|what (?:can|could|do) (?:i|we) do|is it (?:possible|feasible)|could (?:i|we)|can (?:i|we) (?:make|turn))\b|(?:какие идеи|что (?:можно|могу|нам) сделать)', re.I)
_DELIVER = re.compile(r'\b(?:build|create|produce|write|implement|research|give me|make me)\b|\b(?:starter project|implementation guide|step[- ]by[- ]step|bill of materials|bom|firmware|wiring diagram)\b|(?:создай|напиши|сделай|разработай|исследуй)', re.I)
_EXPANSION = re.compile(r'\b(?:comprehensive (?:technical |engineering )?(?:guide|blueprint)|(?:technical|engineering|project) blueprint|step[- ]by[- ]step|bill[- ]of[- ]materials|bom|wiring (?:diagram|instructions)|firmware (?:implementation|development)|implementation (?:phases|pathways|roadmap))\b', re.I)
_FACTUAL = re.compile(r'\b(?:technical(?:ly)?\s+(?:accura\w*|rigorous)|factual\s+accura\w*|(?:architectural|technical|hardware|electrical)\s+feasib\w*|(?:current|realistic|verified)\s+(?:component\s+)?(?:prices|costs)|(?:verify|verified|validate|validated)\s+(?:the\s+)?(?:facts|factual claims|technical accuracy))\b', re.I)
_NEGATIVE = re.compile(r"\b(?:do not|don't|never|avoid|exclude|without|no|unverified)\b", re.I)
EXPLORATION_INSTRUCTION = 'This request is exploratory. Keep the answer concise, offer useful concepts and next choices, and label unverified implementation details. Do not add unsolicited wiring, firmware, BOM or implementation phases.'
SOURCE_INSTRUCTION = 'Separate verified source-backed facts, proposed designs and unverified details. Do not present illustrative code as built or an unmeasured interface as electrically validated.'


def promised(text, pattern):
    # Negative constraints should not become requirements. This remains a narrow
    # wording guard, not a full natural-language authorization classifier.
    for clause in re.split(r'[.\n;]', text):
        for match in pattern.finditer(clause):
            if _NEGATIVE.search(clause[:match.start()]):
                continue
            if re.match(r'\s+(?:(?:as|is|are|remains?)\s+)?(?:unverified|unsupported|uncertain)\b', clause[match.end():], re.I):
                continue
            return True
    return False


def exploration(request):
    return isinstance(request, str) and bool(_EXPLORE.search(request)) and not _DELIVER.search(request)


def criteria(task):
    return [n for n, value in enumerate(task['criteria'], 1) if promised(value, _FACTUAL)]


def bind(plan, payload):
    if payload.get('text_evidence_policy_version') != 1:
        return
    tasks = {t['id']: t for t in plan['tasks']}
    if payload.get('request_scope') == 'exploration':
        for t in tasks.values():
            if t.get('execution') or t.get('browser') or t.get('computer'):
                continue  # Bounded research may support an exploratory answer.
            text = '\n'.join([t['objective'], t['instruction'], *t['criteria'],
                              *(o['purpose'] for o in t['outputs'])])
            if promised(text.replace(EXPLORATION_INSTRUCTION, ''), _EXPANSION):
                raise ValueError('This request asks for exploration; propose concise ideas and feasibility with limits, not an unsolicited implementation blueprint.')
            if EXPLORATION_INSTRUCTION not in t['instruction']:
                t['instruction'] += '\n'+EXPLORATION_INSTRUCTION
    supplied = {s['artifact'] for s in payload.get('sources', [])
                if not s.get('request_context') and not s.get('operation_support')
                and not s['path'].startswith(('request/', 'prior-outputs/'))
                and s['path'].split('/')[-1] != 'conversation.json'}
    research = {t['id'] for t in tasks.values() if not t.get('review_of') and
                (t.get('browser') or t.get('computer') or t.get('execution', {}).get('capability') == 'web.sources')}
    mode = research_mode(payload)
    if mode == 'none' and research:
        raise ValueError('The saved research choice excludes new web research. Use supplied sources or return needs_input for the conflict.')
    for reviewer in tasks.values():
        if not reviewer.get('review_of'):
            continue
        producer = tasks[reviewer['review_of']]
        # Existing operation-specific verification owns native/binary research.
        if producer.get('execution') or producer.get('computer') or producer.get('browser'):
            continue
        if any(o.get('media_type', 'text/plain') not in ('text/plain', 'text/markdown', 'application/json') for o in producer['outputs']):
            continue
        if mode == 'sources' and not criteria(producer):
            producer['criteria'].append('Verify factual accuracy against independent sources.')
            reviewer['criteria'] = list(producer['criteria'])
        checks = criteria(producer)
        if not checks:
            continue
        author_sources = {(i.get('artifact'), i.get('from_task'), i.get('output')) for i in producer['inputs']}
        paths = []
        for i in reviewer['inputs']:
            independent = i.get('artifact') in supplied or i.get('from_task') in research
            identity = (i.get('artifact'), i.get('from_task'), i.get('output'))
            if independent and identity in author_sources and i.get('media_type', 'text/plain') in ('text/plain', 'text/markdown', 'application/json'):
                paths.append(i['path'])
        if not paths:
            raise ValueError('Text factual verification requires independent source inputs for both author and reviewer; draft sections and model-written source notes are not evidence. Add bounded research or supplied sources, or propose explicitly unverified ideas.')
        if mode == 'sources':
            upstream = {i.get('from_task') for i in producer['inputs']}
            for source in upstream & research:
                assessment = next((t['id'] for t in tasks.values() if t.get('review_of') == source), None)
                if assessment is None or assessment not in upstream:
                    raise ValueError('A source-backed author must receive the independent research review alongside its source evidence.')
        reviewer['source_verification'] = {'version': 1, 'criteria': checks, 'sources': paths,
            'candidates': [i['path'] for i in reviewer['inputs'] if i.get('from_task') == producer['id']]}
        if SOURCE_INSTRUCTION not in producer['instruction']:
            producer['instruction'] += '\n'+SOURCE_INSTRUCTION
