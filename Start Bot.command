#!/bin/zsh
# Start/reload the existing background service without changing bot credentials.
cd -- "$(dirname -- "$0")" || exit 1
relay_python=python3
if [[ ! -x "$relay_python" ]]; then
  relay_python=$(command -v python3)
fi
"$relay_python" -m task_relay.bridge install
relay_result=$?
if [[ "$relay_result" -eq 0 ]]; then
  print '\nThe bot is running in the background. You can close this window.'
else
  print '\nThe background service could not start. Keep this error visible for troubleshooting.'
fi
read -r '?Press Return to close.'
exit "$relay_result"
