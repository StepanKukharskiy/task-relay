"""Compatibility import for local maintenance; primitives also ship in the app."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from task_relay.app_bundle import (archive_bundle, retire_archived_bundle,
    replace_contents, restore_contents, finish_contents, bundle_digest, verify, run)
