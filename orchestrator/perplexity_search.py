"""Canvas operation over the existing managed Perplexity browser and journal.

The node runtime owns dispatch. No messenger queue, alternate browser profile,
API provider, automatic retry or semantic source approval is introduced here.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .workers import atomic
from .runtime_outcomes import UncertainOperation
from task_relay import browser_jobs, managed_browser, perplexity_browser
from task_relay.relay_paths import PATHS

PARAMETERS = dict(type='object', properties=dict(query=dict(type='string',minLength=1,maxLength=12000)),
                  required=['query'],additionalProperties=False)
OUTPUTS = {'outputs/answer.md':'text/markdown','outputs/sources.json':'application/json'}


def setup():
    value=managed_browser.status(PATHS)
    return dict(**value,session='not_checked',mode='Search',
                limitation='Saved profile configuration is not proof of sign-in. The node checks the account and ordinary Search controls before submitting.')


def available(assignment, spec):
    import importlib.util
    state=setup()
    if state['error']:raise ValueError(state['error'])
    if not state['enabled']:raise ValueError('Enable browser use in this node’s inspector. No Perplexity search was submitted.')
    if state['manual_sign_in']:raise ValueError('Finish sign-in in Chrome, then choose Done signing in in this node’s inspector.')
    if importlib.util.find_spec('playwright') is None:raise ValueError('The installed Relay runtime needs its browser component.')


def describe(entry, context):
    state=setup()
    entry.update(available=state['available'] and state['enabled'] and not state['manual_sign_in'] and not state['error'],
                 availability_evidence=state,permissions='One ordinary Search in the saved Perplexity browser account. No paid API or automatic resubmission.')


def execute(ctx):
    from .operation_execution import Result
    query=ctx.frozen['execution']['parameters']['query']
    receipt=ctx.frozen['assignment_id']
    control=ctx.control
    control.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(control/'browser-journal.sqlite',isolation_level=None)) as db:
        journal=browser_jobs.Journal(db)
        job=journal.prepare(receipt,query)
        # A prior submission or completion must never be a new Search.
        if job['status'] not in ('prepared','blocked'):
            raise UncertainOperation('Saved browser submission exists; inspect its original receipt. No resubmission.')
        try:
            available(ctx.frozen,ctx.spec)
            with perplexity_browser.profile_lock(PATHS.data), managed_browser.page(PATHS.data) as page:
                driver=perplexity_browser.PerplexityPage(page)
                job=browser_jobs.execute(journal,receipt,driver,timeout=min(120,max(1,ctx.frozen['limits']['seconds']-80)))
                atomic(control/'browser-result.json',job)
                if job['status']=='blocked':raise ValueError(job['error'])
                if job['status']!='completed':raise UncertainOperation(job['error'] or 'Search outcome is uncertain')
                # The journal has already committed the matching answer. Links
                # enrich that answer; failure here must not discard it or resend.
                # Keep the driver's strict binding: a drifting page supplies no
                # links, rather than attaching unrelated links to saved text.
                try:
                    sources=driver.sources(job)
                except Exception as exc:
                    sources=dict(sources=[],observed_links=None,inspected_links=None,truncated=None,
                                 source_collection=dict(status='unavailable',error=str(exc)[:2000],
                                                        error_type=type(exc).__name__))
                else:
                    sources=dict(**sources,source_collection=dict(status='completed'))
                atomic(control/'browser-sources.json',sources)
        except Exception as exc:
            job=journal.get(receipt)
            pending=job['status'] in ('submitting','uncertain')
            details=dict(outcome='uncertain' if pending else 'failed' if job['status']=='completed' else 'rejected',
                         effect='uncertain' if pending else 'confirmed' if job['status']=='completed' else 'none',
                         execution=ctx.frozen['execution'],reason=str(exc),usage=None,browser_receipt=receipt,
                         conversation_url=job['url'])
            atomic(control/'operation.json',details)
            if pending:raise UncertainOperation(str(exc)) from exc
            raise
    # The existing adapter retains the full main-region answer-page text. Do not
    # silently invent an answer-only DOM boundary or claim links were verified.
    source_document=dict(schema_version=1,provider='perplexity',mode='Search',query=query,
        conversation_url=job['url'],transcript_sha256=hashlib.sha256(job['result'].encode()).hexdigest(),
        **sources,usage=None,limitations=[
            'Any listed links were observed on the completed answer page; their contents and support for individual claims were not independently verified.',
            'The answer output retains captured page text, which can include interface text.'])
    source_warning=''
    if sources['source_collection']['status']=='unavailable':
        limitation='Source-link collection failed; the completed answer is retained. An empty source list does not mean the answer had no sources. No search was resubmitted.'
        source_document['limitations'].append(limitation)
        source_warning='> '+limitation+'\n\n'
    answer='# Perplexity Search\n\nConversation: '+job['url']+'\n\n'+source_warning+'## Captured answer page\n\n'+job['result']+'\n'
    content={'outputs/answer.md':answer.encode(), 'outputs/sources.json':(json.dumps(source_document,ensure_ascii=False,indent=2)+'\n').encode()}
    if sum(map(len,content.values()))>ctx.frozen['limits']['output_bytes']:raise ValueError('Perplexity outputs exceed the declared byte limit; saved browser receipt retained.')
    hashes={}
    for path,raw in content.items():
        target=ctx.workspace/path;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
        hashes[path]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    details=dict(outcome='completed',execution=ctx.frozen['execution'],usage=None,upstream_id=job['url'],
                 validation=dict(outputs=hashes,browser_receipt=receipt,source_count=len(sources['sources']),
                                 source_collection=sources['source_collection'],acceptance=False))
    atomic(control/'operation.json',details)
    summary='Captured Perplexity answer page; source links unavailable.' if source_warning else 'Captured Perplexity answer page and observed source links.'
    atomic(ctx.workspace/'.relay/result.json',dict(assignment_id=receipt,summary=summary,
        decision='delivered',instruction='',checks=[dict(criterion=1,passed=True,evidence=json.dumps(details['validation']))]))
    return Result(receipt=details)


def inspect(control, result, details):
    # A killed child after Search submission is not a harmless local failure.
    path=control/'browser-journal.sqlite'
    if not path.exists():return
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT status FROM browser_jobs').fetchall()
    if any(r[0] in ('submitting','uncertain') for r in row):
        result.update(status='uncertain',external_outcome='unknown',reason='Perplexity submission has no confirmed answer; no automatic resubmission.')


def register(registry, adapters):
    from .operation_adapters import Adapter
    registry['perplexity.search']=dict(version=1,kind='procedure',input_types=[],min_inputs=0,max_inputs=0,input_bytes=0,
        output_type=None,outputs=OUTPUTS,output_bytes=2000000,seconds=600,external_requests=1,
        parameters={'query':'Exact research question submitted to ordinary Perplexity Search.'},
        resources=['managed-perplexity-browser'],
        criteria=['Retain the matching completed Search answer page. Attach exactly bound source links when capture succeeds; otherwise disclose source collection failure without discarding the answer or claiming source verification.'],
        permissions='One ordinary Perplexity Search in the existing managed Chrome account. Account allowances apply; no API key or paid API.',
        cancellation='Retain submission intent and uncertain outcomes; never automatically resubmit.',
        description='Research with ordinary Perplexity Search through the saved Chrome account; outputs answer page text and observed source URLs. A completed answer survives source-capture failure with an explicit unavailable-source disclosure. Session readiness is checked before submission, not inferred from setup.',
        support_modules=['task_relay.browser_jobs','task_relay.managed_browser','task_relay.perplexity_browser','task_relay.host_managed_chrome','task_relay.host_browser_accounts'],
        node_ui=dict(title='Research with Perplexity',category='Web & research',connection='managed_browser',
                     inputs={'query':'Research question'},outputs={'answer':'Answer','sources':'Sources'}))
    adapters['perplexity.search']=Adapter(parameters=PARAMETERS,handler='orchestrator.perplexity_search:execute',
        availability=('orchestrator.perplexity_search:available',),descriptions=('orchestrator.perplexity_search:describe',),
        inspections=('orchestrator.perplexity_search:inspect',),handoffs=dict(version=1,ports=[]))
