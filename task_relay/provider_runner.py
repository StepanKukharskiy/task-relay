"""Provider connection checks, isolated from command polling; no credential logs."""
import json
import os
from pathlib import Path
import sys
from task_relay import gemini
from task_relay import providers
from task_relay import api_providers as api


def run_job(state, jid):
    row = state.db.execute('SELECT * FROM provider_jobs WHERE id=?', (jid,)).fetchone()
    if not row or row['status'] != 'running':
        return
    secret_path = gemini.DATA / 'setup-input' / (jid + '.json')
    try:
        provider = row['provider']
        if provider not in ('gemini', *api.SPECS):
            raise ValueError('This provider does not have a bot connection adapter yet.')
        if row['operation'] == 'connect':
            from .credentials import private_json
            key = private_json(secret_path).get('api_key')
        else:
            from .credentials import configuration
            selected=configuration(gemini.DATA/(provider+'.json'),enabled=False)
            key=selected.get('api_key') if selected else None
        if not key:
            raise ValueError('No saved key is available. Open Providers and connect Gemini.')
        base_url = providers.stored(provider).get('base_url')
        names = api.catalog(provider, key, base_url) if provider in api.SPECS else providers.catalog(key)
        image_names=None
        if provider in ('openai','openrouter'):
            try:image_names=api.image_catalog(provider,key,base_url)
            except (ValueError,gemini.ProviderError):pass  # Text setup survives unavailable image discovery.
        with state.db:
            state.db.execute('UPDATE provider_jobs SET status=status WHERE id=?', (jid,))
            if state.db.execute('SELECT status FROM provider_jobs WHERE id=?', (jid,)).fetchone()[0] != 'running':
                return
            if provider in api.SPECS:
                api.configure(provider, key, names, base_url, preserve_reference=row['operation']!='connect')
            else:
                providers.configure_gemini(key, names=names, preserve_reference=row['operation']!='connect')
        if image_names is not None:
            from .credentials import save
            config=api.stored(provider);config['image_catalog']=image_names
            save(gemini.DATA/(provider+'.json'),config)
        name = providers.REGISTRY[provider]['name']
        if provider=='gemini':
            from orchestrator.executors import probe
            try:probe()
            except (ValueError,gemini.ProviderError):pass  # Catalog stays unavailable without a current receipt.
        providers.finish_setup(state, jid, True, f'{name} connected. The model catalog is available; no content was generated. Open /providers → {name} → New task or Default models. Model listings do not guarantee quota, billing or regional access.')
    except gemini.ProviderError as exc:
        providers.finish_setup(state, jid, False, f'The provider did not confirm the connection ({exc.status}). Check your key, endpoint and network, then reconnect. The saved connection was not replaced.')
    except Exception:
        providers.finish_setup(state, jid, False, 'Provider setup could not finish. The saved connection was not replaced. Reopen Providers to try again.')
    finally:
        secret_path.unlink(missing_ok=True)


if __name__ == '__main__':
    os.umask(0o077)
    from task_relay.bridge import State
    state = State(Path(sys.argv[1]))
    try:
        run_job(state, sys.argv[2])
    finally:
        state.db.close()
