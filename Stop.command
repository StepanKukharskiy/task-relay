#!/bin/zsh
set -e
cd -- "${0:A:h}"
python3 bridge.py uninstall
read -r '?Press Enter to close.'
