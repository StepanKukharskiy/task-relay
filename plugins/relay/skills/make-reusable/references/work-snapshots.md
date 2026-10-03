# Work snapshot content

Create the work snapshot body with these level-two Markdown sections, once each:

```markdown
## Objective
The outcome being pursued.

## Current conclusions
- What is currently known, with evidence references where available.

## Decisions and proposals
- [Proposal] A suggested decision awaiting the user's choice.
- [Decided] A decision the user explicitly made, with its basis.

## Evidence
- Source label, reference/link, relevant quotation where supplied, and limitations.

## Artifact references
- Artifact label, reference/link, version if known, and access limitations.

## Unresolved questions
- [Open] A question still needing an answer.
- [Resolved] A previously open question and its answer/basis, when retaining it helps.

## Next actions
- A specific next action supported by the retained work.
```

Use `None recorded.` where no information is supplied. Do not fabricate evidence,
completed actions, access to referenced files, or acceptance. Questions marked
Resolved remain distinguishable from Open. Keep the exact capture request in YAML metadata. Preserve these fields for
compatibility with Task Relay's portable work format:

- format: task-relay-work
- format_version: 1
- work_id: stable lowercase letters/digits/hyphens, at most 64 characters
- title: human-readable work title
- revision: 1 initially, incremented for a reviewed update
- request: exact capture/update request, safely YAML-quoted
- prepared_at: actual UTC creation time from an available host clock
- based_on_sha256: YAML `null` for the initial revision (not an empty string), then SHA-256 of the exact
  selected base snapshot bytes for an update

Use native file/code capabilities to obtain the timestamp and hash when available.
Serialize metadata with a YAML library when available so the request's line breaks
and literal characters survive a read/write round trip.
Never invent a hash or claim byte identity from a paraphrase. If the exact selected
base bytes are unavailable, ask for that file before producing a linked update.
Name the export work-id-r001.relay.md, incrementing the revision suffix. Preserve
the original file. A snapshot reports work state; exporting does not accept every
proposed decision. These work metadata fields are not a proprietary Skill format.
