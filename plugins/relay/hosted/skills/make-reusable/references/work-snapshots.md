# Work snapshot content

Supply `work.markdown` with these level-two Markdown sections, once each:

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
Resolved remain distinguishable from Open. Keep the exact user request in the
tool argument; Relay adds identity, revision, timestamp and the prior snapshot
hash as YAML metadata in the exported `.relay.md`. A saved snapshot reports the
work's state; saving does not accept every proposed decision.

Standard Agent Skills use their existing format; these work-file metadata fields
are not a new Skill format. One serves reusable method, the other instance state.
