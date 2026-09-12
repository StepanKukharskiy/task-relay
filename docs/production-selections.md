# Production decisions and stage control — O05

When independent review releases a producer to its user decision, Telegram result
and status cards show **Select task/path** buttons. The choice is bound to the run,
task, assignment, attempt, artifact hash and declared decision purpose. The selected
file must finish delivery first. A button records that one artifact's selection;
it does not approve sibling files or create a new stage. Status shows saved selections.

Cards and delivered-message bindings are persisted in the shared database. Duplicate
clicks cannot add another decision. Unpaired users, wrong messages/channels, revised
attempts, changed artifact bytes, cancelled runs and pending feedback/revisions are
rejected. Selection, its receipt and confirmation notice commit together. The local
CLI also rejects selection on a cancelled run.

This slice displays up to 30 file choices per card and supports choosing one output
for each producer's existing decision purpose. Bare text such as “B” is not converted
into an artifact selection. Selecting a file does not enable a stopped scheduler
or authorize new work. Multi-output decisions and branching successor plans are
outside this bounded implementation.

**Pause scheduling** stops further dispatch while running workers may finish. The
durable stage stays paused across restart; **Resume** uses the same unchanged
scheduling authorization. **Cancel stage** saves cancellation intent and stops future
tasks. The scheduler keeps monitoring workers after scheduling is disabled and
retries cancellation delivery until a terminal receipt arrives. Uncertain termination
remains visibly pending. Cancellation preserves outputs and history. Controls bind
to a delivered message, owner, channel, contract and control version; stale or
duplicate taps cannot restart work. These are production controls; linked `/workflow`
controls remain separate.

After selecting an output, describe the next stage. The orchestrator uses
`plan_production` with `previous_run` naming the completed stage. The planner carries
the exact artifact IDs/hashes, selection purposes, original instructions, prior
feedback and original job identity to both workers. Source bytes are checked again
before registration. New work follows the existing bounded plan approval flow.
There is one successor per stage; duplicates reuse its saved plan. Clarification via
`parent_id` versions that proposal and invalidates its old card. It does not alter
already executed assignments. Same-scope blocked-stage recovery remains the
separate `continue_production` operation.

**Check status** follows registered stage lineage and shows the outcome, task states,
attempt budgets, pending decisions and recorded selections. **Inspect stage** sends
a JSON snapshot with assignments/inputs, executor, artifacts, decisions, checks,
receipts and available worker logs. Event data is capped at 180 KB and logs at
128 KB total / 32 KB per file, with omissions marked. Recorded usage is preserved;
unreported usage/cost remains unknown. Inspection does not invoke a model or worker.

Inspection and focused orchestrator context also include bounded, cross-run
[artifact dependency history](artifact-dependencies.md): exact frozen inputs,
derived outputs and selection purposes. The local impact command previews consumers
of a proposed replacement. Neither query changes selections or schedules rebuilds.

Explicit [version replacement](artifact-replacements.md) is a separate decision
between two saved selections with the same job and purpose. Telegram presents exact
versions and impact before confirmation. Original decisions remain historical;
Check status and Inspect stage show affected outputs. Next-stage inputs include
relevant current replacements and preserved history, and approval binds replacement
revisions. Replacement itself never starts an update stage.
