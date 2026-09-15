#!/bin/zsh
cd -- "${0:A:h}"
python3 -m task_relay.messages_service stop
printf '\nPress Return to close this window.\n'
read -r
