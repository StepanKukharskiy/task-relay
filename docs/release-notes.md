# Task Relay 0.13.321

Mac beta fixing updates blocked by historical, already-held replies. Includes the latest UI, canvas, nodes and both bundled templates.

## Updater fix

- Historical replies with existing delivery holds or uncertain-delivery receipts no longer block installation and recovery.
- Original reply contents, sent flags, attempts and receipts are preserved. Updating does not resend them or mark them delivered.
- Active sends, deliverable pending replies and running/queued work still block installation. The updater checks again after shutdown.
- A blocked older updater needs a one-time maintenance installation to acquire this fix; do not clear reply history or retry uncertain messages to enable an upgrade.

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

Apple Silicon Macs, macOS 14 or later: download Task-Relay-0.13.321-arm64.dmg.
Existing compatible apps can use Settings → App updates → Include beta releases → Check for updates, then download and install. The update ZIP and manifest include the desktop UI and runtime; a Python wheel alone does not update the app.

This is a locally signed beta without Apple Developer ID notarization. Provider accounts, native applications and the local media/Python runtimes require their own setup. Windows and Intel Mac installers are not included. Existing jobs, artifact versions and uncertain attempts remain in the selected data folder.

## Validation scope

Release publication requires the complete source-matched offline lifecycle gate plus focused template/import, canvas/editor, preparation, media receipt, package and updater checks. Controlled checks do not establish clean-host installation or successful provider execution on every machine. No live template execution is part of release qualification.
