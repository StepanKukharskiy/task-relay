# Installation and data paths

Task Relay separates application code, private state and project work. The shared
resolver in `task_relay/relay_paths.py` supplies paths to the service, provider
runners and execution runtime. Inspecting paths creates no folders, moves no data
and grants no project access:

```sh
task-relay paths
task-relay paths --field state
```

From a source checkout, use `python3 -m task_relay paths` instead.

## Defaults

| Binding | Installed package | Direct source checkout |
| --- | --- | --- |
| Application data and configuration | `~/.task-relay/` | `private/` |
| Default user projects | `~/task-relay-projects/` | `projects/` |
| Generated deliveries | `~/task-relay-generated/` | `generated/` |

Checkout defaults are relative to the checkout, not the shell's working directory.
Installed-package defaults are relative to the current user's home directory and
do not store runtime data in site-packages.

Within the application data directory:

| Location | Purpose |
| --- | --- |
| `state.sqlite` | Shared Telegram and production state |
| `orchestrator/` | Execution artifacts and workspaces |
| `messages-pilot/` | Optional Messages integration state |
| `claude-venv/` | Managed Claude runtime environment |

Maintained icons and native build sources belong to `task_relay/assets/` in the
installed code, rather than to user data.

## Explicit overrides

| Environment variable | Binding |
| --- | --- |
| `TASK_RELAY_DATA_DIR` | Configuration, state, logs, backups and execution data |
| `TASK_RELAY_WORKSPACE_DIR` | Default project folder |
| `TASK_RELAY_GENERATED_DIR` | Generated-delivery folder |

Values must be nonempty absolute paths; `~` is expanded. Invalid settings stop
startup. With a custom data root and no other overrides, project and output folders
are siblings named `<data-name>-projects` and `<data-name>-generated`, with a leading
dot removed from the data name.

For example, select separate locations before configuring an instance:

```sh
export TASK_RELAY_DATA_DIR="$HOME/.task-relay"
export TASK_RELAY_WORKSPACE_DIR="$HOME/relay-projects"
export TASK_RELAY_GENERATED_DIR="$HOME/relay-outputs"
task-relay paths
```

Project/output roots must not expose application data or contain the installation.
Choose a visible project folder compatible with the selected worker's file tools.
A configured path is not authorization to read or edit its contents; see
[access boundaries](host-adapters.md).

## Services and existing data

Provider children inherit the resolved bindings. Service adapters record them so
startup does not depend on an interactive shell. Managed service updates reject
an implicit switch to another data root. Use the same intended bindings when
configuring the channel and installing its service.

Changing an override does **not** move credentials, migrate history or import
another database. Stop and plan an explicit migration before changing an existing
installation's data location. Separate instances need their own configuration and
pairing; do not point concurrent instances at one operational store.

The macOS Messages launcher records bindings at build time. A native app rebuild
can require Full Disk Access to be granted again. Building or starting the app does
not by itself verify Messages access. See [host adapters](host-adapters.md) and the
[roadmap](../ROADMAP.md) for platform and migration support.

## Source and distribution boundary

`source_inventory.json` and `scripts/source_inventory.py` enumerate maintained
source files and hashes. The inventory excludes operational data, provider
environments, user projects, generated deliveries, built apps and caches.
`outputs/` is local development evidence and is excluded from version control.

```sh
python3 scripts/source_inventory.py
```

`pyproject.toml` and `MANIFEST.in` define the narrower wheel/source-archive contents.
See [packaging](packaging.md) for build instructions and distribution boundaries.
