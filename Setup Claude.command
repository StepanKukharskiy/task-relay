#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
CLAUDE_ENV="$(python3 relay_paths.py --field claude_python)"
if [[ ! -x "$CLAUDE_ENV" ]]; then
  python3 -m venv "${CLAUDE_ENV:h:h}"
fi
"$CLAUDE_ENV" -c 'import claude_agent_sdk' 2>/dev/null || "$CLAUDE_ENV" -m pip install -r requirements-claude-lock.txt
"$CLAUDE_ENV" claude_setup.py
read -r '?Press Return to close.'
