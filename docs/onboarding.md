# Installation and first setup

Use macOS with Python 3.11+ for the primary supported path. The source installer
also supports Linux, whose live provider, Telegram and systemd activation
qualification remains open. Windows execution is unavailable. Install Python and
Git first if they are missing; the installer does not install system packages or
require administrator access. Package installation needs access to Python package
indexes for build dependencies.

```sh
git clone https://github.com/StepanKukharskiy/task-relay.git
cd task-relay
sh install.sh
export PATH="$PWD/.venv-relay/bin:$PATH"
```

The PATH command applies to this terminal. In a new terminal, activate the saved
environment or add its absolute `bin` directory to your shell configuration.
You can also invoke the `task-relay` executable by its full path.

The installer owns `.venv-relay` and refuses unrelated environments. Use
`--venv /absolute/new/environment` for a different location or `--no-setup` to
install code without configuration. It resumes interrupted installation of the
same source. Keep the environment at its original path once a service uses it.

## Guided setup

Run `task-relay setup` to begin or resume:

1. Inspect the application data directory printed before setup. Installed packages
   default to `~/.task-relay`; direct source invocations use the checkout's
   `private/` directory. Use [path overrides](path-configuration.md) before setup
   when deliberately reusing existing data. Setup does not move databases.
2. Choose Gemini, OpenAI, Qwen, DeepSeek or OpenRouter. Enter a key through the
   hidden local prompt and choose a model from the returned catalog. Qwen asks for
   the endpoint matching the key's region. These checks contact the provider but
   do not generate content. A model listing does not establish quota or generation
   access. Previously saved connections are retained without another network check.
3. Select an existing project directory, or skip it. Setup records the directory
   to produce a correctly quoted `/new` command. It does not create a task, grant
   worker access or change every task's workspace.
4. Create a dedicated Telegram bot through **@BotFather**, then enter its token.
   Setup reads bot identity and webhook metadata and saves a one-hour pairing link.
   A bot with an existing webhook is rejected. Existing pairing is preserved.

Choose `later` for providers if you want to connect them through `/providers`, use
existing Codex desktop tasks, or set up Claude separately. Codex desktop tasks
require the desktop application and are selected through `/tasks`. Managed Claude
requires its dedicated runtime and eligible native account login; the API wizard
does not install that runtime. The source checkout includes `Setup Claude.command`
for that separate macOS path. The legacy `telegram doctor` command diagnoses the
Codex desktop route; the general `task-relay doctor` does not require Codex.

## Start and verify

```sh
task-relay telegram run
```

Keep this terminal open. Open the printed pairing link, tap **Start**, send the
printed `/new` command, then a small instruction such as “Read README.md and
summarize it in three bullets.” Sending the instruction authorizes provider work
and may incur charges. A returned answer verifies that task's provider and delivery
path. Setup itself does not claim that verification occurred.

To run in the background, stop the foreground process with Ctrl+C, then run
`task-relay telegram install`. This installs a login service on macOS or a systemd
user service on Linux when a user manager is available. Otherwise keep using the
foreground command. `task-relay telegram uninstall` removes the owned background
service and retains application data.

## Recovery and troubleshooting

- **Interrupted setup:** rerun `task-relay setup`. Each completed setting is saved
  atomically. Saved keys, project selection and pairing survive; unfinished checks
  can be retried. An expired unpaired link is renewed while preserving its token
  source. A second simultaneous setup is rejected.
- **Command not found:** activate the installation environment or use its absolute
  `bin/task-relay` path. Python is a prerequisite, not bundled with Task Relay.
- **Missing configuration:** run `task-relay doctor`. It does not initialize state,
  contact providers, send messages or inspect service health. `--json` returns the
  same local checks; exit code 1 indicates a failed check, while warnings identify
  unfinished steps.
- **Saved credential unavailable:** run `task-relay credentials PROVIDER` (use
  `telegram` for the bot). Restore the configured source or fix its file permissions.
  Setup does not overwrite invalid or disabled existing credentials. Use
  `/providers` to deliberately update or enable an existing API connection.
- **No reply:** inspect foreground logs, confirm you used the correct pairing link,
  and check the selected provider through `/providers`. Local doctor success is
  not evidence of network access, model eligibility or message delivery.
- **Project moved:** rerun setup and select its new location. Existing tasks keep
  their own recorded directories; changing setup does not rewrite them.

## Upgrades and migration

Automatic upgrade, rollback and data migration are not implemented. The source
installer refuses changed source in an environment it previously installed. This
prevents an install retry from silently replacing code used by a running service.
Keep the existing installation and data intact. A separate `--venv` can be used to
inspect new code; do not run two relays against the same data or Telegram bot.
Switching data directories is not a migration. Safe upgrade and migration tooling
is the next O13 implementation step.
