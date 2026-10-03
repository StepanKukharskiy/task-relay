# Common execution results — local runtime pilot

Relay can observe different saved execution paths through one versioned
`task-relay.execution-result` envelope, then explicitly capture that observation
into a work project. The envelope is a projection over owning database records.
It supplies no dispatch, acceptance, selection or delivery authority.

This functionality is packaged in local Task Relay 0.13.153 through existing completion/capture paths and the
local work-state CLI. Existing scoped
MCP tools can inspect captured results, their provenance and subsequent
continuation packets. They cannot grant a source database or invoke these local
administration commands. The runtime now records completion observations and
captures them into explicitly linked work projects. Reviewed text runs and plugin
reports use their existing owning project/packet. Generic external MCP executors,
universal discovery of project ownership and live executor-swap qualification
remain open. The signed local app installation verifies 302 source-matching
runtime files, 13 controlled completion/recovery checks using bundled Python,
installed imports, strict signatures and fresh owned-service health. App/database
recovery copies are retained. The update adds no Desktop source-linking interface
and does not qualify a deployed ChatGPT plugin or live worker action.

## Contract, version 1

| Field | Meaning |
| --- | --- |
| `source` | Exact source kind and record identity |
| `assignment` | Owning assignment/job/attempt, saved request, version and available specification/packet hashes |
| `executor` | Saved binding, model, operation and binding basis; locality is `not_recorded` when absent from source records |
| `status.execution` | Common observation: queued, in progress, completed, blocked, failed, stopped, uncertain or not recorded |
| `status.source_state` | Original runtime state, retained separately from its common projection |
| `status.certainty` | Saved uncertainty is retained even when the local process is terminal; `recorded` describes the observation, not external success |
| `status.validation` | Checks recorded or not recorded; it never implies every check passed |
| `status.selection`, `status.delivery` | `not_projected`; consult the owning decision and delivery records |
| `inputs`, `outputs.artifacts` | Available pinned references, paths, hashes and metadata; source files are not automatically imported or selected |
| `evidence`, `validation.checks`, `issues` | Original event/report/check distinctions and available findings |
| `receipt` | Available original receipt fields; missing times or dispatch records are not invented |
| `source_record_sha256` | Hash binding the private saved source-row snapshot |
| `limitations` | Missing coverage and the observation's authority limits |

Source adapters read existing database rows without provider calls or artifact
file access. A production attempt retains its immutable specification version,
frozen input hashes, actual backend binding, session/receipt, outputs and events.
The profile identity stays in `executor.binding`; it is not replaced with an
assumed provider. Model location and code execution location remain distinct.
The envelope does not reinterpret operation-specific checks as a universal pass.

## Supported source records

| CLI kind | Source identity | Bounds and authority |
| --- | --- | --- |
| `production_attempt` | Production attempt ID | Joins its exact assignment, frozen attempt, output ownership and events; retains procedural, registered-operation, model-review and worker-report checks |
| `backend_job` | Direct provider job ID | Retains job, provider run, saved history and attributable artifact rows; current task binding is disclosed as mutable, input coverage may be incomplete |
| `native_candidate` | `relay_agent_candidates.id` | Checked submitted native candidate and frozen impact handoff; external execution remains not recorded |
| `xlsx_candidate` | `relay_fact_external_submissions.id` | Checked submitted spreadsheet candidate and frozen impact handoff; external execution remains not recorded |
| `plugin_capture` | Result capture hash, plus `--source-project` | Explicit assistant notes/questions and continuation hash; these remain model reports |
| `work_text_run` | Reviewed text run ID | Saved exact-text assignment, continuation and output receipt; output selection remains a separate user decision |
| `revision_bundle` | Submitted revision bundle ID | Native candidate and both companion versions, saved checks and available original review/selection evidence |
| `bundle_continuation` | Submitted continuation ID | Three-member set, exact selected-parent digest and receipt hash, saved checks and available original review/selection evidence |

Candidate inspection checks handoff ownership, saved plan hash, candidate hash
and available declared inputs. It does not rerun native package checks or review
quality. These guards verify record consistency, not arbitrary databases' truth.
Local administration deliberately grants a source database and associates an
observation with a target continuation. That association is provenance; it does
not establish that the continuation dispatched the source execution.

## Connected completion and capture

Production collection and uncertain dispatch, direct provider completion, native
and spreadsheet admission, revision-set/continuation admission, reviewed text
completion and plugin result capture now call the same observation bridge. The
bridge retains intent and a frozen envelope in the owning transaction. It keeps
typed operation checkpoints/submission receipts and available parent/set decision
evidence without converting them into target-project selections.

Projection failure remains a pending capture intent with its original source-row
hash. It does not change a completed worker into a failure. Once projected, work
capture retries read the frozen observation, including after source change or
deletion. Capture failure rolls back its request/execution/evidence records and
retains the observation plus pending delivery. No recovery path calls a provider,
dispatches a worker or repeats native editing.

Reviewed text and plugin captures already own an exact project and packet; their
result envelope is captured automatically using that ownership. Plugin notes
remain model reports. Other source paths require an explicit host binding to one
source identity and saved continuation. An unbound completion records its envelope
without guessing a project, creating work or changing any selection.

```sh
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite bind-result --project WORK_ID --packet PACKET_ID --kind production_attempt --source-id ATTEMPT_ID --key LINK_KEY --request-file /private/link-request.txt
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite completion-status
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite recover-results --limit 100
```

Bind an existing claimed attempt before completion, or bind an already observed
saved result. Same-key binding retries preserve the exact project, packet, source
and request; conflicting reuse is refused. Existing scoped work inspection exposes
`execution_capture_state` for that project, including waiting, projection-pending,
pending capture and captured states. The source hash guard refuses to reinterpret
an original pending intent after its root record changes. A later separately
recorded outcome has its own observation. Recovery processes bounded batches;
unresolved capture errors remain visible for further recovery or review.

For existing saved completion records, explicit local backfill is available:

```sh
python3 -m task_relay.work_state_cli --db /absolute/private/copy.sqlite observe-result --kind revision_bundle --source-id BUNDLE_ID
```

Backfill observes a saved outcome only. Production/provider/text sources still
queued or running are refused. Native admission remains recorded as a checked
candidate with external execution not recorded. New observations do not overwrite
older frozen envelopes or their recovery receipts. Local link/backfill/recovery
commands add no MCP source grants. No blanket production/work synchronization or
background recovery service is introduced; owning capture retries and the local
recovery command repair pending capture.

## Inspect, capture and return

Use the source database explicitly. It can be the work database or a separately
selected database, which the CLI opens read-only. `SOURCE_ID` is the saved record
identity for `KIND`; it is not a path to an output file.

```sh
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite inspect-result --source-db /absolute/private/source.sqlite --kind production_attempt --source-id SOURCE_ID
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite capture-execution --project WORK_ID --packet PACKET_ID --source-db /absolute/private/source.sqlite --kind production_attempt --source-id SOURCE_ID --sha256 INSPECTED_SHA256 --key CAPTURE_KEY --request-file /private/capture-request.txt
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite inspect --project WORK_ID
```

Inspection returns a redacted envelope and a hash binding the exact private
projection and original rows. Capture rechecks that hash inside a source snapshot;
changed sources require a fresh inspection. It atomically retains original source
rows, the envelope, the exact local capture request, execution/evidence records and
a recovery receipt. Same-key retries with identical arguments return the original
receipt even after the source changes or disappears; conflicting reuse is refused.
At most 1,000 rows per source query and 2 MB per source snapshot/envelope are
accepted. Oversized records are rejected rather than truncated.

The target continuation must belong to the project and match its saved hash.
Late captures retain the original packet and disclose changed project revision
and changed selected input files separately. Project revision advances and prior
understanding becomes stale. Captured evidence is available to the next
understanding; continuation packets include relevant `execution_results` without
silently exceeding their budget. Selection of an existing project artifact stays
intact. Result artifact references remain within the envelope until explicitly
connected through the work artifact contract.

This is a historical snapshot. Subsequent changes in the source runtime do not
update a captured observation; inspect and explicitly capture a new observation
when needed. Output byte integrity is not revalidated by source inspection.

## Export and recovery

The work project needs a folder grant made by local administration. Export only
writes an explicitly named relative path under that grant.

```sh
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite export-result --project WORK_ID --key CAPTURE_KEY --path .relay/results/captured-result.json
```

Export commits destination and byte-hash intent before writing, verifies read-back
and saves a receipt. Retrying an interrupted export checks an existing identical
file or recreates a missing projection from the saved capture. It never reruns the
worker. Changed files, linked destinations and traversal are refused. The exported
envelope is redacted: its `source_sha256` binds private captured source bytes, while
the export receipt's hash binds the actual redacted file bytes. Export does not
alter the work revision or establish artifact acceptance.

## Qualification

Controlled text fixtures represent research/deck production, native geometry,
spreadsheet candidate submission, code work and direct generated-media metadata.
The same capture path handles Codex/OpenAI/Gemini binding records. Additional
checks cover native candidates, plugin notes, reviewed text receipts, source
changes, conflicting retries, missing sources, identity/hash mismatches, atomic
rollback, stale understanding, changed input files, bounds, redaction and
interrupted export recovery. Actual SDK stdio checks expose a locally captured
text result through a scoped MCP project and continuation; foreign projects stay
inaccessible.

Completion integration is also verified on isolated database copies of three saved
plant revision/continuation sets and five saved research outcomes, including
completed, blocked and cancelled work. All three plant artifact references, hashes,
saved cross-file checks, available original decisions and the continuation's exact
parent receipt are retained. Forced capture failure, frozen recovery, repeated
notification, export and return preserve the same receipt and work revision on
retry. Original database tables and owning tables in the copies remain unchanged.
Native/provider admission-hook tests use small text files and controlled admission
checks; they do not repeat native package qualification. The 86 focused checks
include completion rollback, pending-state inspection, CLI binding/recovery and
actual scoped SDK exposure of an automatically captured text result.

These are saved-record and protocol checks. No live provider swap, generation,
native application execution, deployed ChatGPT session or service installation
is qualified by them. Test commands and outcomes are retained in ignored local
outputs.
