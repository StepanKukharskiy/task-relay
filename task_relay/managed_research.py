"""Execute one durably assigned Chrome research job through the provider scheduler."""
from pathlib import Path
from orchestrator.storage import transaction
from . import browser_research as research
from .browser_jobs import Journal, execute


def interrupted(state, receipt, detail):
    """An interrupted submission becomes inspectable, never queued for replay."""
    with transaction(state.db):
        journal = Journal(state.db)
        job = journal.get(receipt)
        if job['status'] not in ('completed', 'blocked', 'uncertain'):
            journal.update(receipt, 'uncertain' if job['status'] == 'submitting' else 'blocked', error=detail)
        result = journal.get(receipt)
        research.finalize(state, result)
        state.db.execute('UPDATE provider_jobs SET status=? WHERE id=?',
                         ('completed' if result['status'] == 'completed' else 'failed', receipt))


def run(state, receipt, driver_factory=None):
    from .perplexity_browser import profile_lock, browser_page
    data = Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent
    try:
        with profile_lock(data) as root:
            with transaction(state.db):
                row = state.db.execute('''SELECT r.state FROM browser_research_requests r
                    JOIN browser_research_transport t ON t.id=r.id
                    JOIN provider_jobs p ON p.id=r.id
                    WHERE r.id=? AND t.transport='chrome' AND p.status='running' ''', (receipt,)).fetchone()
                if not row or row[0] not in ('queued', 'inspect'):
                    return
                inspect = row[0] == 'inspect'
                state.db.execute("UPDATE browser_research_requests SET state='running' WHERE id=?", (receipt,))
            if not research.managed_enabled(state):
                raise ValueError('Enable Browser use in Task Relay Settings.')
            with (driver_factory or browser_page)(root) as driver:
                result = execute(Journal(state.db), receipt, driver, reconcile=inspect)
            with transaction(state.db):
                research.finalize(state, result)
                state.db.execute('UPDATE provider_jobs SET status=? WHERE id=?',
                                 ('completed' if result['status'] == 'completed' else 'failed', receipt))
    except Exception:
        interrupted(state, receipt, 'The Relay browser could not finish this job. Open Task Relay Settings → Browser use to check Chrome and sign-in. Inspect this receipt before retrying.')
