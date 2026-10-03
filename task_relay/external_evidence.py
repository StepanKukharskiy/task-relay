"""Keep external source checks within the capabilities frozen for a stage."""

import re
from pathlib import PurePosixPath


_ARTICLE = re.compile(r"\b(?:артикул\w*|part\s*(?:number|no\.?|#)|sku)\b", re.I)
_CONFIRM = re.compile(r"(?:подтвержд\w*|проверк\w*|верифицир\w*|verif\w*|confirm\w*)", re.I)
_SOURCE = re.compile(r"(?:источник\w*|каталог\w*|производител\w*|source\w*|catalog\w*|manufacturer|oem)", re.I)
_ONLINE = re.compile(r"(?:интернет\w*|онлайн|открыт\w* доступ\w*|public\s+(?:web|source)|online|on\s+the\s+web)", re.I)
_CATALOG = re.compile(r"(?:каталог\w*|catalog\w*|oem|service\s+manual|схем\w*)", re.I)
_RESEARCH = re.compile(r"\b(?:research|search|look\s*up)\b|(?:поиск\w*|исследован\w*)", re.I)
_PART_IDENTIFIERS = re.compile(r"\b(?:articles?|part[\s-]*(?:numbers?|no\.?|#)|sku)\b|артикул\w*", re.I)
_URL = re.compile(r"\burls?\b|источник\w*|ссылк\w*", re.I)


def required(request):
    """Recognize explicit source verification, not ordinary source-grounded writing."""
    if not isinstance(request, str):
        return False
    words = " ".join(request.split())
    return bool((_ARTICLE.search(words) and _CONFIRM.search(words) and _SOURCE.search(words))
                or (_ONLINE.search(words) and _CONFIRM.search(words) and _SOURCE.search(words))
                or (_CATALOG.search(words) and _CONFIRM.search(words))
                or (_RESEARCH.search(words) and _CATALOG.search(words)
                    and _PART_IDENTIFIERS.search(words) and _URL.search(words)))


def supplied(payload):
    """An explicitly selected catalog/research source can replace a live lookup."""
    options = payload.get('options', {})
    if options.get('research_ids') or options.get('reference_pack_id'):
        return True
    for source in payload.get('sources', []):
        path = source.get('path', '')
        if source.get('request_context') or PurePosixPath(path).name == 'conversation.json':
            continue
        if _CATALOG.search(PurePosixPath(path).name):
            return True
    return False


def research_available(payload):
    options = payload.get('options', {})
    return ('web.sources' in options.get('step_capabilities', [])
            or ('web.sources' in options.get('optional_research_capabilities', [])
                and (payload.get('research_mode')=='sources' or payload.get('research_advice_version')==1))
            or any(set(item.get('capabilities', [])) & {'browser.use','computer.use'}
                   for item in options.get('worker_catalog', [])))


def needed(payload):
    return required(payload.get('original_request')) and not supplied(payload)


def validate_plan(plan, payload):
    """A file/shell-only plan cannot promise article-specific external evidence."""
    if not needed(payload):
        return
    tasks = {task['id']: task for task in plan['tasks']}
    research = {task['id'] for task in plan['tasks']
                if not task.get('review_of') and task.get('browser')
                and 'browser.use' in task.get('worker', {}).get('requires', [])}
    research.update(task['id'] for task in plan['tasks'] if not task.get('review_of')
                    and task.get('computer') and 'computer.use' in task.get('worker',{}).get('requires',[]))
    research.update(task['id'] for task in plan['tasks']
                    if not task.get('review_of')
                    and task.get('execution', {}).get('capability') == 'web.sources')
    if not research:
        raise ValueError('External article/source verification requires a browser.use, computer.use or web.sources research step, or selected catalog evidence; file and shell workers cannot establish it.')

    def research_input(task_id, seen=None):
        if task_id in research:
            return True
        seen = set() if seen is None else seen
        if task_id in seen:
            return False
        seen.add(task_id)
        return any(research_input(item['from_task'], seen.copy())
                   for item in tasks[task_id]['inputs'] if 'from_task' in item)

    consumed_by_producer = {item['from_task']
                            for task in plan['tasks'] if not task.get('review_of')
                            for item in task['inputs'] if 'from_task' in item}
    reviewers = {task['review_of']: task for task in plan['tasks']
                 if task.get('review_of')}
    for task in plan['tasks']:
        if task.get('review_of') or task['id'] in research:
            continue
        if task['id'] in consumed_by_producer:
            continue  # Source preparation can precede the research lookup.
        if not research_input(task['id']):
            raise ValueError('The file producer must consume a declared output from the research step; a dependency or instruction alone is not evidence.')
        upstream = {item['from_task'] for item in task['inputs'] if 'from_task' in item}
        for source_id in upstream & research:
            reviewer = reviewers.get(source_id)
            if reviewer and reviewer['id'] not in upstream:
                raise ValueError('The file producer must consume the independent research review as a declared input alongside the source pack.')
