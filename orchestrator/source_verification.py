"""Bind text factual-review evidence to exact independent input passages.

Quoted support and candidate coverage remain reviewer judgments. These checks
reject circular/forged citations; they do not establish semantic truth or certify
software builds, electrical safety or physical testing.
"""
import hashlib
import json

INSTRUCTIONS = '''The frozen source_verification contract applies to its listed
criteria. Audit every material factual claim relevant to each criterion against
the independent source inputs, including contradictory hardware variants and
unverified/current details. Evidence must contain claims with candidate_path,
claim (the whole exact candidate passage), verdict (supported, unsupported or
uncertain), reason, and supports (exact path, sha256 and literal quote from an
independent input). Candidate sections, your own review, the user request, model
memory and a generated source list cannot support a factual pass. Missing evidence
means revise/blocked; never accept. A source quote establishes only source support,
not a build or physical test. Report those limits explicitly. Use the typed report
form when supplied; otherwise JSON-encode {"claims":[...]} in check evidence.
Use short contiguous excerpts, preserving whitespace. A valid citation is not
proof of truth: judge the whole claim, source quality and contradictory evidence.'''


def validate_assignment(task):
    p = task['source_verification']
    if (not task.get('review_of') or not isinstance(p, dict) or set(p) != {'version', 'criteria', 'sources', 'candidates'}
            or type(p['version']) is not int or p['version'] != 1):
        raise ValueError('Invalid text source verification contract.')
    if (not isinstance(p['criteria'], list) or not p['criteria']
            or any(type(n) is not int or not 1 <= n <= len(task['criteria']) for n in p['criteria'])
            or len(p['criteria']) != len(set(p['criteria']))):
        raise ValueError('Invalid text source verification criteria.')
    inputs = {i['path']: i for i in task['inputs']}
    actual_candidates = {i['path'] for i in task['inputs'] if i.get('from_task') == task['review_of']}
    for key in ('sources', 'candidates'):
        paths = p[key]
        if (not isinstance(paths, list) or not paths
                or any(not isinstance(path, str) or path not in inputs for path in paths)
                or len(paths) != len(set(paths))):
            raise ValueError('Text verification requires distinct declared source and candidate paths.')
    if set(p['candidates']) != actual_candidates or set(p['sources']) & actual_candidates:
        raise ValueError('The reviewed candidate cannot be its own independent source.')
    if any(path.startswith('request/') or path.split('/')[-1] == 'conversation.json' for path in p['sources']):
        raise ValueError('Request instructions are not independent factual evidence.')


def schema():
    from task_relay.planning_contract import obj, array
    text = {'type': 'string'}
    support = obj({'path': text, 'sha256': text, 'quote': text}, ('path', 'sha256', 'quote'))
    claim = obj({'candidate_path': text, 'claim': text,
                 'verdict': {'type': 'string', 'enum': ['supported', 'unsupported', 'uncertain']},
                 'reason': text, 'supports': array(support)},
                ('candidate_path', 'claim', 'verdict', 'reason', 'supports'))
    return obj({'claims': array(claim)}, ('claims',))


def validate_report(result, frozen):
    if not frozen.get('source_verification') or result['decision'] != 'accept':
        return
    validate_assignment(frozen)
    from .runtime import safe_file
    from task_relay.planning_contract import validate
    p = frozen['source_verification']
    inputs = {i['path']: i for i in frozen['inputs']}
    texts = {}

    def read(path):
        if path not in texts:
            raw = safe_file(frozen['workspace'], path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != inputs[path].get('sha256'):
                raise ValueError('Text verification input differs from its frozen hash: ' + path)
            try:
                texts[path] = raw.decode('utf-8-sig')
            except UnicodeError:
                raise ValueError('Text verification requires UTF-8 source evidence: ' + path) from None
        return texts[path]

    for number in p['criteria']:
        try:
            data = json.loads(result['checks'][number - 1]['evidence'])
            validate(data, schema())
        except (ValueError, TypeError, KeyError, IndexError):
            raise ValueError('Factual acceptance requires structured independent source evidence for criterion ' + str(number) + '.') from None
        if not 1 <= len(data['claims']) <= 40:
            raise ValueError('Audit 1–40 material factual claims per source criterion.')
        seen = set()
        for claim in data['claims']:
            path, passage = claim['candidate_path'], claim['claim']
            if path not in p['candidates'] or not passage.strip() or len(passage) > 4000 or (path, passage) in seen:
                raise ValueError('Audit distinct complete passages from the exact candidate.')
            seen.add((path, passage))
            if passage not in read(path):
                raise ValueError('Audited claim is absent from the frozen candidate.')
            if claim['verdict'] != 'supported' or not claim['reason'].strip() or len(claim['reason']) > 4000:
                raise ValueError('Unsupported or uncertain factual claims require revise or blocked, never accept.')
            if not 1 <= len(claim['supports']) <= 8:
                raise ValueError('Each factual pass requires independent source passages.')
            for support in claim['supports']:
                source, quote = support['path'], support['quote']
                if source not in p['sources']:
                    raise ValueError('Candidate/request/generated review cannot substantiate factual verification.')
                if support['sha256'] != inputs[source].get('sha256'):
                    raise ValueError('Source citation differs from the frozen source version.')
                if not quote.strip() or len(quote) > 2000 or quote not in read(source):
                    raise ValueError('Support quote is absent from the exact independent source.')
