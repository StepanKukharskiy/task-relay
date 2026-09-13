# Task Relay companion (macOS Apple Silicon pilot)

Task Relay runs on your computer; everyday work stays in your messenger. The
packaged app is a small menu-bar companion for setup, connection status, settings
and local decisions. Closing the window hides it; the menu reopens it. Quit
companion exits the interface and leaves independently supervised services running.
Only one companion instance is allowed. It does not yet install itself as a login
item; the existing service definitions retain their own login behavior.

The app bundles Python and Relay. First launch opens the next required connection
step: AI provider, Telegram pairing, then service startup. A default folder is
optional and lives in settings. BotFather/token setup remains required for the
current dedicated Telegram bot. No provider generation or message is triggered
by opening the window. If reading an existing data folder times out, Grant folder
access opens a native chooser for that same saved folder; it does not rebind data.
Automatic status polling stops after a read failure until a deliberate retry. The source installer retains its separate loopback guide.

After setup the window shows connection status, Open Telegram and the available
service control. Channels contains Telegram and optional Apple Messages connection
settings and delivery controls. Settings contains AI connections, working folder,
on-demand Relay usage/storage, updates and troubleshooting.
Task browsing, conversation composition, workflow libraries and tool catalogs are
not part of the companion. Their existing runtime records and operations remain
intact. Startup does not fetch task conversations or recursively scan storage.

A focused local decision view retains exact Codex/Claude review text and the
existing one-shot approval checks. Allow requires opening the complete review;
changed or uncertain submissions are not repeated. Production selections and
normal conversation remain in their supported messenger channel.

## Channels

Open Channels from the window or menu bar. Each paired messenger has an On/Off
switch. Pause all messaging holds new requests and outgoing messages across both
channels without cancelling work already started. A send already in progress can
finish. Replies wait at their original destination; enabling another channel does
not broadcast or reroute them. Resuming releases pending replies, but never retries
an uncertain send or executes messages written while the channel was paused.
Telegram button clicks have no timestamp: the first polled batch after resume is
discarded for callbacks, so a click during that brief transition may need repeating.

Proactive updates chooses Off, Telegram or Messages for new release notices.
Changing it does not move queued notices. Off holds existing pending notices too;
task replies and requested updates are governed by the channel switches. Other
messengers appear only as future support, with no connect or enable controls.

Policy is shared in the selected Relay database, with atomic revisions and change
receipts. The app waits for current intake and delivery acknowledgements. A saved
switch cannot stop an old service that predates these controls; update and restart
that service first. Opening Channels does not restart a service, change permissions
or hand off the standalone Messages helper. Pairing records survive toggles.

## One companion, optional Messages connection

The main app executable runs the macOS Messages service in background mode.
It only runs after an explicit service handoff; opening the companion does not
start it or change an existing standalone Messages Relay installation.
Existing standalone helpers continue to show their own menu until handed off.
The same settings surface reports their state and, when paths and pairing match,
offers a reviewed handoff. The underlying channels retain distinct histories,
delivery ownership and uncertain-send records in the shared database.

Messages remains a text-only pilot requiring `imsg`, an existing paired self-chat
and its original Codex task. First-time Messages enrollment is still the separate
[pilot setup](../docs/messages-pilot.md); Telegram is the complete onboarding path.
Migrating from a separate helper may require new Full Disk Access and Automation grants.
The UI opens the system permission page; it does not grant permissions itself.

## Existing-install handoff and recovery

Use existing installation connects to its saved paths without moving data or
restarting services. A separate Review service handoff prepares exact old/new
service definitions and a runtime identity. Apply checks those identities again,
refuses in-flight work, unloads the old owner before switching, and requires a fresh
heartbeat from a newly started service. A service that was stopped stays stopped.

Failure restores the old definition and previous loaded/stopped state when that
can be established. Interrupted or uncertain transitions are never applied again.
Settings → Troubleshooting → Inspect handoff receipts exposes explicit restoration.
Unrelated service edits block replacement/restoration. Pairing, task/artifact history
and uncertain submissions stay in place; no database migration or provider replay
is part of the handoff. Receipts are retained in `companion-handoffs` under the
selected data directory. Existing service-start receipts remain available there
as `desktop-service-receipts.jsonl`.
Launchd output lives in `~/Library/Logs/Task Relay` and
`~/Library/Logs/Task Relay Messages`; it must be writable before the app starts,
independently of permissions for a data folder under Documents.

Controlled tests cover these paths. Existing-install macOS qualification has also
observed successful reviewed Telegram and Messages handoffs, fresh bundled-service
health and channel-policy acknowledgements. Refreshing the existing Full Disk
Access grant restored native status reads after a local signing change. This does
not establish permission continuity across releases. Clean-host setup, provider
execution and messenger delivery remain open; no live service is automatically
adopted after installing the companion.

Build on macOS Apple Silicon with Xcode Command Line Tools, Rust and Node.js.
Python 3 is needed to *build* the app. From this directory:

```sh
npm ci
sh scripts/build-runtime.sh
npm run build
```

`build-runtime.sh` pins the macOS arm64 `python-build-standalone` CPython 3.14.7
archive and verifies its SHA-256 before staging release sources. The generated
runtime is ignored by Git. `npm run build` produces a `.app` under
`src-tauri/target/release/bundle/macos/`. `npm run dev` uses the checkout's Python
and the staged runtime only for service startup. The bundled interpreter includes
the hash-pinned Pillow wheel from `scripts/requirements-runtime.txt` for registered
image validation/conversion. Build dependencies are not
needed by app users.

Initialize a stable local build identity once with
`python3 scripts/sign-app.py --init-local` from `desktop/`, then run `npm run build`.
The dedicated user keychain preserves the private key across builds and joins the
existing keychain search list. No certificate trust roots or privacy grants are
changed. Builds fail if the saved identity is missing; they never fall back to ad
hoc signing. `TASK_RELAY_SIGNING_IDENTITY` can select a separately managed signing
identity. Local self-signing is not Apple Developer ID signing or notarization.

A signed/notarized public package, clean-host
install and an authorized provider task plus Telegram reply remain release gates.
The source installer remains the qualified installation path. Linux and Windows
desktop packages require their native host adapters and builds.

For a future public macOS desktop release, the intended path is to download a
signed and notarized disk image from GitHub Releases, drag Task Relay to
Applications, and open it. The app bundles Python and Relay; its compact setup
guides provider and bot configuration without a terminal. No desktop disk image
is published yet. Until that release path passes the gates above, use the source
installer in the main README.

## Packaged release implementation order

The source updater is explicitly unavailable for the app bundle and for a source
controller targeting the companion-owned installation. Source release metadata
can still be checked; it is not a verified app update. Bundled startup does not
follow a previous source updater's runtime selection. These boundaries are covered
by `python3 -m unittest tests.test_packaged_update_boundary`.

The remaining release work has these reviewable outputs, in order:

1. Build a version-consistent candidate from reviewed source with pinned runtime
   inputs. Sign nested executable code and the final bundle with Developer ID,
   notarize the distribution and retain verification evidence. Developer ID and
   notarization access must exist before this can produce a public package.
2. Define separate app-release metadata with exact version, architecture, size,
   digest and expected signing identity. Verify the downloaded candidate before
   presenting it for an explicit update; wheel metadata is insufficient.
3. Implement a replacement helper outside the bundle being replaced. Bind approval
   to the exact installed and candidate identities, service definitions and data
   paths. Check both channels for unfinished work, retain stopped-service state,
   and record replacement intent before stopping owners or replacing code.
4. Require fresh readiness from each previously running service before completing
   the update. Bind any schema change to an explicit migration plan. Failed starts
   restore compatible prior code without discarding newer records; interrupted
   replacement exposes a recovery receipt and never blindly repeats the update.
5. Qualify installation, update, interrupted recovery and rollback on a clean
   supported Mac, followed by an authorized text task, exact decision and actual
   Telegram delivery. Optional Messages permissions retain their separate gate.

Direct menu-bar interaction and clean-host setup remain open local qualification
items. Installed-runtime checks with isolated data establish only that fresh status
does not create task records and that saved setup survives bridge-process restart.

## Downloadable Mac beta and CLI alternative

The website's primary download is `Task-Relay-0.12.1-beta.1-arm64.dmg`, for Apple
Silicon and macOS 14+. Drag Task Relay into Applications and eject the disk before
opening the app. Python and the Relay runtime are included. The beta uses ad hoc
signing, not Developer ID or notarization; macOS may require its per-app Open Anyway
flow. Never disable Gatekeeper. Managed hosts may prohibit this beta, and updates
may require refreshing existing permission grants. A signed public release remains
an open gate.

First-run setup presents one active form at a time: AI access, a dedicated Telegram
bot, explicit service startup, then Telegram pairing. Saved state determines the
next step after interruption. Saving a form never automatically starts a service
or a provider task. Existing services are offered for reuse/review instead of being
replaced. Paired users return to the normal companion. A first actual instruction
and reply remain the user's end-to-end check; pairing alone does not verify AI work.
First-time Messages enrollment retains its separate pilot procedure.

The secondary website route downloads the same beta's source and runs
`sh install.sh --terminal-setup` with Python 3.11+. CLI commands honor the data
binding explicitly selected in the companion; explicit path overrides still win.
Neither route silently replaces an existing login service.

Build the reviewed runtime and app using the stable signing setup above. Package
it using `python3 desktop/scripts/package-beta.py --app /absolute/Task\ Relay.app
--output /absolute/Task-Relay-0.13.0-beta.1-arm64.dmg` (on one line). The packager
refuses to replace an existing artifact, creates the Applications shortcut and
installation notes, verifies the disk image, and emits its SHA-256 checksum.
Do not package an installed personal app or local configuration. Download files
are generated artifacts, excluded from Git; the website serves only named files.
## Messages ownership

Messages runs through `Task Relay.app/Contents/MacOS/task-relay-desktop
--messages-service`, the same executable and signed identity as the app window.
No nested Messages Relay.app is shipped. **Permissions…** reveals Task Relay.app
and opens Full Disk Access settings. A one-time grant refresh may be needed when
moving from the previous ad hoc identity. Relay cannot grant this permission.
Pairing and history remain in the shared database.

Local installation maintenance uses `scripts/install-local.py`: prepare a fixed
candidate/service manifest, then apply that manifest. It stops owned services only
when work is idle, backs up SQLite, and preserves the installed app root directory.
Rollback copies are verified ZIPs outside Applications; no runnable backup app is
left behind. A failure before services restart restores the previous Contents and
service definitions. Once new dispatch is possible, recovery requires inspection
and never restores an old database automatically. This is a local maintenance
path; the signed/notarized public updater and clean-host qualification remain open.

### Local identity qualification (2026-09-13)

Controlled checks: 51 service, handoff, app-replacement, archive, companion and
Messages tests passed; three signing tests and three local-installer tests passed.
The native Messages service path test passed. Two local builds signed with the
same certificate have identical designated requirements; the newer build verifies
against the older requirement. The installed bundle passes strict signature checks
and contains no nested Messages app.

Deployed checks: app replacement preserved the installed directory inode; the
Messages service definition uses the main app executable. The initial startup
health deadline expired and its failure receipt was retained. Later inspection
confirmed fresh Telegram poll/scan/production/orchestrator heartbeats and a running
Messages watcher. Both obsolete runnable backup apps were retired only after ZIP
round-trip and signature checks. No test message was sent and phone delivery was
not qualified. This does not establish permission continuity on a future update
or clean host. Private installation receipts and test logs remain under outputs.

## 0.13.0 release candidate

The current source and app versions are 0.13.0. Build a fresh immutable beta DMG
from the reviewed source using the command above. Existing website downloads
remain 0.12.1-beta.1 until new assets are explicitly published; a source PR does
not update their bytes. Recommend prerelease distribution while notarization,
clean-host setup and live media-provider qualification remain open.
