# Task Relay 0.13.89

Mac beta with typed workflow planning, stronger recovery, native model tools and
provider-independent local reel production. Includes the first-run planning fix
from 0.13.60 and accumulated updates since 0.13.54.

## What changed

- Workflow builders compile selected artifacts, operation contracts and review
  reports into exact versioned handoffs. Attachments, image albums, source geometry
  and completed-stage selections retain their identity across planning and recovery.
- Confirmed failures have clearer, bounded continuation and correction paths.
  Started plans return to their saved execution. Uncertain submissions are not
  replayed, and changed scripts still require review, selection and a separate Start.
- Shared API workers improve long-text delivery, source exposure and Gemini tool
  reporting. Placeholder-only output cannot pass local delivery checks; human
  selection and independent review remain required.
- Rhino and Blender recovery preserve failed evidence and selected source models.
  Standalone 3DM creation uses the bundled rhino3dm library, including reviewed
  Python scripts and explicit Rhino archive versions. Library verification does
  not imply native Rhino verification. The SketchUp adapter requires local host
  qualification before use.
- Image sourcing supports browser discovery and bounded fallback while retaining
  source provenance and explicit generated-image restrictions.
- Ordinary reel requests can use a separately installed, qualified local
  HyperFrames runtime. Providers author editable projects, preview them for review
  and user selection, then render the exact selected project to MP4. Legacy scene
  composition remains supported; optional renderer installation is not automatic.

## Install or upgrade

For Apple Silicon Macs running macOS 14 or later, download
Task-Relay-0.13.89-arm64.dmg. Quit Task Relay, replace the app in Applications,
and reopen it. Keep the same saved data folder.

Apps from 0.13.26 onward can use Settings → App updates. Enable Include beta
releases, then Check for updates → Download update → Install and restart.
Earlier apps need the manual DMG installation and any offered service handoff.
The matching CLI source includes install.sh; a Python wheel does not update the app.

This remains a locally signed beta without Apple Developer ID or notarization.
The signing identity is retained for compatible in-app updates. macOS may require
Privacy & Security → Open Anyway and refreshed permissions. No Windows or Intel
Mac installer is included. Native applications and optional renderers need their
own installation and qualification.

## Validation scope

Release validation covers affected planning, recovery, operation and provider
contracts with controlled fixtures, plus packaging, updater and website behavior.
Package checks verify source identity, matching versions, bundled dependencies,
code signatures and asset checksums. No live provider job, user-content rendering,
messenger delivery or clean-host installation is claimed for this release.
