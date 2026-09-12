#!/bin/sh
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.11 or newer is required. Install it, then rerun this installer.' >&2
  exit 1
fi
exec python3 "$(dirname "$0")/scripts/install.py" "$@"
