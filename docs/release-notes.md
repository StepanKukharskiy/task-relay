# Task Relay 0.13.60

Fixes workflow planning on a fresh installation. This focused update builds on
published 0.13.54 and retains its existing capabilities.

## What changed

- New installations can plan with an already configured and verified file worker,
  without needing a saved production policy or an earlier workflow. Relay prefers
  the conversation provider and freezes the exact configured model.
- Explicit worker choices and saved assignments remain fixed. If no worker is
  ready, Relay points to Check worker connection instead of an internal policy key.
- Planning still presents the existing approval boundary before production starts.
  Historical failed requests and responses remain saved and are not replayed.

## Install or upgrade

For Apple Silicon Macs running macOS 14 or later, download
Task-Relay-0.13.60-arm64.dmg. Quit Task Relay, replace the app in Applications,
and reopen it. Keep the same saved data folder.

Apps from 0.13.26 onward can use Settings → App updates. Enable Include beta
releases, click Check for updates, Download update, then Install and restart.
Earlier apps need the manual DMG installation and any offered service handoff.
The matching CLI source includes install.sh; a Python wheel does not update the app.

If worker setup is still needed, connect a provider and select its text model,
then use Apps and tools → Code and document tools → Worker provider → Check worker
connection. Ask Relay to continue the saved request after updating; the update
itself does not replay failed work.

This remains a locally signed beta without Apple Developer ID or notarization.
The signing identity is retained for compatible in-app updates. No Windows or
Intel Mac installer is included.

## Validation scope

Controlled first-run planning, provider/model preservation, workflow recovery,
desktop planning and updater checks use synthetic data. Packaging checks verify
bundled dependencies, matching app/runtime versions, code signatures and asset
checksums. No live provider job, Rhino modeling or clean-host installation is
claimed for this release.
