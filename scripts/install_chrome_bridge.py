"""Register the reviewed capture bridge for one explicitly selected extension."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from task_relay.host_browser_capture import install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extension-id', required=True)
    parser.add_argument('--data-dir', required=True, help='Explicit existing Relay data folder, or a new isolated test folder')
    parser.add_argument('--registration-dir', help='Override only for an isolated controlled test')
    args = parser.parse_args()
    print(json.dumps(install(args.extension_id, args.data_dir, ROOT, sys.executable, registration=args.registration_dir), indent=2))


if __name__ == '__main__': main()
