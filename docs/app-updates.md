# Desktop app updates

The companion has a separate app updater in Settings → App updates. It checks
GitHub on first opening the companion when the saved check is over a day old;
Check for updates refreshes it immediately. Checks only read public release
metadata. They never download an installer or stop a service.

Choose Include beta releases to see beta packages. Download update prepares and
verifies the exact selected version while Relay remains open. Install and restart
is available only after verification. It closes the companion, stops previously
running app-owned services, installs the candidate, checks fresh service readiness,
and reopens the app. Stopped services remain stopped. Release notes open the
repository's releases page. No terminal command is part of this user flow.

**Bootstrap to 0.13.26:** apps through 0.13.25 need one manual installation.
Quit Relay, replace Task Relay in Applications with the new DMG, and reopen it.
If Settings shows an existing service, use Review service handoff to migrate it;
complete the Messages handoff too if shown. Keep the same saved data folder.
The 0.13.26 app uses package module commands instead of removed wrapper files.
Its protocol 2 manifest prevents older installers from replacing the app without
migrating those commands. Subsequent compatible protocol 2 releases can use
Install and restart.

## Release contract

A DMG, wheel, or source archive alone is not an app update. Publish these two
additional assets on the same GitHub release, using tag `vMAJOR.MINOR.PATCH`:

- `Task-Relay-VERSION-macos-ARCH.zip`: the signed app bundle, with plain files and
  directories, exact modes, and no symlinks.
- `app-update-macos-ARCH.json`: protocol 2, app version, platform, architecture,
  stable/beta channel, asset filename, byte length, SHA-256 digest, SHA-256 of the
  signing certificate, and `data_policy: unchanged`.

The release metadata must match GitHub's asset size and digest. Drafts are excluded;
betas require opt-in. The updater selects the highest compatible version among
30 recent releases and never downgrades. Versions must match the app's Info.plist.
Architecture and minimum macOS version are checked before installation.

The downloaded code must pass strict macOS code-signature verification and match
both the published certificate fingerprint and the **installed app's signing
certificate**. This prevents release metadata alone from changing the trusted
publisher. Stable packages also require Gatekeeper assessment. The beta channel
supports continuity with the already installed local signing identity; it does
not remove quarantine, disable Gatekeeper, grant privacy permissions, or claim
Apple notarization. Moving from local signing to Developer ID (or rotating the
certificate) requires a reviewed manual installation.

Maintainer packaging, from a reviewed immutable signed app:

```sh
python3 desktop/scripts/package-update.py --app '/path/to/Task Relay.app' --output /path/to/release-assets --channel beta
```

Use `--channel stable` only for a Developer ID signed/notarized package that passes
assessment. Upload both files with the corresponding DMG/checksums to the matching
release before publication. Keep the GitHub prerelease label consistent with the
manifest channel. Packaging neither publishes assets nor changes the app.

## Installation and recovery boundaries

Approval binds the prepared candidate, current app digest/root inode, exact
service definitions and loaded states, and selected data/workspace/output paths.
Changed identities, external service owners, administrator-only app locations,
legacy separate Messages storage, and active/queued work block installation.
Desktop mutations serialize with installation. After shutdown, service/setup
locks and another idle check catch work admitted during preflight.

The interpreter and helper are copied into private storage outside the app before
replacement. The helper writes intent before side effects. It preserves the app
root directory and retains previous Contents plus a database backup. Both before
download readiness and after service shutdown, the candidate reopens a database
copy; schema or row changes require a separately reviewed migration and refuse
this update. Probe execution disables bytecode writes to preserve signed bundles.

Only previously loaded services restart. Telegram's poll, scan, production and
orchestrator heartbeats and the optional Messages readiness must be fresh after
restart. A stopped service is never enabled by the updater. App process startup
is checked separately; it does not establish an end-to-end messenger delivery.

Failure before new services start attempts to restore previous code automatically.
After a restart has been attempted, uncertainty is surfaced for explicit Recover
previous app. Recovery requires idle work, unchanged owners/data bindings, a
verified prior bundle and a successful compatibility probe against current data.
It restores **code only**, never an older database or an uncertain submission.
The helper is also used for recovery, so it survives replacement. A dead worker
never restarts automatically. An unapproved prepared download can be discarded
without touching the installed app.

Receipts, helper runtimes and database backups live under the user's
Library/Application Support/Task Relay App Updates directory, separately for each
installed app path. Previous Contents are retained in a private hidden directory
beside the installed app so replacement renames stay on the same filesystem.
Each attempt retains its own receipt and phase history. They are private and are
not release assets. Automatic deletion/retention limits are not implemented yet.
If the app cannot launch after an interruption, reinstall the known previous DMG;
keep the recovery folder and existing task data for inspection.

Controlled fixtures cover metadata/channel validation, corrupt downloads, stale
approval, busy jobs, duplicate requests, interrupted replacement, retained newer
data, and stale readiness. A read-only installed-app signature check confirms
native certificate extraction. A full signed-app update/recovery on a clean Mac,
privacy-grant continuity and actual channel delivery remain deployment checks.
