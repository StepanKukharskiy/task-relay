# Task Relay

**Coordinate agents, tools and project work from one inbox.**

Task Relay is a self-hosted execution service with a Telegram interface. Send a
request, choose the references and review a bounded plan. Relay coordinates the
workers, preserves their outputs and brings back results or decisions that need you.

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

Start on **macOS with Python 3.11 or newer**, a dedicated Telegram bot token and a
provider account or API key for the work you want to run. Install from source:

```sh
git clone https://github.com/StepanKukharskiy/task-relay.git
cd task-relay
sh install.sh
export PATH="$PWD/.venv-relay/bin:$PATH"
```

The installer creates a dedicated Python environment and opens guided setup. It
asks for an API provider, a model, an existing project folder, and a dedicated
Telegram bot token from **@BotFather**. API keys are entered locally with hidden
input. Choose `later` to configure providers separately or use existing Codex tasks.

Setup checks the provider's model catalog and Telegram bot metadata. It prints a
pairing link and a first-task command; it does not send messages or run a model.
Start the relay:

```sh
task-relay telegram run
```

With the service running, open the pairing link in Telegram and tap **Start**.
Send the `/new` command printed by setup, then your first instruction. This
instruction starts provider work and may incur provider charges. A returned reply
confirms that task's provider and Telegram path. `/providers` manages connections
and models.

If interrupted, run `task-relay setup` again. Saved credentials and existing pairing
are retained. `task-relay doctor` checks local configuration and reports remaining
steps without making network calls. See [setup and troubleshooting](docs/onboarding.md).

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
instructions. Explicit data migration remains planned.

## Working from Telegram

Use `/tasks` to find a task, or create a provider task in a project folder:

```text
/new gemini "/absolute/path/to/project" Review project
Read README.md and suggest improvements.
```

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

## Development

Application code lives in `task_relay/`, the execution runtime in `orchestrator/`,
and tests in `tests/`. From a source checkout, use `python3 -m task_relay --help`.
Run only the tests relevant to a change; see [development and packaging](docs/packaging.md).

[Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md) ·
[Worker runtime](docs/worker-runtime.md) · [Usage tracking](docs/usage-tracking.md)
