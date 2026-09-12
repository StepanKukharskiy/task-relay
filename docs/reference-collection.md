# Automatic production reference collection

In `/orchestrator` conversation mode, ask to use a previous production and name its project, for example: “Collect the files and guides from my drawings video in Content for planning another film.” The model chooses an existing project path. A background collector finds production folders with a brief plus composition (or a HyperFrames project marker). It selects a sole match or an explicitly named unique version; otherwise Telegram shows source/version buttons. Choosing a source preserves the complete original request and queues collection. Collection never starts agents or renders.

The collector registers the selected composition, assets, scripts, records and outputs, shared ancestor instructions and creator guides, selected voice/content plans and owned examples, and explicit static local references. HyperFrames sub-composition asset paths resolve from the composition root. It copies files into the existing immutable artifact registry and reuses unchanged, hash-verified copies. The manifest contains source paths, registered-copy paths, artifact IDs, hashes, purposes, workspace destinations, the original request and runtime-compatible `inputs` entries. The summary and manifest are delivered as Telegram documents; replying keeps reference-pack context.

A ready pack can be attached by the orchestrator to an existing Codex task or to a linked-workflow plan/run proposal. The handoff carries the manifest path and expected hash, with instructions to use registered copies and inspect unresolved inputs. Original request text remains intact. Registered packs do not modify existing runtime plans, overwrite prior production sources, or authorize a later production stage.

## Discovery boundaries

- Existing specific project folders only; no home-directory-wide search or arbitrary model-provided path.
- Brief/composition markers, visible source files and static links. Runtime imports, dynamically generated filenames, external websites, unmentioned attachments outside the project and other production systems can require additional input. A static unresolved pointer may be an example in documentation rather than a required asset; its source context is retained for planner review.
- At most 30 candidate productions, 30,000 scanned entries and 12 directory levels. Oversized discovery stops with a request to narrow the project.
- At most 275 source files, 2 GB total, and 500 MB per file; one additional registered request file. Packs exceeding a limit fail visibly rather than silently omitting necessary source files.
- Private, hidden, credential, dependency, scratch and redundant QA-capture paths are excluded. Symlinks/hard links are not copied. Explicit references outside the selected project are reported, not followed. Exclusions and unresolved links appear in the manifest.
- Source choices expire after 30 minutes and require complete card delivery and the paired user. Changed briefs fail collection. Interrupted copies are not automatically retried; completed registered files are retained and can be reused in a fresh collection.

`ready` means the selected files were registered; it does not prove the production is self-contained, fact-checked or creatively accepted. New pipeline generation is O03, not part of collection.
