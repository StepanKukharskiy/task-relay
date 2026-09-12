#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
python3 gemini_setup.py
read -r '?Press Return to close.'
