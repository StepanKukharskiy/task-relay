# Installation and first setup

The [macOS companion pilot](../desktop/README.md) bundles Python and the Relay
runtime, with a compact menu-bar setup/settings window. Everyday work stays in
Telegram; the companion handles connections, status, exact local decisions and
recovery. Existing source and Messages services require a separate reviewed
handoff before the companion manages them. The local `.app` is not a signed public
distribution and has not passed clean-host provider/Telegram acceptance. Use the
source installer below for the supported installation path.

Use macOS with Python 3.11+ for the primary supported path. The source installer
also supports Linux, whose live provider, Telegram and systemd activation
qualification remains open. Windows execution is unavailable. Install Python 3.11+
first if it is missing. Git is needed to clone the repository; downloading the
source ZIP avoids that prerequisite. The source installer creates a dedicated
virtual environment, installs Relay and its required Python build/runtime packages,
and verifies the CLI. It does not install Python or system packages or require
administrator access. Package installation needs access to Python package indexes.

On macOS, [download the public source ZIP](https://github.com/StepanKukharskiy/task-relay/archive/refs/heads/main.zip),
extract it, then double-click **Setup.command** in its folder. That script locates
its own folder and runs installation; users do not need to type `cd` or a shell
command. If installation fails, the window stays open with the error and can be
retried after fixing it. Keep the extracted folder because it holds the dedicated
environment. macOS may ask for confirmation before opening a downloaded script.

The terminal path is available on macOS and Linux:

```sh
git clone https://github.com/StepanKukharskiy/task-relay.git
cd task-relay
sh install.sh
```

The installer opens a loopback HTML setup page in your browser. Complete its steps,
then close the launcher with Ctrl+C in the installer window. The installed CLI path
is printed. Terminal users may use the printed PATH command for that terminal; in
a new terminal, activate the saved environment or use the executable by its full
path. Double-click **Setup.command** to reopen the setup page without typing a
command.

The installer owns `.venv-relay` and refuses unrelated environments. Use
`--venv /absolute/new/environment` for a different location or `--no-setup` to
install code without configuration. It resumes interrupted installation of the
same source. Keep the environment at its original path once a service uses it.

## Guided setup

Opening `task_relay/assets/launcher.html` directly shows an install guide. The
browser cannot read Relay configuration or run `install.sh` from `file://`; the
guide does not show invented status or active controls. When the installer opens
the loopback server, the launcher shows the installed version, saved project,
provider and Telegram status, local diagnostics, cached release information and
detected tools. Its header uses the Task Relay blue-on-white logo. The setup page
explains which dependencies the installer handles and which tools are optional. Browser automation
needs the separate Playwright package and Chromium installation described in
[general browser setup](general-browser.md); managed Claude uses its dedicated
runtime and account setup. Codex, Blender and FFmpeg are only needed for workflows
that use them. The launcher does not install external applications. Its download
button retrieves the **public source ZIP** from GitHub; it does not export
local projects, tasks or credentials. Reopen it with `task-relay launcher` (or
`task-relay launcher --no-open` to print its local URL). The server listens only on
127.0.0.1 with a per-run private URL; closing the terminal stops it. Page load only
reads local status. An explicit provider submission checks the model catalog, an
explicit Telegram submission checks bot identity and webhook status, and **Check
updates** contacts GitHub. No task or message is sent by these controls. Each
completed setting is saved for interruption recovery.

Use `task-relay setup` or `sh install.sh --terminal-setup` for the CLI wizard. The
same setup order applies to either interface:

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

- **Interrupted setup:** reopen `task-relay launcher` or rerun `task-relay setup`. Each completed setting is saved
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

The source installer resumes installation of the same source and refuses changed
source in its existing environment. Starting with 0.12.0, use `task-relay update`
for published compatible core releases. It prepares a separate environment,
checks unfinished work and storage compatibility, then switches the owned Telegram
service with a startup gate and recovery receipts. `task-relay update rollback`
retains newer task history. See [update instructions](updates.md) for limitations
and the one-time bootstrap from older installations.

While the bot is running, daily stable-release checks and Telegram notices are on
by default. `task-relay update notifications off` disables both. Downloads and
installation require an explicit `update apply --version VERSION` command.
Version 0.12.1 adds explicit additive-schema migration plans and guarded reversal;
see the controller bootstrap instructions before upgrading from 0.12.0. Destructive
data conversions and separate Messages deployment updates remain outside this scope.
