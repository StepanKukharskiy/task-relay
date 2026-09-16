# Task Relay 0.13.54

Mac beta refresh for workflow continuity, presentation creation and native model recovery.

## What changed since 0.13.26

- More reliable artifact handoffs across research, native models, image work and
  presentations. Uploaded reference images retain their exact versions and reach
  capable workers; native inspectors receive only the explicitly selected model.
- Clearer blocked-stage explanations and progress cards, including provider request
  budgets, token usage and separate task sections. Saved, unexecuted plans can be
  recovered without repeating completed work or losing their failure receipts.
- Focused, independently reviewed Rhino/Blender script corrections preserve prior
  results and require a separate Start before executing changed native code.
- Reusable presentation layouts, image grids, authentic image sourcing and bounded
  correction paths improve editable PPTX assembly. Optional missing plant photos
  can be omitted when the request permits it.
- Browser capture and review improvements, explicit source contracts, workflow
  output folders and clearer result handoff.
- Website downloads now discover complete published GitHub releases, including
  betas, without a website edit for each app release. Version labels, Mac downloads,
  CLI source and checksums come from the same release.

## Install or upgrade

Download Task-Relay-0.13.54-arm64.dmg for Apple Silicon and macOS 14 or later.
Quit Task Relay, open the DMG, replace Task Relay in Applications, and reopen it.
Keep your existing data folder. If Settings offers Review service handoff, complete
it for existing Telegram and Messages services.

Compatible apps from 0.13.26 onward can use Settings → App updates → Download
update → Install and restart. Enable Include beta releases to see this package.
Earlier apps need the manual DMG installation because their service commands differ.
The matching CLI source includes install.sh; a Python wheel does not update the app.

This remains a beta: locally signed, without Apple Developer ID or notarization.
macOS may require Privacy & Security → Open Anyway and refreshed permissions.
Windows 10+ support is under development; no Windows installer is included.

## Validation scope

Targeted controlled tests accompany the individual workflow fixes. Release checks
cover updater compatibility, publication and website discovery/download behavior.
The built app matches the locally installed 0.13.54 runtime. Native geometry quality,
paid providers, clean-host installation and Windows execution were not requalified
as part of this packaging release.
