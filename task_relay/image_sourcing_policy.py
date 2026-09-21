"""Shared, read-only source selection for new plans; never changes approved work."""

INSTRUCTIONS = '''Relay chooses where to find reference images; the user need only
describe the subjects and intended result. Do not ask the user to name a search
website, or require Google Images wording to use browser discovery. Consult
image_sourcing (in snapshot.capabilities for routing) for the available default.
Its preferred_operation is a default for unspecified sources, not authorization
to override an explicit website, licence requirement, executor, or saved stage.
Use images.fetch with a browser.use discovery worker when it is the available
default; use images.collect for Commons-only requests, documented reuse licences,
or when browser discovery is unavailable. If the requested restriction cannot be
met, explain the actual missing capability rather than silently dropping it.
For unrestricted browser discovery choose a suitable primary search site and one
alternate from search_sites. Include their exact origins in the proposed browser
contract BEFORE execution, and give the worker this recovery instruction: when
results are irrelevant, empty or only thumbnails, refine the subject query, then
try the approved alternate within the same request/action budget. Retain successful
exports and record remaining gaps. Do not weaken subject identity. Never bypass
challenges; an unrestricted task may use its already approved alternate, while an
explicitly required site's challenge needs manual verification. Do not switch AI
providers or add origins/tools during execution. An exhausted or uncertain task
does not gain retries. A failed Commons-only approved stage needs a new scoped
plan to use browser discovery; this policy does not mutate saved plans.
Pass original observed photos in reviewed ZIP bundles with exact sources and
unknown rights disclosed. Never replace missing reference photos with generated
images. Honor permission to omit missing images while preserving subject text.
'''


def describe(operations, workers, browser):
    """Only advertise routes present in this catalog (possibly a frozen scope)."""
    available = {x['id'] for x in operations if x.get('available') is True}
    browser_workers = [x['id'] for x in workers
                       if x.get('available', True) and 'browser.use' in x.get('capabilities', [])]
    ready = bool(browser.get('enabled') and browser.get('available') and browser_workers)
    methods = []
    if 'images.fetch' in available and ready:
        methods.append('images.fetch')
    if 'images.collect' in available:
        methods.append('images.collect')
    sites = [
        dict(id='google', name='Google Images', url='https://www.google.com/search?tbm=isch',
             origins=['https://www.google.com', 'https://consent.google.com']),
        dict(id='bing', name='Bing Images', url='https://www.bing.com/images/search',
             origins=['https://www.bing.com']),
    ] if 'images.fetch' in methods else []
    return dict(version=1, preferred_operation=next(iter(methods), None),
                available_operations=methods, browser_executors=browser_workers if ready else [],
                search_sites=sites, selection='Default only; explicit user constraints and frozen scope take precedence.',
                limitation='Availability is local configuration, not proof of website access or photo coverage.')
