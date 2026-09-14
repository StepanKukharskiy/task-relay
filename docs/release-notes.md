# Task Relay 0.13.1

Beta candidate: this source change does not publish a GitHub release.

## App updates

- Settings → App updates checks for new desktop releases and optionally includes
  betas. Download update verifies the package; Install and restart becomes
  available after verification. A visible update notice opens the controls.
- App packages are separate from source releases. ZIP/manifest assets must match
  GitHub's published byte length and checksum and the installed app's signing
  certificate. Stable packages additionally require Gatekeeper assessment.
- Installation preserves the app root and saved data, checks for active work,
  stops/restarts only the previously running owned services, and verifies fresh
  readiness. An independent helper retains previous code and per-attempt receipts.
  Interrupted updates expose explicit recovery without resubmitting work or
  restoring an older database.

## Installation

Published 0.13.0 and earlier apps need one manual installation of this build to
receive the updater. Subsequent compatible releases can be installed in-app.
The Mac beta requires Apple Silicon and macOS 14+. It uses local signing;
Developer ID signing and Apple notarization remain unavailable with a free
Apple developer account. macOS may require Open Anyway and refreshed permissions.

Controlled checks cover metadata, archive validation, data compatibility, real
schema idle checks, exact approval, interruption and recovery. They do not replace
clean-host installation/update qualification or actual messenger delivery.
Schema-changing updates, signing-certificate changes, unsupported owners and
administrator-only app locations require a separate reviewed/manual update.

See [app updates](app-updates.md) for the user flow, release contract, packaging
and recovery limits. Existing source update isolation remains unchanged.
