#!/bin/zsh
set -e
cd -- "${0:A:h}"
python3 -m task_relay.bridge uninstall
read -r '?Press Enter to close.'
