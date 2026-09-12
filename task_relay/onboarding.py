"""Resumable local setup for Telegram, an API provider and a first project."""
import argparse
from contextlib import contextmanager
import getpass
import os
import secrets
import shlex
import stat
import time

from . import api_providers as api, credentials, gemini
from .diagnostics import pairing, project_folder
from .filesystem import FILES, Grant
from .host import HOST, UnsupportedHost
from .relay_paths import PATHS


@contextmanager
def setup_lock():
    PATHS.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    grant = Grant(PATHS.data, 'Serialize interactive setup', writes=frozenset({'setup.lock'}))
    with FILES.parent(grant, 'setup.lock', write=True) as (parent, name):
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    with os.fdopen(fd, 'r+') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError('Setup lock is not a regular private file.')
        try:
            HOST.lock(stream)
        except BlockingIOError:
            raise ValueError('Another setup is running. Finish it before trying again.') from None
        yield


def saved(path):
    # An invalid existing file is an error, never permission to replace it.
    return credentials.private_json(path) if path.exists() or path.is_symlink() else {}


def setup_provider(name, ask=input, hidden=getpass.getpass):
    path = PATHS.data / (name + '.json')
    saved(path)
    if path.exists():
        if not credentials.configuration(path):
            raise ValueError('Saved provider is disabled or unavailable. Resolve it with credentials or /providers; setup has preserved it.')
        print('Saved provider connection retained. No network check was repeated.')
        return
    url = api.SPECS[name]['keys'] if name in api.SPECS else 'https://aistudio.google.com/apikey'
    print('Get an API key at ' + url)
    print('The key stays in local private configuration. This checks the model catalog, without generating content.')
    key = hidden('API key (hidden): ').strip()
    if not key:
        raise ValueError('No key entered. Rerun setup when ready.')
    if name == 'gemini':
        from .providers import CANDIDATES, catalog
        names = catalog(key)
        print('Available models: ' + ', '.join(names[:20]) + (' …' if len(names) > 20 else ''))
        default = next((m for m in CANDIDATES['text'] if m in names), '')
        model = gemini.model_name(ask(f'Text model ID [{default or "enter a text model from the catalog"}]: ').strip() or default)
        if model not in names:
            raise ValueError('That model was not in the returned catalog. No key or settings were saved.')
        credentials.save(path, dict(api_key=key, enabled=True, models={'text': model},
                                    catalog=names, catalog_checked_at=time.time()))
    else:
        base = api.endpoint(name, ask('Qwen regional HTTPS endpoint (Return for Singapore): ').strip() or None) if name == 'qwen' else None
        names = api.catalog(name, key, base)
        default = api.SPECS[name]['model'] if api.SPECS[name]['model'] in names else names[0]
        print('Available models: ' + ', '.join(names[:20]) + (' …' if len(names) > 20 else ''))
        model = api.model_name(ask(f'Text model [{default}]: ').strip() or default)
        if model not in names:
            raise ValueError('That model was not in the returned catalog. No key or settings were saved.')
        # Save the selected model with the credential in one atomic replacement.
        credentials.save(path, dict(api_key=key, enabled=True, model=model, catalog=names,
                                    base_url=api.endpoint(name, base), catalog_checked_at=time.time()))
    print('Provider configured. Model listings do not prove generation access or quota.')


def setup_telegram():
    from . import bridge
    path = PATHS.data / 'config.json'
    config = saved(path)
    if not path.exists():
        bridge.configure()
        return
    if not credentials.configuration(path, 'token', enabled=False):
        raise ValueError('Saved Telegram credential is unavailable; use credentials telegram to diagnose it.')
    if pairing(PATHS.state):
        print('Existing Telegram pairing retained.')
        return
    if not config.get('username'):
        raise ValueError('Saved Telegram username is missing; run telegram configure to verify the bot.')
    if not config.get('pair_code') or config.get('pair_expires', 0) <= time.time():
        config.update(pair_code=secrets.token_urlsafe(24), pair_expires=time.time() + 3600)
        credentials.save(path, config)  # preserve references and every other setting
    print('Start the relay, then open this link and tap Start (expires within one hour):')
    print(f"https://t.me/{config['username']}?start={config['pair_code']}")


def setup(ask=input, hidden=getpass.getpass):
    HOST.require_posix('Interactive setup')
    print('Task Relay setup — completed settings survive interruption; rerun this command to continue.')
    print('Application data: ' + str(PATHS.data))
    print('Use task-relay paths to inspect bindings. Changing data roots does not migrate existing tasks.')
    with setup_lock():
        path = PATHS.data / 'onboarding.json'
        settings = saved(path)
        if settings.get('version', 1) != 1:
            raise ValueError('This setup record needs a newer Task Relay version; it was preserved.')
        settings['version'] = 1
        choices = ('gemini', *api.SPECS, 'later')
        default = settings.get('provider', 'gemini')
        print('API providers: ' + ', '.join(choices[:-1]) + '. Choose later for existing Codex tasks or separate Claude setup.')
        name = ask(f'Provider [{default}]: ').strip().lower() or default
        if name not in choices:
            raise ValueError('Choose one of the listed providers, or later.')
        settings['provider'] = name
        credentials.save(path, settings)
        if name != 'later':
            setup_provider(name, ask, hidden)
        default_project = settings.get('project', '')
        value = ask(f'Existing project directory [{default_project or "skip"}]: ').strip() or default_project
        if value:
            settings['project'] = str(project_folder(value, PATHS))
            credentials.save(path, settings)
        setup_telegram()
        print('\nConfiguration saved. Telegram pairing and a real provider task remain to be verified.')
        print('Start in the foreground: task-relay telegram run')
        print('After stopping the foreground process: task-relay telegram install')
        print('Check local configuration: task-relay doctor')
        if name != 'later' and settings.get('project'):
            print('In Telegram, create your first task with:')
            print(f'/new {name} {shlex.quote(settings["project"])} First task')
            print('Then send an instruction. Sending it authorizes that provider task and may incur provider charges.')
        else:
            print('In Telegram, use /providers to connect a provider and /tasks to select existing tasks.')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        setup()
    except (KeyboardInterrupt, EOFError):
        print('\nSetup interrupted. Saved settings remain; rerun task-relay setup to continue.')
        raise SystemExit(130) from None
    except Exception as exc:
        # Transport errors may carry credentials in URLs; never echo arbitrary exceptions.
        from .bridge import BridgeError
        if isinstance(exc, (credentials.CredentialError, UnsupportedHost, BridgeError)):
            print('Setup could not finish. Check saved credentials and host support with task-relay doctor.')
        elif isinstance(exc, ValueError) and type(exc) is ValueError:
            print(str(exc))
        else:
            print('Setup could not finish (' + type(exc).__name__ + '). Saved steps remain; check connectivity and rerun setup.')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
