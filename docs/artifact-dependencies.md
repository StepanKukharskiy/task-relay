# Artifact dependencies — A01

Relay can explain which registered inputs were supplied to produce an output and
preview what may be affected by replacing an exact version. This works across
production runs and file types. It reads the existing registry and frozen worker
assignments from the shared SQLite database; it creates no parallel artifact store.
Historical runs with complete frozen input evidence work without a backfill.

The orchestrator's focused production context and **Inspect stage** include
`artifact_lineage`. Each dependency names the output, input artifact ID/hash,
attempt, input path, purpose and authority. Artifact nodes include saved selection
records and their specific purposes. Inspection reports registered versions; it
does not reopen Blender or verify current file bytes.

Local read-only commands (replace the uppercase placeholders with exact registered
IDs from stage inspection):

```sh
python3 -m orchestrator artifact-lineage OUTPUT_ARTIFACT_ID
python3 -m orchestrator artifact-impact OLD_ARTIFACT_ID --replacement CANDIDATE_ARTIFACT_ID
```

The replacement argument adds candidate metadata, saved selections and a content
hash comparison. It does **not** select the candidate or declare the old selection
superseded. Equal hashes or filenames do not merge independent artifact identities.
Impact is currently available through the local CLI/runtime API; the conversation
snapshot exposes upstream lineage, not a direct impact-query tool.

For example, if a recorded render uses model A and a recorded presentation uses
that render, impact for A lists both outputs. It separately lists recorded worker
attempts that consumed either version, including launching/running/uncertain work
that has produced no artifact, and queued assignments with exact pinned inputs.
Unresolved `from_task` references become evidence only when an attempt claims and
freezes the actual version. Nothing in this query pauses, retries or rewrites work.

Every declared input is conservatively a potential dependency of every output from
its attempt. This includes guides, context and prior drafts. It is not proof that
the model read or semantically used a particular input. A prior draft may appear in
the ancestry of its revision without making that revision outdated. Files accessed
outside the registered input contract cannot be discovered from this history.

The default graph limit is 100 nodes, configurable with `--limit` from 1 to 200.
Conversation context uses 40. Graphs return at most 1,000 edges; impact lists at most
200 recorded consumer entries and 200 queued input entries. `truncated` discloses
omissions; `gaps` reports missing registry/frozen identity or hash evidence. Incomplete
results must not be described as a complete list of affected work. These are result
bounds; queries still inspect saved attempt history and are not a latency guarantee.

[A02](artifact-replacements.md) adds explicit replacement decisions scoped to a
job/purpose and persistent outdated-output tracking through a separate decision. A selection alone does not authorize downstream rebuilds.
Existing exact-selection, stage-approval and execution-budget rules continue to apply.
