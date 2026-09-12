# Continuity experiment: scoped working state

This local experiment adds `state-update` and `context-export` to the existing learning
CLI. It uses the same evidence/usage infrastructure and fixes the model to
`gemini-3.7-flash`. Each update is an immutable **model proposal**, not a guide amendment,
production action, or independent approval. This remains an experimental capability; model proposals require review.

## State update

Import the selected export as before. Provide the known jobs and their workflows once:

```json
{"R037": "reel", "R038": "carousel"}
```

```sh
python3 -m learning import --dataset continuity --workflow content --kind conversation /absolute/history.md
python3 -m learning state-update --project my-project --dataset continuity --jobs /absolute/jobs.json
```

Use the returned state ID explicitly for the next update:

```sh
python3 -m learning import --dataset continuity --workflow content --kind conversation /absolute/history.md
python3 -m learning state-update --project my-project --dataset continuity --previous state:ID
python3 -m learning show continuity_states state:ID
```

The operation sends the previous entries and their original supporting messages plus
new messages to the fixed model. It proposes additions with:

- A statement, exact supporting quotation and immutable event/source reference.
- Project, job and workflow applicability. An empty jobs list means project-wide;
  an empty workflows list means all workflows within that project.
- `explicit_instruction`, `recorded_result`, `inferred_preference`, or
  `unresolved_question` status, with uncertainty kept separately.
- An `adds`, `overrides`, or `conflicts` relationship to earlier entries.

Old entries are retained. A job-specific override suppresses its target only inside the
override's narrower/equal scope; the original remains applicable elsewhere. A conflict
does not silently choose a winner. The model proposes those relationships; deterministic
checks verify references and permitted scope relationships, not their full semantic truth.

Unknown jobs are rejected. Additional known jobs can be supplied with another `--jobs`
file; an existing job's workflow cannot change silently. A previous state from another
project is rejected. There is no hidden mutable project head: selecting `--previous`
chooses the branch to continue, and every earlier state remains available.

Unchanged messages are deduplicated across revisions using message identity, timestamp,
role and content. When the export supplies a Thread ID, dated copies of the same history
can be recognized across filenames; otherwise the source path identifies the history.
Changed message text is new evidence, while the original source revision remains stored.
Reimporting an unchanged history after an update requires no model call.

Every new message needs an explicit coverage disposition, including quoted material or
messages that add no state. Exact supporting quotes must resolve. Explicit instructions
need direct authored user evidence; Markdown blockquotes, fenced examples and assistant
reports cannot provide that authority. Unmarked quotations and semantic scope still need
model interpretation and may require review.

Each update has one call, a default 120,000-character input cap and an 8,192-token output
cap. Oversized or invalid results remain incomplete; earlier state is preserved, and no
automatic correction/retry is made. Requests, raw responses, failures and provider usage
remain in `analysis_runs`, `internal_jobs` and the existing `api_steps` rows. Importing,
exporting and inspecting state do not themselves call the model.

## Guide versions and portable context

Guide applicability is explicitly selected by the operator. Import a guide, then supply
the returned source ID and its scope in a bindings JSON file:

```json
[
  {
    "source_id": "source:IMPORTED_ID",
    "scope": {"project": "my-project", "jobs": [], "workflows": ["reel"]}
  }
]
```

Pass `--guides /absolute/bindings.json` with a state update. Omitting it retains the
previous bindings; supplying it replaces the selected set in the new state version.
Earlier versions keep their old bindings. A changed live guide cannot silently replace
the bytes referenced by an existing context.

```sh
python3 -m learning context-export state:ID --job R038 --workflow carousel --directory /absolute/new-context-folder
```

The new directory contains:

- `TASK_CONTEXT.md`: applicable requirements/decisions, separately labeled inferred
  preferences and reported results, unresolved questions/conflicts, selected guide
  versions, source quotations, and explicitly inactive superseded entries.
- `evidence/`: original cited source snapshots for portable links.
- `manifest.json`: exact state/context hashes, selected entries, and source hashes.

The single Markdown file contains supporting excerpts and full selected guide text, so
it can be attached alone. Keeping the evidence directory alongside it also provides full
source verification. Source paths are relative to the bundle; no access to Task Relay's
private database is needed. A new job ID receives relevant project-wide entries, not
another job's requirements. The file instructs the receiving agent to use the current
request and applicable established preferences before asking again.

Export is deterministic and makes no model call. It preserves model-identified conflicts
and scope; it does not independently prove the state is correct or interpret every guide
against every requirement. Existing directories are rejected to preserve previous exports.

## Inspect, correct, and record effort

```sh
python3 -m learning state-review state:ID --note "Checked the job scopes and overrides" --metrics /absolute/metrics.json
```

Metrics may include `review_minutes`, `correction_minutes`, `repeated_reminders`,
`missed_requirements`, `inappropriate_carryover`, `revisions`, and `production_usage`.
Omit unmeasured values; zero is an observation, not a default. Provider usage is already
stored automatically for state maintenance. Optional human-time estimates are never
derived from chat timestamps.

For a state error, create a correction JSON object with `withdraw` (old entry IDs) and/or
`entries` (replacement entries using the same schema shown in the saved model request).

```sh
python3 -m learning state-correct state:ID --correction /absolute/correction.json --note "Scope was too broad" --metrics /absolute/metrics.json
```

This produces a new `reviewer_corrected` state, retaining the original entries and
recording the correction. It does not rewrite the model's first output. Replacements
still need valid supporting citations and scopes. Continue from the corrected state ID
if it is the version selected for use.

## Experiment boundary

The current test uses deliberately explicit synthetic examples of known failure modes.
It establishes basic functioning, not a reduction in production burden. It includes
operator-supplied job identities and guide bindings; it does not autonomously discover
all applicable project structure. State size is bounded by a hard input cap; no scalable
retrieval, live collection, automatic project-head management, or production execution
has been added.

The next experiment should use new work with equal guides, inputs, available evidence,
production model and tools. Prepare an ordinary model-generated handoff for baseline and
maintained context for treatment, counting preparation usage and review on both sides.
Save both first outputs before correction. Review repeated reminders, missed requirements,
inappropriate carryover, revisions, final quality, model usage and state-checking effort.
The production comparison has not been run.
