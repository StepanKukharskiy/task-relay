#!/bin/zsh
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
read -r "relay_task_id?Codex task ID (leave blank to use the saved task): "
relay_args=()
[[ -z "$relay_task_id" ]] || relay_args=(--task "$relay_task_id")
python3 -m task_relay.messages_pilot "${relay_args[@]}"
printf '\nPress Return to close this window.\n'
read -r
