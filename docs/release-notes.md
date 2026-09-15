# Task Relay 0.13.26

Mac beta refresh with current workflow orchestration, app settings and package cleanup.

## What is included

- Apps and tools settings show detected installations and versions, with switches
  for supported apps, Browser use, and bundled code/document tools.
- Request-derived workflows retain selected outputs, execution reviews, recovery
  receipts and inspectable workflow folders across research, native models,
  visualization and editable presentations. Existing approval boundaries remain.
- Shared Gemini/OpenAI/Qwen workers, browser screenshots, reusable procedures and
  history-based automation suggestions. Connected accounts and optional native
  apps are still required for the operations that use them.
- Bundled document dependencies support PPTX, DOCX, XLSX and PDF operations.
- Launchers and services now call the task_relay package directly. The 56 root
  forwarding modules and their packaging entries are removed.
- Windows CI fixture corrections are included. Windows 10+ support is still in
  development; this release does not provide a qualified Windows installer.

## Install or upgrade

Download Task-Relay-0.13.26-arm64.dmg for Apple Silicon and macOS 14 or later.
Quit Task Relay, open the DMG, replace Task Relay in Applications, and reopen it.
Keep your existing data folder. If Settings shows an existing service, choose
Review service handoff and complete it; do the Messages handoff too if offered.
These steps migrate old launcher paths without deleting requests or outputs.

Apps through 0.13.25 require this one-time manual installation. The new protocol 2
update manifest blocks older updaters from silently installing incompatible service
commands. Later compatible releases support Settings → App updates → Download
update → Install and restart; enable Include beta releases for beta packages.

This beta is locally signed, without Apple Developer ID or notarization. macOS may
require Privacy & Security → Open Anyway after the first opening attempt, and
permissions may need refreshing. It is therefore marked as a prerelease.

The matching CLI source archive includes install.sh. Python wheels/source packages
are separate from the desktop app and do not update Task Relay.app.

## Validation scope

Controlled checks cover package entry points, installed wheel imports, service
migration/recovery, updater compatibility, and website downloads. Existing native
CAD/media workflows were not rerun for this packaging change. Clean-host install
qualification, Apple notarization and native Windows execution remain pending.
