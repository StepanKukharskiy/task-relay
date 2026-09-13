"""Explicit browser requests reuse the conversation and reviewed production queues."""
CONTROLS={'','connect','chat','status','cancel'}


def executor(text):
    words=text.split(None,2)
    provider=words[1].lower() if len(words)>1 and words[1].lower() in ('gemini','openai','qwen') else 'gemini'
    return provider+'-browser'


def instructions(text):
    from orchestrator.browser_contract import WEBSITE_TASK_INSTRUCTIONS
    return INSTRUCTIONS.replace('gemini-browser',executor(text))+'\n'+WEBSITE_TASK_INSTRUCTIONS


def is_request(text):
    words=text.split(None,1)
    return bool(words and words[0].split('@')[0].lower()=='/browser' and
                not (len(words)>1 and words[1].split()[:1]==['sites']) and
                len(words)>1 and words[1].strip().lower() not in CONTROLS)


INSTRUCTIONS='''The current message explicitly requests /browser execution.
Preserve its exact text and use plan_production with executor="gemini-browser"
for a new bounded website task, template="custom", project=null unless requested,
reference_pack_id=null and empty source selections unless sources are needed.
Do not substitute a normal web-search answer, a file-only worker, Codex delegation
or Perplexity sign-in. Public information searches do not require a signed-in
profile; the planner may use a dedicated public-search profile and select relevant
public websites. The browser worker must inspect actual pages and cite its results.
For signed-in account work, consult snapshot.capabilities.browser_account_sites.
Use the accounts profile only after the exact sites are confirmed_by_user. If not,
ask for /browser sites add and /browser sites login for the missing site; do not
replace an account request with anonymous browsing. Passwords and verification
codes belong in the browser during manual setup, never in an ordinary chat message.
Use applicable conversation preferences. For information-only research, state
reasonable defaults rather than repeatedly asking for nonessential preferences.
Dates must include a year, based on the current request/context and host clock;
make any inferred year explicit. Flight information is search-only: no booking,
payment, account changes or contact with airlines. Distinguish observed fares from
route/schedule information and report inaccessible pricing as unavailable.
Planning returns the existing exact-scope Start card. Clarifications and capability
blockers may use action=null. Never claim the browser has run before its receipts.
'''


def validate(action,text=''):
    if action is not None and (not isinstance(action,dict) or action.get('kind')!='plan_production' or action.get('executor')!=executor(text)):
        raise ValueError('This /browser request requires a browser production plan; no alternative executor was dispatched.')


def refresh_connection(text=''):
    """Refresh stale model metadata only; no content generation or browser launch."""
    from orchestrator import executors
    selected=executor(text);provider=selected.removesuffix('-browser')
    _,backend=executors.configured() if provider=='gemini' else executors.configured(provider)
    backend={**backend,'type':selected}
    try:executors.available(backend)
    except ValueError:
        executors.probe() if provider=='gemini' else executors.probe(provider)
        executors.available(backend)
