"""Bounded public text-source collection for registered production steps."""

import json
import http.client
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from task_relay import gemini, orchestrator_web

MAX_QUERIES = 20
MAX_DOMAINS = 8
MAX_PAGES_PER_QUERY = 2


def validate(queries, domains):
    if (not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES
            or any(not isinstance(q, str) or not 1 <= len(q.strip()) <= 250
                   or any(ord(c) < 32 for c in q) for q in queries)
            or len({q.casefold().strip() for q in queries}) != len(queries)):
        raise ValueError('Web source collection requires 1–20 distinct literal queries of at most 250 characters.')
    if (not isinstance(domains, list) or len(domains) > MAX_DOMAINS
            or any(not isinstance(d, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', d)
                   or '.' not in d or '..' in d for d in domains)
            or len(set(d.lower() for d in domains)) != len(domains)):
        raise ValueError('Use up to eight distinct public domain names without schemes, paths or wildcards.')
    return [q.strip() for q in queries], [d.lower() for d in domains]


def allowed(url, domains):
    host = urlsplit(orchestrator_web.public_url(url)).hostname
    return not domains or any(host == d or host.endswith('.' + d) for d in domains)


def collect(queries, domains, model, control, config):
    """Return fetched candidates; no result is promoted to a verified fact."""
    queries, domains = validate(queries, domains)
    if not isinstance(model, str) or not model or config.get('models', {}).get('text') != model:
        raise ValueError('The selected Gemini text model changed; no search was sent.')
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, query in enumerate(queries, 1):
        session = orchestrator_web.Session(control / f'query-{index:02d}.json', config)
        entry = {'query': query, 'status': 'unresolved', 'search_queries': [],
                 'searched_at': None, 'grounding': [], 'pages': [], 'errors': []}
        try:
            search = session.search(query)
        except gemini.ProviderError:
            # Session.search retains the submitted/uncertain receipt. Stop here;
            # neither this operation nor recovery may resubmit an uncertain call.
            raise
        except (ValueError, OSError) as exc:
            entry['errors'].append('Search: ' + str(exc))
            entries.append(entry)
            continue
        entry['search_queries'] = search['queries']
        entry['searched_at'] = search['retrieved_at']
        entry['grounding'] = [source for source in search['sources'] if allowed(source['url'], domains)]
        if not entry['grounding']:
            entry['errors'].append('No grounding source matched the selected domains.')
        for source in entry['grounding'][:MAX_PAGES_PER_QUERY]:
            try:
                page = session.fetch(source['url'], 0, orchestrator_web.MAX_CHARS,
                                     allowed_hosts=domains or None)
                if not allowed(page['url'], domains):
                    entry['errors'].append('Redirect left the selected domains: ' + page['url'])
                    continue
                entry['pages'].append({key: page[key] for key in
                    ('url', 'requested_url', 'title', 'text', 'retrieved_at', 'sha256', 'content_type',
                     'total_characters', 'next_offset')})
            except (ValueError, OSError, http.client.HTTPException) as exc:
                entry['errors'].append('Fetch ' + source['url'] + ': ' + str(exc))
        if entry['pages']:
            entry['status'] = 'source_fetched'
        elif entry['grounding']:
            entry['status'] = 'search_only'
        entries.append(entry)
    pack = {'version': 1, 'kind': 'public_source_candidates', 'provider': 'Gemini with Google Search',
            'model': model, 'domains': domains, 'created_at': time.time(), 'entries': entries,
            'interpretation': 'Search grounding and fetched pages are source candidates, not verified facts. Check the exact subject in each page.'}
    return json.dumps(pack, ensure_ascii=False, sort_keys=True), {
        'queries': len(entries), 'grounded': sum(bool(e['grounding']) for e in entries),
        'fetched': sum(bool(e['pages']) for e in entries),
        'unresolved': sum(not e['pages'] for e in entries)}
