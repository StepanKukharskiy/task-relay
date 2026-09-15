#!/bin/zsh
cd -- "${0:A:h}"
read -r "relay_pair_code?Enter the current pairing code: "
[[ -n "$relay_pair_code" ]] || exit 1
python3 -m task_relay.messages_diagnose --code "$relay_pair_code"
printf '\nPress Return to close this window.\n'
read -r
