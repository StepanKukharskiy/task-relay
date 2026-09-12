# Conversation drafts in Codex handoffs

Codex routes now freeze the last twelve answered orchestrator turns in the request's channel and production focus, alongside selected research and guides. Each entry contains its exact user message, answer, creation time and source ID. The receiving task reads `conversation.json` from the route's immutable input manifest. Hash verification stops submission if the copy changes. Guide choices do not recapture or silently replace this context.

This fixes a handoff that sent a guide but omitted the newer video script drafted in chat. The destination had consequently found an older script in a blocked production workspace.

Conversation drafts are unreviewed source material. They neither accept a production nor authorize historical requests to run again. The current request governs the destination's work. An explicit handoff to Codex, or a specifically named existing task, remains available from a production reply without advancing that production's frozen stages.

History is ordered by creation time, with channel isolation preserved. The same history selection is used for model context and handoff capture. This is bounded conversational continuity, not a complete project archive or automatic synchronization with all Codex tasks. Missing or ambiguous versions must be inspected or clarified. More than 200 KB of selected conversation stops routing instead of truncating a draft. Research and guide inputs keep their existing independent selection rules.
