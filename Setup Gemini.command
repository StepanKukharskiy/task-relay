#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
python3 -m task_relay.gemini_setup
read -r '?Press Return to close.'
