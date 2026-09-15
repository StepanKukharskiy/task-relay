# Automation opportunities from Relay history

Development source can analyze recorded history locally and suggest automation
opportunities. The analyzer does not call an AI provider, read artifact contents,
modify existing requests, or start execution. Natural-language discovery uses the
normal orchestrator interpreter; the explicit command skips that model call.

## Inspect and promote

- `/opportunities` analyzes the latest history in the current channel and saves
  an immutable evidence snapshot.
- `/opportunities list` shows the latest snapshot. Add a page number for more.
- `/opportunities OPPORTUNITY_ID` shows supporting workflows or requests, recorded
  outcomes, user decisions, failures, repairs and available planning usage. Add a
  page number to inspect further evidence.
- Ask Relay to draft a particular opportunity from one of its listed completed
  exemplar workflows, specifying literal project variables. The draft retains the
  candidate ID, fingerprint and exact source receipt fingerprint.
- Inspect and approve the resulting version with `/procedures approve ID`.
  Preparing a run, selecting Resume, and native-code Start remain separate.

A direct draft is also available without model interpretation:

```text
/opportunities draft OPPORTUNITY_ID WORKFLOW_ID {"name":"Research and report","parameters":[{"name":"location","example":"Iowa"}]}
```

The example must occur literally in the chosen workflow. Missing or changed
source receipts prevent promotion; analysis must be refreshed. A changed draft
does not overwrite an earlier procedure version. Unknown or cross-channel IDs
are rejected. Inspecting or drafting suggestions never approves work.

## Discovery rules

| Candidate | Matching and evidence | Proposed next action |
| --- | --- | --- |
| Repeated workflow | Two or more distinct workflow IDs with the same ordered stage contracts | Review a complete example and its project variables as a reusable procedure |
| Shared sequence | Two to six adjacent stages shared across different complete workflow structures | Review a reusable component opportunity; current promotion keeps the complete exemplar |
| Repeated request | Two or more human request IDs with the same text after whitespace normalization | Distinguish retries from recurring tasks and capture a successful workflow |
| Repeated failure | Matching recorded stage-error text, or the same provider/phase/error class across human requests | Compare receipts before proposing a preflight check or validated repair rule |

Matching uses exact registered-operation sets, routes, gates and output counts
where a concrete contract exists. Generated stage names and output-role names
may differ. Untyped conversation stages retain their IDs and output roles to
avoid grouping all text tasks together. Operation sets and review gates are never
relaxed. The original stage definitions remain unchanged in every exemplar.
Structural matching identifies a candidate, not semantic equivalence.

Each workflow contributes at most one observation per pattern; retries and repeated
failure events do not increase the independent workflow count. Internal stage
requests and prior discovery actions are excluded from human-request matching.
Exact-request matching preserves case and numbers. Failure classes may contain
different causes; the tool displays the underlying messages for review.

Shared-sequence discovery **does not yet extract standalone subprocedures**. Such
extraction needs a reviewed contract for inputs supplied by preceding stages.
Promotion preserves the complete exemplar, with its original request and all
prerequisites, instead of silently removing stages. Preferences, repair rules and
provider changes are proposals for further work, not automatically applied learning.

## Measurements and limits

The report shows occurrence counts, recorded completion, choice events, selected
artifact versions, clarification events, failure events and repair receipts.
Completion does not imply user acceptance; a repair preparation receipt does not
prove repaired host execution succeeded. Request-only outcomes remain unknown.
Recorded elapsed spans include waiting and review; they are not active work time.

Usage totals cover directly linked stage-planning calls, with provider/model and
measurement coverage. Missing usage stays unknown. Browser, chat and production
worker usage are not included in that total. Recorded token expenditure is not
an estimate of savings; no dollar or time savings are invented.

Each analysis examines at most 200 recent workflows and 1,000 recent human requests
in its channel. Coverage totals and skipped malformed records are visible. At most
50 candidates are retained, ordered by available completed exemplars and then
repetition frequency. This is an explicit priority heuristic, not a confidence
probability. Identical supporting sets keep maximal shared sequences to reduce noise.

Reports and candidates live in the local Relay database. Their creation is atomic
and idempotent by channel/request identity. Old evidence remains inspectable after
later scans. Saved procedure versions retain their own approval boundary and use
fresh outputs when run. The selected opportunity's source is shown to the
orchestrator only as context; discovery context is excluded from execution-stage
prompts.

## Read-only local inspection

For development or offline analysis:

```sh
python3 -B -m task_relay.opportunities --database /path/to/state.sqlite --channel telegram --json
```

This opens SQLite in read-only mode and does not construct the application State,
migrate the database, or save candidates. It can inspect pipeline history from
installations predating procedure support. Keep exported reports in private,
ignored storage: they contain request excerpts and workflow evidence. The command
analyzes the explicitly selected database, which may differ from another installed
app's data directory.

## Controlled validation

`python3 -B -m unittest tests.test_opportunities tests.test_procedures tests.test_messages_orchestrator tests.test_pipelines tests.test_workflow_files tests.test_channel_policy`

All 98 tests passed locally on macOS. Small SQLite/text fixtures cover renamed
stage contracts, preserved gate differences, shared sequences, independent
occurrence counts, partial/unknown usage, current-channel isolation, internal-job
exclusion, bounded coverage, immutable snapshots, stale/tampered evidence, atomic
rollback, pagination and exact draft promotion. A subprocess check opens a
pre-procedure schema read-only without migrating it. No live provider, media,
native-app execution or messenger delivery was performed by these checks.
