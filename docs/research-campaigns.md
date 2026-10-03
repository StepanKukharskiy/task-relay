# Research campaign controller

Installed locally in Task Relay 0.13.130. All 30 installed campaign/scripting checks
passed, including a synthetic twenty-entity campaign. A live run exposed an Apple
Event timeout and invalid home-only discovery grant; the new preflight rejects
that grant. A completed live research campaign is not claimed.

The conversational orchestrator proposes a `research_campaign` policy on a
`plan_pipeline` action. Job data defines the entity type, target count, required
fields, required qualification criteria, batch size, maximum batches and discovery
and assessment instructions. `stage_details` contains the final delivery stages.
The workflow builder constructs research slots and typed ports; the model does
not enumerate a bespoke batch graph or invent ledger schemas.

The policy is version 1. Each criterion is `{id, question}` and is required:
all `met` qualifies, any `unmet` rejects, otherwise the entity is held. Preferences
must remain contextual fields unless the user actually requires them. Existing
automation, tools or staff are not built-in exclusions. Unknowns cannot be
silently promoted or filled with inferred facts.

## Bounded execution

Relay compiles up to twelve discovery/assessment pairs followed by one to four
final delivery stages. This is an explicit campaign grant, not an increase to
the ordinary twelve-stage pipeline limit. The complete slot graph is saved
before work starts and never rewritten to add capacity. Maximum yield capacity
must reach the requested target; it does not guarantee yield. Each record's
identity, fields and criterion decisions count against the existing thirty-unit
record audit limit, plus ten summary claims. Batch size must also fit the
twenty-four-request executor ceiling.

Each slot has exactly one Safari producer and one independent saved-evidence
reviewer. They each have one attempt. Producer ceilings are 300 seconds and
24 requests/tools; reviewer ceilings are 600 seconds and 16 requests/tools.
Responses have at most 8192 output tokens. Existing Safari action, exact URL,
provider binding and source-transfer rules apply. Stage routing and planning
retain their existing bounded calls. Final output stages retain their declared
production limits and user-selection gates. No per-job monetary estimate is
inferred from request ceilings.

Discovery returns `research.batch` records with `discovery_reason` and no
criteria. Assessment receives that exact reviewed ledger and plans exact profile
URLs before dispatch. It must account for every new identity in the batch.
The controller reduces the last batch's record ceiling to the remaining target.
Queries and evidence judgments remain model work; schemas, budgets, versions,
counts and transitions are code-owned.

Campaign discovery rejects X home/explore URLs and `/search` without one nonempty
`q` parameter before dispatch. The planner chooses exact URL-encoded query URLs or
specific source pages. The worker cannot turn a landing page into a search by
typing or clicking. Apple Event timeout diagnostics retain the failing native
step; a timed-out launch/read remains uncertain and is never automatically replayed.

## Evidence and qualification

`research.batch` uses the same provider-neutral `operation_submit` checkpoint
store as other record families. Every record includes the candidate identity,
source-linked facts and one `{criterion, verdict, reason, supports}` decision per
policy criterion. Review units include the complete question, decision and reason.
The separate reviewer must substantiate each unit against its exact raw pack;
an accepted audit is distinct from a qualified candidate and from user acceptance.

Completion ingestion checks the current producer/reviewer attempts, committed
record exports, accepted-review event, exact evidence/summary hashes and raw input
hashes. Qualified identities additionally require a captured profile visit;
granting a URL or quoting a search snippet is insufficient. Inaccessible profiles
cannot qualify. Missing identity provenance can still block a worker rather than
produce a held record; the controller never fabricates identity support.

X profile handles are normalized across `x.com`/`twitter.com`, case and tracking
queries; post/search URLs cannot stand in for profile identities. For other sites,
meaningful query strings remain part of identity. Real-world aliases across
different URLs are not automatically resolved. Every reviewed record version and
receipt remains in the ledger; duplicates never increase the unique count.

## Progress and recovery

The shared database stores campaign receipt ingestion in the same transaction as
pipeline completion. Deterministic pipeline request IDs and the existing queue
prevent duplicate dispatch after restart. Re-ingesting an identical receipt is
idempotent; a conflicting completion is rejected. A crash before commit rolls back
both progress and stage completion. No external call occurs in that transaction.

Empty discovery is a reviewed outcome. If no new identities remain, its assessment
slot is marked `skipped`, not completed or accepted. The next discovery uses the
remaining fixed capacity. Once the target is met, unused research slots are
skipped. When capacity is exhausted, the ledger reports `shortfall`, exact counts
and remaining target. It never pads results or loops indefinitely. A rejected
evidence audit, failed worker or uncertain provider/native outcome blocks the
existing workflow; it does not become a free replacement batch. Pause and cancel
retain their existing behavior.

Progress appears in the workflow catalog and reviewed-batch notices. The `.relay`
job-state export and final-stage frozen context include the ledger, policy,
counts, outcome, versions and review bindings. Exact registered raw captures
travel with completed source artifacts. Final production workers can assemble
requested spreadsheets, notes and drafts from these inputs with independent
review; dedicated deterministic campaign exporters are not part of this change.
Outreach remains draft only. Nothing is user-accepted merely because the campaign
has reached its target.

Controlled qualification uses small synthetic captures, including twenty entities
through the production-completion path, prospect/supplier parameter reuse, empty
and duplicate batches, holds, rejection, shortfall, changed sources, interrupted
transactions and uncertain outcomes. It performs no paid requests or browser work.
