---
name: relay-manage
description: Discover, diagnose, update or recover an installed Task Relay app using its local management interface. Use for Relay installation and maintenance; not for creating jobs, running templates or making conversation content reusable.
---

# Manage an installed Relay

Use Relay's management command, not edits to its database or signed app bundle.
The user's request supplies scope: a status question does not authorize installing
an update, starting services, sending messages or running a job. Continue an
already authorized update/recovery without asking for the same approval again;
honor the host's required access approvals.

## Find the installation

On macOS, look for the executable at:

`/Applications/Task Relay.app/Contents/Resources/resources/runtime/relay`

Also check `~/Applications/Task Relay.app` or the exact location the user supplied.
Do not search the user's whole disk. Quote paths. If several copies exist, inspect
their `manage discover` output and select the intended one before any mutation.
The bundled launcher uses Relay's own Python with bytecode writes disabled. Do
not import the signed runtime with system Python or install dependencies into it.

With an installed Python package, use `task-relay manage discover`. Its output
lists supported app commands. Source/wheel updates are separate: `task-relay
update --help`; do not use that updater to replace a Mac app.

If the app lacks the management launcher, report that it needs a newer release.
Use its existing Settings → App updates, or a reviewed official DMG installation.
Do not reconstruct our development-only bootstrap or patch an old helper.

## Inspect first

Let `RELAY` denote the exact launcher path; run it as `"$RELAY"` in a shell.

- `manage discover`: version, bindings, available app copies and skill location.
- `manage diagnose`: local configuration, signature, service health and update
  admission. No provider call or test message. Missing optional setup is not proof
  that the app cannot update.
- `manage update-status`: cached candidate and current attempt, without networking.
- `manage update-receipts`: retained attempt metadata and, when available, the
  current helper's recovery command as an argument array.

Commands return JSON with `protocol`, `ok`, `action` and `result` or `error`.
Exit 0 means the command completed, not that every diagnostic is healthy or that
an asynchronous installation finished. Exit 2 means inspect the error. Paths and
receipt metadata are private; do not upload them without authorization.

## Install an authorized update

1. `manage update-check --beta` for the current beta, or omit `--beta` for stable
   releases. This contacts public GitHub metadata. A null candidate means no newer
   compatible release was found, not that the network or app was tested end to end.
2. Inspect the candidate version, then use its exact returned ID:
   `manage update-download --candidate ID`.
3. Poll `manage update-status` at reasonable intervals until the attempt is
   `ready`. Downloading/preparing is not permission to start duplicate downloads.
4. Use the ready attempt ID: `manage update-install --attempt ID`.
5. Observe status until `complete`, then verify the installed version and run local
   diagnostics. `launching` and `installing` are in progress, not success.

The updater owns signatures, compatibility probes, backups, service shutdown,
replacement and restart. Active work can block it; never cancel work or widen
grants just to pass admission. Old held replies may remain pending. Preserve their
text, flags and uncertain receipts; never clear or resend them to enable updating.

## Recover an interrupted update

Read `update-status` and `update-receipts --attempt ID` before acting. A live worker
must finish; an interrupted or uncertain operation must not be blindly repeated.
For user-authorized recovery, use `manage update-recover --attempt ID`. An
unapproved preparation is closed without changing the installed app. An approved
update restores verified previous code only when current data is compatible; it
does not roll back the database or retry work.

If the app UI cannot open, its management launcher may still work. If its Contents
are damaged, use the retained helper command already returned by `update-receipts`
or inspect the current `attempt.json` under
`~/Library/Application Support/Task Relay App Updates/`. Match the original app,
attempt, folder and data bindings. The retained `worker/relay` accepts `manage
--app ORIGINAL_APP update-status` and `update-recover --attempt ID`. Use the saved
binding environment, never a guessed/default data folder. Its ownership checks
reject helpers from another attempt. Treat recovery command arrays as individual
arguments; never pass their contents to shell `eval`. If helper or prior code is unavailable,
preserve all recovery files and reinstall a known official DMG through the user's
authorized maintenance flow. Do not infer that reinstalling recovered the data.
Helpers copied by releases before 0.13.322 lack the management launcher;
`management_helper_available: false` does not authorize modifying those helpers.

Report observed versions, final phase, diagnostic failures and retained evidence.
Do not claim recovery, delivery or provider execution from an attempted command.
