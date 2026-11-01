# Task Relay 0.13.327

## Start locally, with agent skills included

- Opening Relay starts its local worker after provider setup (or Later). Telegram is optional; an unreadable saved bot credential no longer blocks local startup.
- Stop Relay pauses automatic startup until Start is chosen again. Failed starts and incomplete handoffs require inspection; existing installations are not silently replaced.
- `relay-manage` and `relay-author` install automatically for local ChatGPT Desktop / Codex when Relay opens, without a separate download. Managed unchanged copies update with Relay; personal edits remain intact. Settings shows skill readiness. Start a new agent chat; restart the agent if needed. Local permissions still apply.
- The handoff review is clearly separate from a completed start. Previously held replies and uncertain delivery receipts remain preserved without resending.

## Codex chat without an API key

Settings → AI connection now offers **Codex · ChatGPT sign-in**. It uses the existing Codex ChatGPT login and account allowance. Relay requires its separately qualified Codex tool runtime (see `docs/codex-tool-gate.md`); installing ChatGPT Desktop alone does not supply that runtime. No API-key fallback or credential copying is used. Image/video providers keep their separate connections. This adapter is qualified with offline protocol fixtures; no live subscription request is implied.

## Canvas and animation fixes

- Open canvases refresh running nodes without reopening the job, recover from transient read errors, and preserve unsaved edits.
- Imported image cards show thumbnails and named outputs with visible exact connections. Collection inputs have distinct wire endpoints and source names.
- HyperFrames projects declare their animation runtime. Relay provisions pinned GSAP 3.15.0 or browser-native WAAPI and owns loading, initialization and dependency validation. The local GSAP wrapper loading fix is included.

## Templates

- **Support-first CA · cells to timber reel** is available in Jobs → Templates. It includes the saved CA graph, Blender script, scene checks and brief, copied into a new editable 11-node job. Use Codex, isolated Python, Blender, Gemini, HyperFrames and FFmpeg to build the two animation stages, graph-derived music, AI visualization and a 12-second vertical reel. Complete Preview before selecting Export final reel.
- Every template card now highlights its software tools, including **Cellular aggregation · from Chat**.
- Template selection does not run tools, grant paid/native execution or import previous results and approvals. The supplied CA study is not a structural qualification.

## Latest fixes

- Model nodes can explicitly choose isolated Local Python for binary outputs such as soundtracks.
- Reusing saved outputs preserves their declared media types, including historical WAV files with generic filenames.
- Running a consumer separately retains exact asset paths from its completed preparation, with hashes and producer identities checked.
- A selected text model node only derives preparation schemas from directly connected registered operations; downstream model capabilities no longer incorrectly block it.
- Local media failures retain exact execution identities. Older failed receipts reconcile only with matching stopped-execution evidence, without replay or rewriting history.
- HyperFrames author guidance clarifies inline timeline registration, stable text IDs and supplied local fonts.

## Install or upgrade

Apple Silicon Macs, macOS 14 or later: download Task-Relay-0.13.327-arm64.dmg.
Existing compatible apps can use Settings → App updates → Include beta releases → Check for updates, then download and install. The update ZIP and manifest include the desktop UI and runtime; a Python wheel alone does not update the app.

This is a locally signed beta without Apple Developer ID notarization. Provider accounts, native applications and the local media/Python runtimes require their own setup. Windows and Intel Mac installers are not included. Existing jobs, artifact versions and uncertain attempts remain in the selected data folder.

## Validation scope

Release publication requires the complete source-matched offline lifecycle gate plus focused template/import, canvas/editor, preparation, media receipt, package and updater checks. Controlled checks do not establish clean-host installation or successful provider execution on every machine. No live template execution is part of release qualification.

## Verification

The full offline lifecycle matrix passed: 463 tests across 36 groups, no skipped cases. Its retained receipt matches the merged public source. Connector/publication, update, native-host and browser/media checks also passed. The installed Mac app was verified against all 491 packaged sources, showed a healthy local worker and both bundled skills ready, and preserved every original held reply/delivery record.

These controlled checks do not claim live model quality or account availability. The existing optional Messages permission requirement remains host-specific.
