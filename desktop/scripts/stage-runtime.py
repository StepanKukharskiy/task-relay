"""Copy only reviewed release sources into the desktop's generated runtime."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.source_inventory import inventory


def main():
    app = ROOT / 'desktop/src-tauri/resources/runtime/app'
    legacy = app.parent / 'helpers/Messages Relay.app'
    if legacy.is_symlink():raise ValueError('Generated Messages helper must not be linked.')
    sources = [entry['path'] for entry in inventory()['files'] if entry['release']]
    if app.is_symlink():
        raise ValueError('The generated runtime source directory must not be a symlink.')
    if legacy.exists():shutil.rmtree(legacy)
    # Rebuild this generated directory so retired sources cannot survive a restage.
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)
    for name in sources:
        target = app / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    shutil.copy2(ROOT / 'desktop/scripts/relay_bridge_entry.py', app / 'desktop_bridge_entry.py')
    print(f'Staged {len(sources)} reviewed runtime files.')


if __name__ == '__main__':
    main()
