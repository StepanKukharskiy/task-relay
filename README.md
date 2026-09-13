# Task Relay

**Coordinate agents, tools and project work from one inbox.**

[Website](https://task-relay-website-production.up.railway.app)

Task Relay is a self-hosted execution service with a Telegram interface. Send a
request, choose the references and review a bounded plan. Relay coordinates the
workers, preserves their outputs and brings back results or decisions that need you.

New messages go to the orchestrator. Reply to a task message to continue that task.
`/use` selects a target for commands; it does not redirect new messages. `/routing`
shows where messages go.

## What it does

- **Routes requests** to existing tasks or proposes a new workflow for approval.
- **Coordinates work** across agents, API calls and registered procedures, with
  explicit inputs, outputs, dependencies and limits.
- **Keeps decisions attached to exact outputs.** Select a version, request a revision,
  pause a stage or continue from an accepted result.
- **Preserves execution history.** Requests, artifact versions, approvals and
  execution receipts survive restarts. Uncertain submissions are not automatically
  repeated.
- **Returns results through Telegram**, including supported file attachments and
  task status. Recorded token usage is available through `/usage`.

Task Relay is in active development. Workflows are bounded by the capabilities of
their selected workers; it does not provide unrestricted automation of arbitrary
applications.

Registered local modeling includes [Blender](docs/local-applications.md) and
[direct Rhino 7/8 on macOS](docs/rhino.md), with native candidates, previews and
reviewed execution. Grasshopper support is paused.

## Platform support

| Platform | Current support |
| --- | --- |
| macOS | Primary execution host. Telegram, local workers and optional Apple Messages integration. |
| Linux | Native text-worker, recovery and file-access checks pass. Foreground operation and an optional systemd user-service adapter are implemented; service and live provider/Telegram qualification remain open. |
| Windows | Package installation, imports and CLI inspection are checked. Task execution is not supported yet. |

See [native qualification](docs/native-qualification.md) for the tested scope and
[the roadmap](ROADMAP.md) for remaining work. Apple Messages is a separate macOS
pilot with a smaller feature set than Telegram.

## Get started

**Mac beta:** [download the DMG](https://task-relay-website-production.up.railway.app/#download)
for Apple Silicon and macOS 14+. Drag Task Relay into Applications and follow the
app's four saved setup steps. Python is bundled. This beta lacks Apple Developer
ID/notarization; the website explains macOS's per-app opening step and limitations.
Existing services require reviewed handoff. First-time Messages enrollment remains
an optional pilot; Telegram is the complete onboarding path.

**CLI alternative:** the same download page offers matching beta source. With
Python 3.11+, extract it and run `sh install.sh --terminal-setup`. Keep its installed
environment in place. CLI commands honor the data binding previously selected in
the companion; explicit environment overrides take precedence.

The development source route remains available:

Start on **macOS with Python 3.11 or newer**, a dedicated Telegram bot token and a
provider account or API key for the work you want to run. [Download the source
ZIP](https://github.com/StepanKukharskiy/task-relay/archive/refs/heads/main.zip),
extract it, and double-click **Setup.command** in the extracted folder. It finds
its own folder, installs Relay and opens the local setup page. No terminal command
or Git checkout is needed for this macOS path.

The terminal alternative, also used on Linux, is:

```sh
git clone https://github.com/StepanKukharskiy/task-relay.git
cd task-relay
sh install.sh
```

The installer creates a dedicated Python environment and opens a local setup page.
Opening its HTML file directly shows the complete install guide; live status and
configuration controls appear only when the installer opens the local server.
Follow its project, provider and Telegram steps.
It installs Relay’s required Python packages automatically. Python 3.11+ must
already be installed; Git is needed for cloning but not for the source ZIP.
Optional browser, Claude and media tools are installed separately when needed.
API keys and bot tokens are entered locally and are not shown in status checks.
Choose `later` to configure providers separately or use existing Codex tasks.
The source installer prints the installed CLI path. Terminal users can add it to
their PATH with the printed command. Reopen setup by double-clicking
**Setup.command** again, or use `task-relay launcher` from the installed environment.
The CLI wizard remains available through `sh install.sh --terminal-setup`.

Setup checks the provider's model catalog and Telegram bot metadata. The page
shows a pairing link and, once a project and provider are ready, a first-task
command. It does not send messages or run a model.
Start the relay:

```sh
task-relay telegram run
```

With the service running, open the pairing link in Telegram and tap **Start**.
Send the `/new` command shown by setup, then your first instruction. This
instruction starts provider work and may incur provider charges. A returned reply
confirms that task's provider and Telegram path. `/providers` manages connections
and models.

If interrupted, reopen `task-relay launcher` or rerun `task-relay setup`. Saved
credentials and existing pairing are retained. `task-relay doctor` checks local
configuration and reports remaining steps without making network calls. See
[setup and troubleshooting](docs/onboarding.md).

Keep the foreground process running while using the bot. To run it in the
background, stop the foreground process first, then use:

```sh
task-relay telegram install
```

On macOS this installs a login service. On Linux it requires a working systemd
user manager; otherwise use the foreground command under your chosen supervisor.
Use `task-relay telegram uninstall` to remove the service while retaining saved
configuration and task records. Keep `.venv-relay` in place while the service uses
it. For future releases, use `task-relay update check` and select a version with
`task-relay update apply --version VERSION`. The running bot checks daily and sends
one notice per newer release; disable this with `task-relay update notifications off`.
See [updates and rollback](docs/updates.md) for scope, recovery and first-upgrade
instructions. Version 0.12.1 adds reviewed additive-schema migration plans;
destructive data conversions need a separate plan.

## Working from Telegram

Use `/tasks` to find a task, or create a provider task in a project folder:

```text
/new gemini "/absolute/path/to/project" Review project
Read README.md and suggest improvements.
```

To create a Codex task without starting work, use
`/new codex "/absolute/path/to/known/project" Task title`, or ask Relay to create
one in a named project. Explicitly asking to create a task and do work there queues
the original request as its first turn. This uses an existing local checkout and
inherits Codex configuration; uncertain creation is never automatically retried.
Connected creation still needs live qualification on the installed Codex version.

Use `/templates` in Telegram or Messages to see the five bundled cross-tool
workflow starters, or `task-relay workflows` locally. Ask to prepare a chosen
stage for your project; the existing planner presents its concrete scope before
execution. See [project tasks and starter workflows](docs/project-tasks-and-starters.md)
for stage lists, required integrations and current limits.

Replace the example path with an existing folder on the execution host. Reply to
that task's messages to continue its conversation. Use `/status` to inspect progress
and `/providers` to manage connections. A shortcut such as `/gemini INSTRUCTION`
uses the replied-to or selected task's project context.

Available integrations include Codex desktop tasks and CLI workers, managed Claude
sessions, Gemini, and OpenAI-compatible text-provider routes for OpenAI, Qwen,
DeepSeek and OpenRouter. Capabilities differ: direct text API tasks can read project
files, while editing, shell execution and media operations require a worker or
adapter that supports them. Claude needs its own eligible native login; the Codex
desktop route needs the desktop application running.

For coordinated work, a request and selected references become a concrete plan
before execution. Results retain their identity across review and revision; choosing
an output does not silently authorize unrelated work. See
[planning](docs/new-pipeline-planning.md), [mixed execution](docs/mixed-execution.md)
and [production controls](docs/production-selections.md).

## Data and access

Task Relay runs on your host and stores configuration, task history and artifacts
locally. An installed package defaults to `~/.task-relay` for application data;
project and generated-output folders are separate. Inspect or configure these
locations with `task-relay paths` and the documented
[path overrides](docs/path-configuration.md).

Prompts and results travel through Telegram. Requested content is sent to the
selected provider. Telegram bot chats are not end-to-end encrypted; the provider
connection flow explains how keys entered through chat are handled. Keep sensitive
material outside folders granted to workers.

File access and cancellation depend on the execution adapter. Read-only project
tools, declared-file workers and shell workers have different boundaries. Approval
applies to the recorded action, and cancellation does not undo work already done.
See [host and access boundaries](docs/host-adapters.md).

## License

Copyright 2026 Stepan Kukharskiy.

Task Relay is licensed under the [Apache License, Version 2.0](LICENSE).
Third-party dependencies retain their respective licenses.

## Development

Application code lives in `task_relay/`, the execution runtime in `orchestrator/`,
and tests in `tests/`. From a source checkout, use `python3 -m task_relay --help`.
Run only the tests relevant to a change; see [development and packaging](docs/packaging.md).

[Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md) ·
[Worker runtime](docs/worker-runtime.md) · [Usage tracking](docs/usage-tracking.md)
