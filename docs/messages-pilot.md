# Messages Relay

The [Task Relay companion](../desktop/README.md) now provides one settings surface
for Telegram and the optional Messages connection. Existing Messages Relay.app
installations remain active until an explicit reviewed handoff to the bundled
hidden helper. Pairing/history stay in place; permissions at the new helper
location and live handoff still need qualification. First-time enrollment retains
the pilot setup below. This does not add attachments or channel parity.

## Orchestrator as the default

Send ordinary text in the paired self-chat to give an instruction to the shared Task Relay orchestrator. `/orchestrator YOUR INSTRUCTION` is an explicit equivalent. It can route instructions to existing tasks, collect references, and control registered production stages using the same saved project state as the Telegram interface. Creating arbitrary new workflows from a message is not implemented yet.

For example: `Ask the Codex task working on my video to check the source files and report what is missing.` If more than one task matches, the reply offers numbered choices. Send `/choose CODE NUMBER` using the code printed with that reply. Choices retain the original expiry, delivery, and workflow revision checks. Status choices read fresh production state without calling a model.

Ordinary text always goes to the orchestrator. `/codex` and `/gemini` still address those providers directly, and `/ask` continues whichever of those two you selected. `/status` reports orchestrator readiness too. Keep both the Messages login service and the main Task Relay service running; Telegram connectivity is not required for the independent orchestrator worker.

Messages conversation history is separate from Telegram history. Jobs, registered productions, and task state are shared. Results return to their originating interface; a task or production controlled from Messages sends subsequent progress there until it is controlled from Telegram again. The pilot and shared task watcher deduplicate results for the pilot's original Codex task. Bot headers and inbound self-chat echoes are ignored, so generated replies do not start new requests.

This interface accepts and sends text only. Generated files are reported with their local Mac paths. Attachments, macOS/Codex approvals, and Codex input questions still require the Mac. All Relay records live in `private/state.sqlite`, including pairing, outgoing Messages parts, provider history, orchestration and delivery receipts. Messages uses namespaced tables and explicit channel ownership in that shared database.

## Background service and Gemini

Messages Relay now supports `/gemini YOUR INSTRUCTION` and `/codex YOUR INSTRUCTION`. Either command also selects that provider, so `/ask YOUR INSTRUCTION` continues it. Use `/gemini` or `/codex` alone to switch without starting work. `/new gemini` starts a fresh Gemini conversation; `/stop gemini` requests cancellation; `/status` shows both providers.

The Gemini adapter reuses the API key and enabled/default model settings in the existing Task Relay connection. Messages keeps its own Gemini conversation identity in the shared database; it does not import Telegram conversations. The main Relay service executes both channels’ jobs through one Gemini worker. The Messages service only handles the chat interface and delivery. Text runs use the same existing read-only project file tools, scoped to this Codex task's project folder. Image, video, speech, attachment intake, and phone approvals are not wired to Messages in this version. Each result carries its source provider label, even if you switch while it is running.

`Messages Relay.app` is a small menu-bar app (the **scribble logo** menu) supervised by the user's login LaunchAgent `com.personal.taskrelay.messages`. It starts after login, runs without Terminal, and restarts its worker after failure. Keep this project folder in place and the Mac awake and online. Codex tasks need Codex open. Gemini needs its saved API connection and the main Relay service running.

The app needs its own **Full Disk Access** permission, because Terminal's permission does not necessarily apply to a login service. Add **Messages Relay.app** from your home **Applications** folder in System Settings → Privacy & Security → Full Disk Access. Allow Messages automation if macOS prompts. The app menu provides a shortcut to the settings and Start / Restart. **Pause** stops work until you resume it; pairing and provider history stay saved. Do not also run the foreground pilot; both use the same exclusive lock.

Service maintenance:

```sh
python3 -m task_relay.messages_service build
python3 -m task_relay.messages_service install
python3 -m task_relay.messages_service status
python3 -m task_relay.messages_service restart
python3 -m task_relay.messages_service stop
```

`install` copies the app to `~/Applications/Messages Relay.app`, writes this service's plist to `~/Library/LaunchAgents`, and enables/starts it. The app and its logs must be outside Documents so launchd can start the app before it has permission to access protected folders. `stop` disables and unloads this service while preserving its pairing and history. **Stop Messages Service.command** is the double-click equivalent. Health is recorded in `private/messages-pilot/health.json`; logs in `~/Library/Logs/Messages Relay` omit prompts and API keys. The app is locally ad-hoc signed; the launcher build is reused when unchanged to avoid unnecessary macOS permission identity changes.

Checks: 25 tests cover the pilot, the observed Tahoe self-chat format, Gemini/Codex selection, provider-specific result delivery, conversation history, duplicate inputs, restart recovery, cancellation, and login-service configuration. Gemini end-to-end tests use a mocked provider response; live service and API checks are recorded separately below.

The foreground instructions below remain available for troubleshooting, with `/ask` now using the selected provider.

The direct `/codex` command controls the original Codex task from an iPhone self-chat using the same Apple Account as the Mac. First setup requires an explicit `--task TASK_UUID`; later starts reuse the saved task. The orchestrator can route to other existing tasks. Pilot state is stored in the shared database; `private/messages-pilot/` holds its lock, health and retained historical files.

## Start

1. Messages must be signed in on the Mac. Enable **Terminal** in **System Settings → Privacy & Security → Full Disk Access**. Quit Terminal completely and reopen it after changing permission.
2. Double-click **Start Messages Pilot.command** in this project's folder.
3. On the iPhone, send the displayed `/pair CODE` to your **own** iMessage phone number or Apple Account email. Send it after the launcher displays the code. Use blue iMessage, not SMS, and a direct self-conversation, not a group.
4. Allow Terminal to control Messages when macOS asks. The pilot should reply with its task name and commands.
5. Send `/ping`, then `/ask Reply with: Messages pilot works`. The configured Codex task must be idle. Keep Codex open, the Terminal window running, and the Mac awake.

Commands are listed above. Ordinary text goes to the orchestrator. `/allow`, `/use`, attachments, new Codex tasks, phone approvals, and input-question responses are not implemented. Answer permissions and questions in Codex on the Mac. `/status` reports task activity, not individual approval details. Current-task final replies are forwarded after pairing, including turns started on the desktop.

Ctrl+C in the pilot Terminal stops the bridge. Restart the same launcher to retain pairing. Commands sent while it was offline are deliberately not replayed: wait for the launcher to report ready, then send a new command.

## Permissions and scope

The installed `imsg` CLI reads the local Messages database and sends using Messages AppleScript automation. macOS grants Full Disk Access to the launcher, which is broader than the pilot's one-conversation filter. Before pairing, the watcher sees new message events but persists only the matching pairing message ID and the selected conversation identity. After pairing, the pilot processes only that direct iMessage conversation and only messages marked as sent by the local Apple Account. Subsequent launches restrict the watcher to that chat. It never stores unrelated conversation content. Each response part starts with a Codex header, preventing command echo loops. Pairing expires after one hour.

Only the standard CLI watch/send features are used; no injected Messages bridge or SIP changes are needed. The Mac still needs its usual connectivity to Codex. `imsg` reporting success means Messages accepted the send; actual phone delivery is an acceptance check.

## Recovery

Message GUIDs deduplicate commands. Submissions are committed before sending to Codex. An ambiguous submission is never retried, and blocks new instructions until a completion arrives or you inspect Codex and run:

```sh
python3 -m task_relay.messages_pilot --clear-pending
```

Outgoing parts are committed before sending. A timeout or crash leaves an uncertain delivery and holds the remaining parts of that reply, so an accepted message is never blindly resent. After restart, the watcher accepts fresh messages and independent replies can be delivered. Held replies stay unacknowledged, including their choice cards, and cannot fill the export batch and starve newer responses. The app's Channels status shows the warning while the service is connected; the launcher prints the affected IDs. After checking the conversation, acknowledge/skip that delivery with:

```sh
python3 -m task_relay.messages_pilot --ack-delivery 'THE_PRINTED_ID'
```

This skips the uncertain part, whether or not it arrived. It never sends it again. If you need the missing result, read it in Codex or send a new explicit request after recovery. Stop any running pilot before either recovery command. Use the same Python interpreter as the launcher if `python3` is not installed in your Terminal path.

Only one process can hold the pilot lock. A Relay installation has one Messages pairing. `--state` does not create a second pairing or database; a separate installation must use its own `TASK_RELAY_DATA_DIR`.

## Consolidating older installations

Stop both services before running the operator migration:

```sh
task-relay storage consolidate-messages
```

It holds both service locks, checks for in-flight work and makes integrity-checked SQLite backups under the data directory’s `backups/` folder. It imports the older Messages transport and provider databases in one transaction, preserving exact prompts, conversation IDs, file paths, pending/uncertain deliveries and deduplication records. Existing Telegram preferences remain unchanged. Conflicting record identities or unknown populated tables abort the import.

A generated task emoji may need reassignment to avoid an existing emoji; the receipt records both values. A conflicting custom emoji requires an explicit resolution. Usage identities move with their records so future refreshes do not double-count the same calls.

After commit, the original databases move into the backup folder. An already-migrated legacy orchestration database is archived there too. Restart both services after the command succeeds. Startup refuses unmigrated Messages databases. Rerunning the command after interrupted archival resumes retirement without importing or dispatching work again.

The committed `storage_migrations` receipt records the input snapshots, row counts and any remapping. Backups are recovery copies, never runtime inputs. File artifacts and model response/history files stay at their original paths. To roll back before resuming work, stop both services, restore all database snapshots listed in that receipt (including the main database) to their original paths, and restore the matching old application version together. Never restore a single stale database after new work has started; that would discard newer records or risk replay. Migration itself sends no messages and invokes no providers.
