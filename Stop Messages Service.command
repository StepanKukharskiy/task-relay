#!/bin/zsh
cd -- "${0:A:h}"
python3 messages_service.py stop
printf '\nPress Return to close this window.\n'
read -r
