# Workflow observer: local pilot

The local CLI implements evidence import, bounded Gemini analysis, proposal review and
revision, isolated guide application and rollback, and subsequent-job evaluation.
The first real import and discovery runs are recorded. A prospective improvement cycle
has **not** been completed: no real proposal has been accepted or used for production.

The separate [continuity experiment](continuity-experiment.md) now adds scoped state
maintenance and portable `TASK_CONTEXT.md` export, with a recorded known-case test.

Run commands from the Task Relay project folder. The default store is
`private/learning/state.sqlite`; `--db PATH` before the command selects another store.
Importing and reviewing are local. `analyze` and relevant `evaluate` calls send selected
evidence to the Gemini connection already configured through Task Relay.

## Import selected evidence

```sh
python3 -m learning import --dataset content --workflow content --kind conversation /absolute/history.md
python3 -m learning import --dataset content --workflow content --kind guide /absolute/CONTENT_PRODUCTION_GUIDE.md /absolute/REEL_PRODUCTION_GUIDE.md
python3 -m learning import --dataset solver --workflow solver --kind ledger /absolute/SOLVER_ATTEMPTS.md
python3 -m learning status --dataset content
```

Sources retain original bytes, SHA-256, path, type, and import time. Events retain roles,
timestamps where supplied, source line spans, message/attempt IDs, and artifact references.
The supported conversation format is the supplied `# Chronological Transcript` export
with numbered `### 0001 · User` / `Agent (channel)` envelopes and UTC timestamps.
Malformed envelopes, nested unfenced envelopes, and mismatched declared counts fail
explicitly. Ledger entries use `- **H01 — Title:** summary` syntax; no dates or human
interventions are invented for them.

Identical bytes at the same source path and type reuse records. Changed bytes preserve
both revisions. The last explicitly imported revision is selected for that dataset;
earlier evidence remains retrievable. Files linked by histories are never fetched
automatically. Artifact links refer to current files, not verified historical versions.
Approval-index and decision-marker annotations never authorize a change.

## Analyze and inspect

```sh
python3 -m learning analyze --dataset content --backend gemini \
  --max-calls 32 --max-input-chars 2000000 --context-chars 400000 \
  --max-output-tokens 8192
python3 -m learning status --run-id analysis:ID
python3 -m learning show events event:ID
python3 -m learning show sources source:ID
```

Stage A scans the entire selected history in bounded neighboring batches. Oversized
messages carry exact character offsets; overlap is recorded and is not a new correction
episode. Stage B compares candidates with the selected guide snapshots and retrieves
original cited messages. Workflows are processed separately. Large synthesis input fails
incomplete instead of being truncated.

Every request, raw response, model, generation settings, status and provider usage is
retained in `internal_jobs`; usage also uses Task Relay's existing `api_steps` format.
Jobs have their own IDs and never create Telegram update IDs, messages, or file-tool
requests. The CLI explicitly consumes this local queue. Gemini is the only v0 adapter;
it reuses the existing client, response validation and provider configuration.

Budgets limit new calls, cumulative input characters and output tokens per call. They
are not dollar caps. Reported usage includes input, output and thinking tokens when the
provider supplies them. Dollar cost remains unknown without a configured price table.
No billable request is automatically replayed after an ambiguous submission.

JSON structure, citation existence and scope, target guide identity, and exact unique
replacement text are checked before publication. One bounded synthesis retry can fix
a validation error. If it still fails, **no proposals from the run are published**.
A completed extraction is not a semantic endorsement or a successful intervention.

An incomplete discovery can reuse successful episode responses only when dataset,
source revisions, model, settings and complete request contents match:

```sh
python3 -m learning analyze --dataset content --context-chars 400000 \
  --max-calls 3 --max-input-chars 900000 --reuse-episodes analysis:PREVIOUS_ID
python3 -m learning cancel analysis:ID
python3 -m learning recover-job internal:ID
```

Reuse records the prior run and its usage, including failed synthesis. It never resubmits
an old job. `recover-job` marks an interrupted sending job uncertain; it does not retry it.
Cancellation requests stop further calls; an in-flight provider request may still finish
and consume usage. An interrupted overall run remains visibly running/incomplete until
it is cancelled/inspected, rather than being declared successful.

## Review, revise, and apply

```sh
python3 -m learning review proposal:ID
python3 -m learning review proposal:ID --decision accept --review-hash HASH_FROM_CARD
python3 -m learning apply proposal:ID --trial /absolute/new-trial --guide-path docs/guide.md
```

The card shows scope, observation, hypothesis, existing guidance, uncertainty, source
citations, hashes, and the exact diff. Acceptance binds the entire reviewed proposal.
All selected source snapshots are checked against the current files at acceptance and
application; changed/missing sources make the proposal stale. Dismissed proposals cannot
be applied. Identical suggestions link back to the original record and its decisions.

Application creates a **new** directory containing `baseline/docs/guide.md`,
`treatment/docs/guide.md` and `intervention.json`. The baseline bytes are the saved
original; treatment bytes must hash exactly to the reviewed amendment. Writes are atomic,
application intent is journaled first, and existing workspaces are rejected. Only the
guide is copied: production inputs, assets, history, models and requirements must still
be staged identically before running a paired production experiment.

To edit a suggestion, save an amendment JSON object containing the fields to change
(`change`, `scope`, `evidence`, `observation`, `hypothesis`, `existing_guidance`,
`expected_benefit`, `evaluation`, `missing_evidence`). `change` includes the selected
`source_id`, unique literal `before`, and replacement `after`.

```sh
python3 -m learning revise proposal:ID --amendment /absolute/amendment.json --note "Reviewer rationale"
python3 -m learning review proposal:NEW_ID
python3 -m learning review proposal:ID --decision dismiss --note "Already covered"
```

Revision preserves the old version and decisions, labels the new text as a local reviewer
revision, and requires new acceptance. It never inherits an old approval. Dismissing and
other lifecycle decisions are explicit local operator actions; historical approvals and
model responses cannot invoke them.

```sh
python3 -m learning revert application:ID --note "Rollback rationale"
```

Rollback restores saved original bytes only if treatment still matches the applied hash
and its paths have not been redirected through symlinks. It refuses to overwrite later
work. An interrupted application has a `prepared` journal entry and retains its source
bytes; inspect that entry and the trial before recovery. It is not silently reapplied.

## Inspect a subsequent job

Import a job-specific follow-up export into a new dataset, then identify the application
version actually used. Feedback remains ordinary conversation; no correction spreadsheet
is needed.

```sh
python3 -m learning import --dataset followup --workflow content --kind conversation /absolute/next-job.md
python3 -m learning evaluate application:ID --dataset followup --job-id next-reel \
  --workflow content --mode preserve-approved --intervention-hash APPLIED_SHA256
python3 -m learning review proposal:ID --decision keep --note "Review rationale"
```

`--human-minutes NUMBER` is an optional estimate, never inferred from timestamps. Job ID
and intervention use are operator declarations; the current trial hash is independently
checked. This adapter expects one production job per selected follow-up dataset.
Old timestamps are excluded and discovery sources cannot serve as prospective evidence.
The same job cannot be counted twice for one application. Multiple repairs within it
remain one recurrence job.

Outcomes distinguish `recurred`, `no_recurrence_observed`, `outcome_unknown`, and
`no_relevant_jobs_observed`. No relevant job or unknown outcome produces a null recurrence
count. Positive absence requires relevant evidence and explicit user acceptance. Authored
user citations are required for corrections and acceptance. Findings about eligibility,
semantic support, and visual fidelity still need review. Production usage is marked not
supplied until production records are attached; no causal or time-saving claim is made.

## Pilot and remaining work

Verification: `python3 -m unittest tests.test_learning`. Tests cover parsing, source revisions,
citations, bounded coverage, data-only injection text, silent internal jobs, failed and
cancelled calls, exact review receipts, stale sources, isolated application, rollback,
revision provenance and future-job evaluation.
