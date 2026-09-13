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

## One companion, optional Messages helper

The bundle includes a hidden macOS Messages helper using the existing pilot's
bundle identifier. It only runs after an explicit service handoff; opening the
companion neither starts it nor changes the separate Messages Relay installation.
Existing standalone helpers continue to show their own menu until handed off.
The same settings surface reports their state and, when paths and pairing match,
offers a reviewed handoff. The underlying channels retain distinct histories,
delivery ownership and uncertain-send records in the shared database.

Messages remains a text-only pilot requiring `imsg`, an existing paired self-chat
and its original Codex task. First-time Messages enrollment is still the separate
[pilot setup](../docs/messages-pilot.md); Telegram is the complete onboarding path.
A helper at a new location may require new Full Disk Access and Automation grants.
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

Controlled tests cover these paths. A successful mock heartbeat does not qualify
macOS permission transfer, actual source/helper handoff, provider execution or
messenger delivery. Those live gates remain open; no live service is automatically
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
and the staged runtime only for service startup. Build dependencies are not
needed by app users.

For local QA after bundling, ad hoc sign and verify the bundle with
`codesign --force --deep --sign - "src-tauri/target/release/bundle/macos/Task Relay.app"`
and `codesign --verify --deep --strict "src-tauri/target/release/bundle/macos/Task Relay.app"`.
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
