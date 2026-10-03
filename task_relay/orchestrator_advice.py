"""Direct conversation recommendations and disclosure from recorded web reads."""
import hashlib
import json
import re
from pathlib import Path

from . import text_evidence_planning as policy

# The wire budget includes JSON escaping and all advisory fields. Text and action
# budgets are enforced separately; a larger display reply grants no new authority.
MAX_RESPONSE_CHARACTERS = 1_000_000
MAX_DIRECT_ANSWER_CHARACTERS = 32_000
MAX_ACTION_ANSWER_CHARACTERS = 6_000
MAX_ACTION_DATA_CHARACTERS = 16_000

INSTRUCTIONS = '''For this conversation return research_advice alongside answer and
action, using {recommended_mode: none or sources, requirement: unnecessary or
optional or required, reason: a concise request-specific reason, questions: up to
four concrete questions source checking would resolve}. Judge the requested outcome,
not keywords. Pure creative work, clock/status questions and supplied project records
usually need no new web research (none/unnecessary, questions=[]). For exploration,
give a short, engaging answer and recommend quick ideas with optional source checks,
or explain why source-backed work would help. Do not turn an ideas question into
wiring instructions, firmware, a parts list or an engineering blueprint. Keep an
exploratory direct answer within 2200 characters, before advice and source disclosure.
State implementation unknowns beside the specific claim; avoid blanket UNVERIFIED
labels and claims that a proposed build is proven feasible. Do not assert current
product capabilities, prices or compatibility from memory as verified facts.
For optional research, offer it as a next choice instead of silently doing extra
paid searches. If the user explicitly requests verification/research, use the
available bounded web tools or propose a separately reviewed stage. When sources
are required but not read/supplied, explain the evidence gap rather than presenting
a final factual guide. Source URLs must refer to observed tool results; retrieval
does not prove correctness. Relay appends saved advice and actual web-read disclosure.
This advice grants no execution authority. For a new plan_production, include
research_mode=suggest (default recommendation), none (explicit no new research) or
sources (explicit source-backed choice), preserving the exact user request. Do not
turn a question into permission for workers, hardware modifications or a paid job.
Use the runtime-defined relay_respond tool to return answer/recommendation data.
Relay owns its schema, available tools, budgets and validation; do not write or
revise a contract. Its action_json is null for a direct answer, or a serialized
action DATA object using the existing allowed action fields. Return the final tool
alone, without combining it with reads. No extra provider turn follows this tool.
Plain JSON answers remain compatible but must use the same fields and enums.
In particular recommended_mode is ONLY none or sources; optional belongs ONLY in
requirement. For example, a quick answer with optional checks uses
{"recommended_mode":"none","requirement":"optional","reason":"The ideas can
come first; documentation could establish compatibility.","questions":["Which
documented interfaces are compatible?"]}.
Return work_status as respond, needs_input or blocked. Use needs_input/blocked
with action_json=null when required inputs or capabilities remain unresolved;
retain the frozen outcomes and explain the specific gap, never mark files done.
Also return next_options: an array of zero to three concrete next choices. When
exploration has useful alternatives, offer distinct outcomes Relay can help produce
now, such as checking existing projects, making a software prototype, or preparing
a design, chosen from the ENTIRE offered option_tools catalog. Do not limit options
to research, enumerate irrelevant tools, or merely describe things the user could do.
Each option has title (short), outcome (specific deliverable and why useful), tools
(one to four exact option_tools IDs), and request (a self-contained follow-up request
to prepare that outcome). State scope and unknowns; hardware testing is not a software
prototype. Options are proposals, not started jobs. For action != null return [].
Name options for the result the user receives, not internal activities such as
Draft Technical Architecture Spec or Research Hardware Mods. Prefer outcomes such
as Find the easiest documented approach or Build a software prototype. Describe
deliverables and meaningful validation in outcome/request, using only offered
capabilities. Separate compilation/protocol tests from physical-device tests.
Do not promise proven/verified results before checking evidence; a research option
can aim to establish a documented approach and report unresolved gaps.
Keep the answer natural: Relay presents options and source status separately.
Do not narrate routing, research requirement enums, provenance machinery or repeat
the option menu inside answer. For exploratory requests prioritize a few useful
ideas over current product lists, exact specifications and detailed architectures.
Check terms against the actual device; distinguish chips from boards and added
modules, and normal authoring features from engine/plugin extensions. If these
details have not been sourced, leave them as questions for the chosen job.
Return claim_sources: zero to eight {statement, source_urls} DATA entries for
material factual claims. statement must be an exact excerpt from answer and
source_urls must be URLs observed in this request's successful web reads. Use []
when no source supports a claim. Relay derives evidence states from read receipts;
never supply a state, verdict or contract. A read page establishes retrieval and a
candidate citation, not semantic verification, implementation success or testing.
For straightforward requests without useful alternatives return []. Existing action
routes still carry authorized work; offering options must not replace doing an
already explicit request. The transport does not determine advice or tool selection.
For explicit source checks, read primary pages using web_fetch, cite them beside the
claims and distinguish confirmed facts, inference and unresolved questions. Search
synthesis alone cannot establish verified pinouts, compatibility or implementations.
Use research_advice.questions for factual uncertainties, not board/tool preferences.
Respect entry_context.research_mode; none excludes new web tools, sources requests
source checking. entry_context attachments are exact frozen inputs, not proof of
reading; plan with them or read available project files before claiming contents.'''

INSTRUCTIONS += (f'\nExplicit long-form writing may use up to {MAX_DIRECT_ANSWER_CHARACTERS} '
                 'characters in a direct answer. With an execution action, keep the '
                 f'answer within {MAX_ACTION_ANSWER_CHARACTERS} characters. These limits '
                 'include code snippets; never silently omit requested articles to fit. '
                 'Requests for saved/downloadable files use the available production '
                 'planning route; inline prose alone is not a saved file receipt.')


def option_tools(payload):
    """Advertise captured availability; choosing a route still rechecks its grants."""
    catalog = payload.get('snapshot', {}).get('capabilities', {})
    result = []
    for group in ('operations', 'graph_operations', 'graph_executors'):
        for item in catalog.get(group, []):
            readable_project = (group == 'operations' and item.get('executor') == 'relay.files'
                                and payload.get('snapshot', {}).get('project_roadmaps', {}).get('available_projects'))
            if item.get('available') is not True and not readable_project:
                continue
            if group == 'operations' and item.get('executor') not in ('relay.web', 'relay.files'):
                continue
            result.append({'id': group + ':' + item['id'],
                           **{k:item[k] for k in ('tools', 'capabilities', 'description', 'permissions', 'limits', 'grant_boundary', 'requires_registered_inputs') if k in item}})
    if payload.get('entry_context', {}).get('research_mode') == 'none':
        result = [item for item in result if item['id'] not in
                  ('operations:web_fetch', 'operations:web_search', 'graph_operations:web.sources')]
    return result


def options(value, tools):
    if not isinstance(value, list) or len(value) > 3:
        raise ValueError('Offer at most three concrete next options.')
    known = {tool['id'] for tool in tools}
    for item in value:
        if not isinstance(item, dict) or set(item) != {'title', 'outcome', 'tools', 'request'}:
            raise ValueError('Each next option needs a title, outcome, tools and follow-up request.')
        for key, limit in (('title',100), ('outcome',500), ('request',1500)):
            if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > limit:
                raise ValueError('A next option contains invalid text.')
        if (not isinstance(item['tools'], list) or not 1 <= len(item['tools']) <= 4
                or any(not isinstance(t,str) or t not in known for t in item['tools'])
                or len(set(item['tools'])) != len(item['tools'])):
            raise ValueError('A next option names a tool unavailable in the captured catalog.')
    return value


def legacy_render_options(value):
    if not value:
        return ''
    return '\n\nNext options Relay can help with:\n' + '\n'.join(
        f'{i}. {item["title"]} — {item["outcome"]}' for i,item in enumerate(value,1)) + '\nChoose an option to continue; none has started.'


def render_options(value):
    if not value:
        return ''
    return '\n\nWant to take this further?\n' + '\n'.join(
        f'{i}. {item["title"]} — {item["outcome"]}' for i,item in enumerate(value,1)) + '\nNothing starts until you approve a plan.'


def response_definition(request, tools):
    """Compile the response contract from runtime rules and captured tool IDs."""
    ids = [item['id'] for item in tools]
    def string(limit):
        return {'type':'string', 'minLength':1, 'maxLength':limit}
    option = {'type':'object', 'additionalProperties':False,
              'properties':{'title':string(100), 'outcome':string(500), 'request':string(1500),
                            'tools':{'type':'array', 'minItems':1, 'maxItems':4,
                                     'items':{'type':'string', **({'enum':ids} if ids else {})}}},
              'required':['title','outcome','request','tools']}
    advice = {'type':'object','additionalProperties':False,
              'properties':{'recommended_mode':{'type':'string','enum':['none','sources']},
                            'requirement':{'type':'string','enum':['unnecessary','optional','required']},
                            'reason':string(800),
                            'questions':{'type':'array','maxItems':4,'items':string(300)}},
              'required':['recommended_mode','requirement','reason','questions']}
    return {'name':'relay_respond', 'description':'Finish with response data for the runtime-owned v1 contract. This records a response, executes no action and makes no additional provider request.',
            'parameters':{'type':'object','additionalProperties':False,
                          'properties':{'answer':{**string(2200 if policy.exploration(request) else MAX_DIRECT_ANSWER_CHARACTERS),
                                                  'description':f'Display text. With a non-null action_json, at most {MAX_ACTION_ANSWER_CHARACTERS} characters.'},
                                        'work_status':{'type':'string','enum':['respond','needs_input','blocked']},
                                        'action_json':{'type':['string','null'],'maxLength':MAX_ACTION_DATA_CHARACTERS,
                                                       'description':'Null for a direct answer; otherwise JSON-serialized action data. Relay validates its action kind, fields, scope and authority separately.'},
                                        'research_advice':advice,
                                        'claim_sources':{'type':'array','maxItems':8,'items':{
                                            'type':'object','additionalProperties':False,
                                            'properties':{'statement':string(500),'source_urls':{
                                                'type':'array','maxItems':4,'items':string(2000)}},
                                            'required':['statement','source_urls']}},
                                        'next_options':{'type':'array','maxItems':3 if ids else 0,'items':option}},
                          'required':['answer','action_json','research_advice','next_options','claim_sources','work_status']}}


def source_summary(advice, evidence):
    """Retrieval status is runtime data, never a model's factual verdict."""
    pages = sum(s['kind'] == 'page' for s in evidence['sources'])
    searches = sum(s['kind'] == 'search_result' for s in evidence['sources'])
    state = 'incomplete' if evidence.get('partial') else 'pages_read' if pages else 'search_only' if searches else 'not_checked'
    label = {'incomplete':'Sources: incomplete', 'pages_read':f'Sources: {pages} page'+('s' if pages != 1 else '')+' read',
             'search_only':'Sources: search references only', 'not_checked':'Sources: not checked yet'}[state]
    return {'state':state,'label':label,'pages':pages,'search_references':searches,
            'visible':bool(evidence['sources'] or evidence.get('partial') or advice and advice.get('requirement') != 'unnecessary')}


def claim_evidence(value, answer, evidence):
    """Project bounded claim/source data; retrieval alone never means verified."""
    result = []
    answer = answer if isinstance(answer,str) else ''
    if not isinstance(value,list) or len(value) > 8:
        return result
    observed = {s['url']:s['kind'] for s in evidence['sources']}
    for item in value:
        if (not isinstance(item,dict) or set(item) != {'statement','source_urls'}
                or not isinstance(item['statement'],str) or not item['statement'].strip() or len(item['statement']) > 500
                or not isinstance(item['source_urls'],list) or len(item['source_urls']) > 4
                or any(not isinstance(url,str) or len(url) > 2000 for url in item['source_urls'])):
            continue
        urls = list(dict.fromkeys(item['source_urls']))
        matched = item['statement'] in answer
        known = [url for url in urls if url in observed]
        state = ('unresolved' if not matched or len(known) != len(urls) else
                 'generated' if not urls else 'page_linked' if all(observed[url] == 'page' for url in urls) else 'search_reference')
        result.append({'statement':item['statement'],'state':state,'source_urls':known,'matches_answer':matched})
    return result


def presentation_advice(value, *, strict=False):
    """Advisory data cannot invalidate or authorize an otherwise valid direct answer."""
    try:
        return policy.advice(value, {'research_advice_version':1}), []
    except (ValueError, TypeError) as exc:
        if strict:
            raise
        issue = str(exc)
    # Keep individually valid explanatory data, without inventing a recommended
    # mode. The exact invalid wire value remains in the saved response.
    if isinstance(value, dict) and set(value) == {'recommended_mode','requirement','reason','questions'}:
        candidate = {**value,'recommended_mode':'sources' if value.get('requirement') == 'required' else 'none'}
        try:
            policy.advice(candidate, {'research_advice_version':1})
            return {key:value[key] for key in ('requirement','reason','questions')}, [issue]
        except (ValueError, TypeError):
            pass
    return None, [issue]


class AdviceError(ValueError):
    def __init__(self, raw, message):
        self.raw = raw
        super().__init__(message)


def validate(raw, request, tools=None, evidence=None, research_mode='suggest'):
    """Validate runtime scope; non-authorizing advisory defects do not trigger replay."""
    from .orchestrator_chat import response_json
    try:
        value = response_json(raw)
        if not isinstance(value, dict):
            raise ValueError('Declare the conversation response as an object.')
        advice, _ = presentation_advice(value.get('research_advice'), strict=value.get('action') is not None or research_mode == 'sources')
        if research_mode == 'sources' and (value['research_advice']['recommended_mode'] != 'sources'
                                           or value['research_advice']['requirement'] != 'required'):
            raise ValueError('The response must honor the explicit source-backed choice.')
        if tools is not None:
            options(value.get('next_options'), tools)
            if value.get('action') is not None and value['next_options']:
                raise ValueError('Executed actions cannot also advertise unselected next options.')
        declared_need = (value.get('research_advice') or {}).get('requirement') if isinstance(value.get('research_advice'),dict) else None
        if (evidence is not None and value.get('action') is None
                and (research_mode == 'sources' or declared_need == 'required' or evidence['sources'])
                and not any(s['kind'] == 'page' for s in evidence['sources'])
                and re.search(r'\bverif(?:ied|ication)\b|\bconfirmed\b|\bproduction-tested\b', value.get('answer',''), re.I)):
            raise ValueError('The source check claimed verification without recorded page reads. Search results alone are insufficient; no verified guide was delivered.')
        if value.get('action') is None and policy.exploration(request):
            answer = value.get('answer')
            if isinstance(answer, str) and policy.promised(answer, policy._EXPANSION):
                raise ValueError('An exploratory direct answer must stay concise and avoid an unsolicited implementation blueprint.')
    except (ValueError, TypeError) as exc:
        raise AdviceError(raw, str(exc)) from None
    return raw


def disclosure(root, ident):
    """Read this request's successful tool results, not model-authored citations."""
    stem = hashlib.sha256(str(ident).encode()).hexdigest()
    sources = {}
    titles = {}
    partial = False
    from .orchestrator_web import public_url
    for suffix in ('', '-source-correction', '-workflow-correction'):
        path = Path(root) / 'orchestrator-reads' / (stem + suffix + '.json')
        if not path.exists():
            continue
        try:
            if path.is_symlink() or path.stat().st_size > 20_000_000:
                raise ValueError('Unavailable receipt.')
            journal = json.loads(path.read_text())
            if not isinstance(journal, list):
                raise ValueError('Invalid receipt.')
            for turn in journal:
                for read in turn.get('reads', []):
                    name = read['call']['name']
                    if name not in ('web_fetch', 'web_search'):
                        continue
                    result = read['result']
                    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
                    if read.get('result_sha256') != digest:
                        partial = True
                        continue
                    if result.get('ok') is not True:
                        continue
                    if name == 'web_fetch' and isinstance(result.get('text'), str) and result['text'].strip():
                        sources[public_url(result['url'])] = 'page'
                    elif name == 'web_search':
                        for item in result.get('sources', []):
                            url = public_url(item['url'])
                            sources.setdefault(url, 'search_result')
                            if isinstance(item.get('title'), str):
                                titles[url] = ' '.join(item['title'].split())[:200]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            partial = True
    return {'sources': [{'url': url, 'kind': kind, **({'title':titles[url]} if titles.get(url) else {})}
                        for url, kind in sources.items()], 'partial': partial,
            'report_available': (Path(root) / 'orchestrator-reads' / stem / 'web-report.html').is_file()}


def legacy_render(advice, evidence):
    """Keep conversational advice concise; never imply an unexecuted research step ran."""
    relevant = advice and advice['requirement'] != 'unnecessary'
    lines = []
    if relevant:
        lines += ['']
        if advice.get('recommended_mode') in ('none', 'sources'):
            lines += ['Recommended approach: ' + ('source-backed answer' if advice['recommended_mode'] == 'sources' else 'quick ideas') + '.']
        lines += [advice['reason'], 'Research is ' + advice['requirement'] + ' for this request.',
                  'Questions for source checking:']
        lines += ['• ' + question for question in advice['questions']]
        if advice['requirement'] == 'optional':
            lines.append('You can ask for a source-backed check or keep this at the ideas stage.')
    for kind, label in (('page', 'Pages read:'), ('search_result', 'Search references (page reads not recorded):')):
        items = [s for s in evidence['sources'] if s['kind'] == kind]
        urls = [s['url'] for s in items]
        count = 0
        if urls:
            lines += ['', label]
            for item in items[:10 if kind == 'page' else 3]:
                url = item['url']
                shown = ((item.get('title') or 'Search reference') + ' (search redirect; page not read)'
                         if '/grounding-api-redirect/' in url else url)
                if len('\n'.join(lines)) + len(shown) > 4500:
                    break
                lines.append(shown)
                count += 1
        if len(urls) > count:
            lines.append('Additional recorded sources are omitted from this message.')
    if evidence.get('report_available'):
        lines.append('Source links and search evidence are in the attached search document.')
    if relevant and not evidence['sources']:
        lines += ['', 'No successful web lookup is recorded for this reply.']
    if evidence['partial']:
        lines += ['', 'Some source receipts are unavailable or changed; this disclosure is incomplete.']
    return '\n'.join(lines)


def render(advice, evidence):
    """Keep provenance compact in channel replies; full data stays in receipts."""
    summary = source_summary(advice,evidence)
    if not summary['visible']:
        return ''
    lines = ['','',summary['label']]
    for item in evidence['sources'][:3]:
        shown = ((item.get('title') or 'Search reference') + ' (search reference)'
                 if '/grounding-api-redirect/' in item['url'] else item['url'])
        if len('\n'.join(lines)) + len(shown) <= 2000:
            lines.append(shown)
    if evidence.get('report_available'):
        lines.append('Source links: attached search document.')
    elif len(evidence['sources']) > 3 or any(len(s['url']) > 2000 for s in evidence['sources']):
        lines.append('More source details are saved in Relay.')
    return '\n'.join(lines)
