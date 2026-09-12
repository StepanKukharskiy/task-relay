"""Local installation checks. Never initializes databases or calls a provider."""
import argparse
import json
import os
from pathlib import Path
import sqlite3

from . import credentials
from .host import HOST
from .relay_paths import PATHS


def pairing(path):
    if not path.exists():
        return False
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        rows = dict(db.execute("SELECT key,value FROM kv WHERE key IN ('user_id','chat_id')"))
        return all(json.loads(rows.get(key, 'null')) is not None for key in ('user_id', 'chat_id'))
    finally:
        db.close()


def project_folder(value, paths=PATHS):
    folder = Path(value).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError('Choose an existing absolute project directory.')
    folder = folder.resolve()
    if any(folder.is_relative_to(p) or p.is_relative_to(folder)
           for p in (paths.data, paths.install)):
        raise ValueError('Choose a project outside application data and installation directories.')
    if not os.access(folder, os.R_OK | os.X_OK):
        raise ValueError('The project directory is not readable by this account.')
    if any(ord(c) < 32 for c in str(folder)):
        raise ValueError('Project paths cannot contain control characters.')
    return folder


def inspect(paths=PATHS, host=HOST):
    checks = []
    def add(name, status, detail):
        checks.append(dict(check=name, status=status, detail=detail))
    supported = host.platform in ('darwin', 'linux')
    add('host', 'ok' if supported else 'fail',
        'Execution adapter available.' if supported else 'Task execution is unsupported on this host.')
    if host.platform == 'linux':
        add('qualification', 'info', 'Linux live provider, Telegram and systemd activation qualification remains open.')
    if supported:
        available = credentials.status(paths.data / 'config.json', 'token')['available']
        add('telegram', 'ok' if available else 'fail',
            'Credential resolves locally; network access is unchecked.' if available else 'Run task-relay setup to configure Telegram; use credentials telegram to diagnose a saved token.')
        try:
            paired = pairing(paths.state)
            add('pairing', 'ok' if paired else 'warn',
                'A saved account pairing exists; delivery is unchecked.' if paired else 'Start the relay and open the setup pairing link in Telegram.')
        except (sqlite3.Error, ValueError, OSError):
            add('pairing', 'fail', 'Saved pairing database is unreadable; preserve it and resolve the error before setup.')
        from .api_providers import SPECS
        configured = [name for name in ('gemini', *SPECS)
                      if credentials.status(paths.data / (name + '.json'))['available']]
        try:
            claude = credentials.private_json(paths.data / 'claude.json')
            if claude.get('auth') == 'account' and claude.get('enabled', True) and paths.claude_python.is_file():
                configured.append('claude')
        except credentials.CredentialError:
            pass
        add('providers', 'ok' if configured else 'warn',
            'Locally configured: ' + ', '.join(configured) + '. Account/model access is unchecked.' if configured
            else 'No API or managed Claude provider is configured. Run setup or use /providers. Existing Codex desktop tasks are a separate route.')
        try:
            settings = credentials.private_json(paths.data / 'onboarding.json') if (paths.data / 'onboarding.json').exists() else {}
            if settings.get('project'):
                project_folder(settings['project'], paths)
                add('project', 'ok', 'Saved first-project directory is available; no task or file grant was created by setup.')
            else:
                add('project', 'warn', 'Run setup to select a first project, or supply its folder with /new in Telegram.')
        except (ValueError, OSError, TypeError):
            add('project', 'fail', 'Saved setup/project is invalid or unavailable; restore the directory or select another through setup.')
    from . import releases
    try:
        update = releases.cached(paths.data)
        latest = update.get('release')
        if latest and releases.version(latest['version']) > releases.version(releases.VERSION):
            add('update', 'info', 'Task Relay ' + latest['version'] + ' is available: ' + latest['url'])
        else:
            add('update', 'info', 'No newer release in the local cache. Run task-relay update check to contact GitHub.')
        if update.get('error'):
            add('update-check', 'warn', update['error'])
    except (ValueError, sqlite3.Error, OSError):
        add('update-check', 'warn', 'Release cache is unreadable; task-relay update check can diagnose connectivity.')
    add('service', 'info', 'Runtime health and delivery are unchecked. Use telegram run for foreground logs; telegram install manages the supported background service.')
    return dict(ok=not any(c['status'] == 'fail' for c in checks), checks=checks,
                scope='Local configuration only; no network, messages, generation or service changes.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Machine-readable checks with no secret values')
    args = parser.parse_args()
    report = inspect()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report['checks']:
            print(f"{row['status'].upper()} {row['check']}: {row['detail']}")
        print(report['scope'])
    raise SystemExit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
