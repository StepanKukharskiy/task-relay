#!/bin/sh
set -eu
desktop_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo 'This pinned desktop runtime currently targets macOS Apple Silicon.' >&2
  exit 1
fi
archive=${TASK_RELAY_PYTHON_ARCHIVE:-"$desktop_dir/build/cpython-3.14.7-macos-arm64.tar.gz"}
url='https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.14.7%2B20260901-aarch64-apple-darwin-install_only_stripped.tar.gz'
sha='4632cb1a6edad9e73d3c81b6d2e69131637d995173e3e85005df14102b0592ba'
mkdir -p "$(dirname -- "$archive")"
if [ ! -f "$archive" ]; then
  curl -fL --output "$archive" "$url"
fi
printf '%s  %s\n' "$sha" "$archive" | shasum -a 256 -c -
runtime="$desktop_dir/src-tauri/resources/runtime"
rm -rf "$runtime"
mkdir -p "$runtime"
tar -xzf "$archive" -C "$runtime"
"$runtime/python/bin/python3" -m pip install --only-binary=:all: --require-hashes -r "$desktop_dir/scripts/requirements-runtime.txt"
python3 "$desktop_dir/scripts/stage-runtime.py"
(cd "$runtime/app" && "$runtime/python/bin/python3" -B -m task_relay.bridge --help >/dev/null)
echo 'Bundled Python and Task Relay runtime are ready.'
