#!/bin/zsh
set -e
cd -- "${0:A:h}"
PYTHON='python3'
"$PYTHON" bridge.py doctor
"$PYTHON" bridge.py configure
"$PYTHON" bridge.py install
echo 'Setup complete. Tap Start on the Telegram pairing link printed above.'
read -r '?Press Enter to close.'
