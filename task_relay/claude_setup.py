"""Local Claude account login; never copies OAuth credentials into bridge state."""
import json
import os
from pathlib import Path
import subprocess
import sys

from task_relay.relay_paths import PATHS
from . import credentials
ROOT = PATHS.install
DATA = PATHS.data


def main():
    os.umask(0o077)
    import claude_agent_sdk
    cli = Path(claude_agent_sdk.__file__).parent / '_bundled/claude'
    env = os.environ.copy()
    for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
                'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(key, None)
    def logged_in():
        result = subprocess.run([str(cli), 'auth', 'status', '--json'], env=env, capture_output=True, text=True, timeout=20)
        try:
            status = json.loads(result.stdout)
            return status.get('loggedIn') is True and status.get('authMethod') in ('claude.ai', 'oauth')
        except ValueError:
            return False
    if not logged_in():
        print('Sign in to your Claude account in the browser opened by the official Claude runtime.', flush=True)
        if subprocess.run([str(cli), 'auth', 'login'], env=env).returncode or not logged_in():
            raise SystemExit('Claude login was not completed. Run this setup again when ready.')
    config = {'auth': 'account', 'model': 'sonnet', 'max_budget_usd': 5}
    path = DATA / 'claude.json'
    if path.exists():
        config.update(credentials.private_json(path))
    config['auth'] = 'account'
    credentials.save(path,config)

    print('\nClaude account connected. No bridge restart is needed.\nIn Telegram: /new claude "/absolute/project/folder" Task title\nThen send your instruction. /status checks the selected task.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nLogin cancelled.')
