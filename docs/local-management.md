# Local Relay management

Relay 0.13.322 adds a supported local interface for a person or local coding agent
to discover, diagnose, update and recover an installed app. It uses the existing
app updater; it does not introduce a new scheduler, message sender or repair agent.
Installing Relay does not automatically grant Codex access or register an MCP
server. Terminal/file access and system permissions remain the user's choices.

## Mac app

The signed app includes Python and a launcher which also survives in retained
update helpers. No source checkout, system Python, GitHub login or developer
signing key is required to install an official compatible update.

```sh
RELAY='/Applications/Task Relay.app/Contents/Resources/resources/runtime/relay'
"$RELAY" manage discover
"$RELAY" manage diagnose
"$RELAY" manage update-status
```

Use the actual app location if installed elsewhere. Discovery lists the standard
Applications locations and the invoking app, without searching personal folders
or starting other copies. Diagnostics are local: no provider requests, messages,
job execution or service changes. They report configuration, native signature,
service health and update admission. A failed optional Telegram/provider setup
check does not automatically establish that app installation is blocked.

### Local startup (0.13.327)

Telegram is optional. Relay's local worker can process explicitly submitted Jobs
without a bot or pairing. Missing or unreadable Telegram credentials hold remote
delivery while preserving the saved configuration and reply receipts. Settings
reports a credential problem separately from local service health.

After choosing a provider or Later, opening the desktop app attempts to start its
owned background service. Stop Relay pauses both app-open and login startup until
Start Relay is chosen again. Failed or interrupted startup is not automatically
repeated on reopening. A loaded but unhealthy worker requires diagnosis, and an
existing service owned by another installation requires reviewed handoff.

The text headed “Current executable” and “Companion executable” is a handoff
review, not proof that a service started. Handoff itself preserves stopped state;
the app's separate startup step follows a completed handoff unless startup is
paused. Incomplete or unreadable handoff receipts block automatic startup.
“Check connection” opens local diagnostics; configuring Telegram cannot repair
a failed local worker. Preserve the data folder and inspect the service error
before another start attempt.

The launcher disables Python bytecode writes and ignores Python environment/path
injection. Do not run a system interpreter inside the signed bundle or edit its
contents. Data, project and output paths follow explicit Relay environment
overrides, then the saved desktop binding, then package defaults. A malformed
saved binding is reported rather than silently selecting another database.

## Agent skill

The `relay-manage` and `relay-author` skills ship inside Relay. Starting with
0.13.327, opening the Mac app installs them offline into `~/.agents/skills`, the
user-level discovery location for local ChatGPT Desktop / Codex skills. Existing
copies in `$CODEX_HOME/skills` or `~/.codex/skills` are reused to avoid duplicates.
Exact copies are recorded for automatic future updates; edited, linked or unrelated
copies are preserved and reported in Settings → ChatGPT / Codex skills. Partial
managed installs recover from a write-ahead receipt without overwriting edits.
Neither Telegram nor the background worker is needed for skill installation.

Start a new agent chat to use them; restart the agent if they do not appear.
Local client policy and filesystem access still apply. This does not install the
separate Relay conversation-reuse plugin or grant access to cloud ChatGPT chats.
See [OpenAI's local skill discovery documentation](https://learn.chatgpt.com/docs/build-skills).

To check or repair both bundled skills explicitly, run `"$RELAY" manage skills-sync`.
To inspect or install a copy at a custom location:

```sh
"$RELAY" manage skill
"$RELAY" manage skill-install --destination "$HOME/.agents/skills/relay-manage"
```

For a custom Codex home or another agent, supply that agent's skill directory.
No agent configuration is rewritten. Existing identical copies are unchanged;
edited, partial, linked or unrelated destinations are refused. Choose a fresh
destination when preserving an edited skill. Skill discovery may require a new
chat or client reload. The skill is also distributed as a release ZIP for manual
installation. It is separate from the conversation-reuse Task Relay plugin.

## Update and recovery commands

All management responses use protocol 1: `{"protocol":1,"ok":true,"action":...,"result":...}`
or `{"protocol":1,"ok":false,"action":...,"error":{"code":...,"message":...}}`.
Exit 0 means the command completed; inspect the result for diagnostic health and
asynchronous phases. Exit 2 reports failure. `--help` prints ordinary CLI help.
Read-only output can include private local paths; it excludes credential values,
job contents and raw database records. Do not publish it automatically.

| Command after `manage` | Behavior |
| --- | --- |
| `discover` | Local installation, bindings and skill discovery |
| `diagnose` | Local configuration and app checks |
| `skill` | Locate the bundled skill |
| `skills-sync` | Install/update bundled local skills, preserving personal edits |
| `skill-install --destination PATH` | Explicitly copy the skill without overwriting existing work |
| `update-status` | Read cached candidate/current attempt; no network |
| `update-check [--beta]` | Fetch public release metadata; no package installation |
| `update-download --candidate ID` | Prepare the exact selected candidate asynchronously |
| `update-install --attempt ID` | Approve that ready attempt and launch normal installation |
| `update-receipts [--attempt ID]` | Read retained receipt metadata and recovery command |
| `update-recover --attempt ID` | Recover the exact interrupted attempt; never repeat an active worker |

For the beta, check with `--beta`, download the returned candidate ID, observe
`update-status` until `ready`, then install using the returned attempt ID. Observe
until `complete`; a successful launch is not a completed installation. Existing
signature, exact identity, active-work, data-compatibility and no-replay checks all
apply. No automatic retries, cancellations, credential setup or message resends
are added. See [app updates](app-updates.md) for detailed guarantees and limits.

If the UI cannot start, use the same launcher. If the app Contents are damaged,
use the `recovery_command` argument array retained in receipt inspection. The
current attempt's copied `worker/relay` supports status, diagnostics, receipt
inspection and recovery with `manage --app ORIGINAL_APP ...`; it refuses new
updates and rejects mismatched attempts or data bindings. Preserve the original
helper, previous code and database backup. Recovery restores code only, never an
older database or uncertain external submission. If the helper is missing, a
reviewed official DMG installation is still required.

Helpers copied by releases before 0.13.322 do not contain this launcher. Receipt
inspection reports `management_helper_available: false` for them; do not assume
that upgrading the app retroactively upgrades old retained helpers.

## Python/source installations

`task-relay manage discover`, `diagnose`, `skill` and `skill-install` also work from
the installed Python CLI (`python3 -m task_relay manage ...` in a source checkout).
Use the app command returned by discovery for a desktop installation. Source and
wheel installations retain their distinct `task-relay update` interface; the new
management interface does not route source updates into the signed Mac app.

## Qualification

Controlled checks exercise read-only discovery, malformed bindings, exact attempt
IDs, duplicate-install refusal, interrupted recovery, helper ownership, retained
reply admission, launcher isolation and preservation of edited skills. Release
qualification and installed checks are recorded separately. These checks do not
establish fresh-Mac privacy permissions or successful provider/message execution.
