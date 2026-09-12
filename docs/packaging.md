# Package and command-line interface

Task Relay requires Python 3.11 or newer. The core uses Python's standard library.
Provider runtimes and optional integrations have their own requirements. Check
[platform support](native-qualification.md) before choosing an execution host;
installing the package alone does not establish that every host feature works.

## Install from source

On macOS or Linux:

```sh
git clone https://github.com/StepanKukharskiy/task-relay.git
cd task-relay
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
task-relay --help
```

This installs code and the CLI in the selected environment. Configure the channel
and providers separately, following the [quick start](../README.md#get-started).
Keep that environment available for any service installed from it. After changing
source code, reinstall the package to update an ordinary installation.

For source development, run `python3 -m task_relay` from the checkout. Root Python
scripts are compatibility entry points for the corresponding `task_relay` modules.
Application implementations live in `task_relay/`; `orchestrator/` contains the
execution runtime.

## Commands

An installed package provides `task-relay`. From a checkout, use
`python3 -m task_relay` with the same arguments:

| Command | Operation |
| --- | --- |
| `paths` | Inspect resolved data/project/output paths without creating state |
| `host` | Inspect available host mechanisms and qualification boundaries |
| `credentials PROVIDER` | Inspect credential availability without displaying secrets |
| `telegram configure` | Configure a dedicated bot and obtain a pairing link |
| `telegram run` | Run the Telegram service in the foreground |
| `telegram install` / `uninstall` | Manage the supported host's background service |
| `messages` | Optional macOS Messages service commands |
| `orchestrator` | Inspect and manage the graph execution runtime |
| `usage` | Report recorded usage and manage indexing |
| `setup-gemini` / `setup-claude` | Interactive provider setup |

Use `COMMAND --help` for command groups such as `telegram`, `orchestrator` and
`usage`. Provider setup entries are interactive. The optional `claude` package
extra supplies the pinned SDK, but managed Claude sessions still need their
separate configured runtime environment and eligible native login.

## Data locations

| Invocation | Default data | Default projects | Default generated outputs |
| --- | --- | --- | --- |
| Installed package | `~/.task-relay` | `~/task-relay-projects` | `~/task-relay-generated` |
| Direct source checkout | `private/` under the checkout | `projects/` under the checkout | `generated/` under the checkout |

[Explicit path overrides](path-configuration.md) take precedence. Installation does
not migrate or adopt an existing database. When switching between a checkout and
an installed package, inspect `paths` and deliberately select the intended data
root before configuring or starting a service.

## Build distributions

```sh
python -m pip install build
python -m build
```

This creates a wheel and source archive under `dist/`. To install a built wheel,
pass its filename to `python -m pip install`. The package metadata explicitly lists
runtime modules and maintained assets. Distributions exclude tests, research,
credentials, operational databases, user projects, generated files, built native
applications and development logs.

Icons and native Swift sources are packaged under `task_relay/assets/`. Installing
a wheel does not build, install or grant permissions to a native Messages app.
One-command onboarding, upgrade and data migration are tracked separately in
[the roadmap](../ROADMAP.md).

## Development checks

Tests and shared fixtures live in `tests/`. Run a selected module with, for example,
`python3 -m unittest tests.test_file_tools` when changing project file tools. Test
selection should follow the changed behavior and its affected integrations.
Orchestration and recovery checks use small text fixtures; media rendering or
live provider calls are not general setup or documentation checks.

`scripts/qualify_package.py` verifies archive contents, installed imports and CLI
entry points, and an isolated local text procedure. The selected native CI profiles
and their limitations are documented in [native qualification](native-qualification.md).
They do not establish account eligibility or real Telegram delivery on every host.
