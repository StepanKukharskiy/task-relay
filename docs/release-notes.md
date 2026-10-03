# Task Relay 0.13.155

Mac beta with the current desktop workspace, universal request intake, new Codex
project tasks, Grasshopper definition authoring and the latest recovery fixes.
This release includes the merged desktop changes since 0.13.89.

## What changed

- Requests retain their outcomes, output counts, formats and validation criteria
  before routing. Large work can use bounded stages and independent reviews.
  Oversized or rejected provider replies remain available for read-only recovery.
- Create new Codex tasks in saved projects, including projects without existing
  chats. Original requests, selected files and uncertain submission receipts are
  preserved; work starts only within the requested scope.
- The desktop workspace brings jobs, workflow steps, results, review and version
  history together. Shared plans retain their delivery channel, exact Start
  decisions and recovery records. Saved work has reviewed removal and restoration.
- Create new Grasshopper definitions in Rhino 7/8 on macOS with reviewed Python.
  Native .gh and .ghx candidates are independently reopened and solved. Editing
  existing definitions and visual/geometric fidelity are outside this operation.
- Browser/computer work, reusable workflow procedures, research campaigns and
  reviewed revisions retain bounded permissions and exact artifact handoffs.
- Fix Codex attachment album continuations, migration of inert provider defaults,
  and core startup without optional YAML support. Nondefault provider settings
  still require migration review. Regression coverage is included in CI.

## Install or upgrade

For Apple Silicon Macs running macOS 14 or later, download
Task-Relay-0.13.155-arm64.dmg. Quit Task Relay, replace the app in Applications,
and reopen it. Keep the same saved data folder.

Compatible apps from 0.13.26 onward can use Settings → App updates. Enable
Include beta releases, then Check for updates → Download update → Install and
restart. Earlier apps need the manual DMG installation and any offered service
handoff. The matching CLI source includes install.sh; a wheel does not update the app.

This is a locally signed beta without Apple Developer ID or notarization. It uses
the existing signing identity for compatible in-app updates. macOS may require
Privacy & Security → Open Anyway and refreshed permissions. No Windows or Intel
Mac installer is included. Native applications and optional renderers need their
own installation, access and qualification.

## Validation scope

Controlled release validation passed 106 Python tests and 11 website/updater
JavaScript tests. Prior merged-source CI covers affected orchestration and
recovery contracts. Packaging checks
verify matching versions, bundled dependencies, exact runtime source hashes,
existing signing identity, image integrity and asset checksums. Grasshopper has
controlled and earlier fixed native-fixture qualification on Rhino 7/8; no new
installed-app Grasshopper run, paid provider job, messenger delivery, clean-host
installation or user acceptance is claimed by this release.
