# Task Relay 0.13.322

Mac beta adding documented local management and a companion agent skill. Includes the current UI, canvas, nodes, both templates and the retained-reply updater fix.

## Local management

- A bundled launcher provides JSON discovery, local diagnostics, update status/check/download/install, receipt inspection and exact-attempt recovery. No source checkout or system Python is needed for the Mac app.
- The interface uses the existing updater. Signed-package checks, database compatibility probes, backups, service ownership and no-replay safeguards remain unchanged.
- Retained helpers support recovery when the main app UI cannot open, and reject mismatched attempts or data bindings. New updates must use the installed app.
- The bundled relay-manage skill guides local coding agents through these operations. Explicit skill installation preserves edited copies and does not register an MCP server or change unrelated agent settings. A separate skill ZIP is included.
- Read the [local management guide](https://github.com/StepanKukharskiy/task-relay/blob/v0.13.322/docs/local-management.md). Local access remains subject to the user's permissions.

## Retained replies

Historical held or uncertain replies no longer block app updates. Their contents, flags, attempts and receipts remain unchanged; updates never resend them. Active work and deliverable pending replies still block installation. Older already-blocked updaters need one reviewed maintenance installation to acquire that fix.

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

Apple Silicon Macs, macOS 14 or later: download Task-Relay-0.13.322-arm64.dmg.
Existing compatible apps can use Settings → App updates → Include beta releases → Check for updates, then download and install. The update ZIP and manifest include the desktop UI and runtime; a Python wheel alone does not update the app.

This is a locally signed beta without Apple Developer ID notarization. Provider accounts, native applications and the local media/Python runtimes require their own setup. Windows and Intel Mac installers are not included. Existing jobs, artifact versions and uncertain attempts remain in the selected data folder.

## Validation scope

Release publication requires the complete source-matched offline lifecycle gate plus focused template/import, canvas/editor, preparation, media receipt, package and updater checks. Controlled checks do not establish clean-host installation or successful provider execution on every machine. No live template execution is part of release qualification.
