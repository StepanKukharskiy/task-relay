#!/bin/zsh
set -e
cd -- "${0:A:h}"
exec python3 -m task_relay.bridge run
