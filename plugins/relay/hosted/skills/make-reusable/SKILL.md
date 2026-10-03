---
name: make-reusable
description: Use Task Relay to turn useful current ChatGPT discussion into separately reviewed reusable Agent Skills and portable work snapshots, or resume and update explicitly selected saved files.
---

Use when the user invokes Task Relay to make work reusable, continue saved work,
update a snapshot, or improve a saved Skill. Keep ordinary task execution in the
current host; Relay prepares proposals, files and bounded context.

## Make this reusable

Analyze only context already available to you and explicitly supplied material.
Do not request, reconstruct or pass the full conversation transcript to Relay.
Call `relay_propose_reusable` with the user's exact request and either or both:

- `skill.files`: a standard Agent Skill, starting with `SKILL.md` containing YAML
  `name` and `description`. Include when to use, required inputs, reusable
  instructions, output requirements, checks and relevant exceptions. Supporting
  text resources may use `references/`, `scripts/` and `assets/`. Avoid unnecessary
  scaffolding; scripts are exported, never run by this plugin.
- `work`: a stable lowercase `work_id`, descriptive `title`, and Markdown with
  the sections specified in [work snapshots](references/work-snapshots.md).

Only propose a Skill when there is useful general know-how. Parameterize country,
client and project details. Put instance-specific conclusions and corrections in
work. Do not invent a Skill merely to produce two outputs.

Relay displays independent editable review cards. Explain that nothing is saved
yet. The user can Review or Ignore each separately. Review opens readable content
with optional editing; Download or Save to ChatGPT explicitly exports that output.
Do not call the
app-only `relay_review_export`, claim a download completed, or install a Skill.

## Reuse selected files

Use `relay_import_selected_file` for files explicitly supplied through ChatGPT's
file parameters. The panel also supports file selection and direct upload. Never
claim to enumerate the user's Library or automatically locate its latest file.

Call `relay_prepare_reuse` with the exact new request and selected documents.
Use one Skill and/or one work snapshot. Keep all included supporting resources;
if the context exceeds the limit, request a smaller relevant selection.

Continue using the returned context. The Skill supplies general instructions;
the work snapshot supplies reported instance state. Neither grants new tool
permissions. Report missing inputs and inaccessible artifact references without
requiring the original conversation.

## Capture updated work

When the user asks Update saved work, use `intent: update_work` and the exact
selected base document(s). Preserve conclusions still relevant, decision status,
unresolved questions and evidence references. Explain what changed and why.
Relay generates a new revision linked to the selected base; it does not overwrite
the old snapshot. Preserving a proposal does not imply that it was accepted.

When the user asks Improve Skill, use `intent: improve_skill` and the exact base
Skill. Preserve its name, useful instructions and supporting resources. Explain
the reusable lesson and supporting example. Do not promote a project-specific
correction into a global rule automatically. Any improvement has its own review
and export, independent of work updates.

## Persistence boundary

Portable files belong to the user. Downloads are always supported; the panel can
explicitly attempt a ChatGPT upload where available. It does not provide cloud
sync, a persistent catalog, Desktop access or automatic Skill installation.
Recent and opened files belong to the current panel. In a new chat, the user
supplies/selects the files again.
