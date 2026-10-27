# Codex and Relay: execution ownership review

Reviewed 2026-10-10. This compares inspected implementation and published interfaces,
not private desktop internals. It identifies observed control defects and hypotheses
to test, not a requirement to replace fresh workers with persistent sessions.

## Evidence

Public Codex source was inspected at commit
`806d9732c974bc8a51b8317c1bd8985544fe627c`:

- [Session turn loop](https://github.com/openai/codex/blob/806d9732c974bc8a51b8317c1bd8985544fe627c/codex-rs/core/src/session/turn.rs):
  sampling, tool follow-up, incoming user input and context compaction share a turn
  loop. Continued tool work and pending input determine whether another step runs.
- [Tool router](https://github.com/openai/codex/blob/806d9732c974bc8a51b8317c1bd8985544fe627c/codex-rs/core/src/tools/router.rs):
  registered tool implementations receive session and step context. Recoverable
  argument errors can be returned to the model.
- [Rollout recorder](https://github.com/openai/codex/blob/806d9732c974bc8a51b8317c1bd8985544fe627c/codex-rs/rollout/src/recorder.rs):
  session items persist in JSONL and can be loaded for resumption.
- [App-server protocol](https://learn.chatgpt.com/docs/app-server): clients manage
  threads and turns, resume stored threads and consume typed progress/completion
  events. These are application responsibilities, not semantic worker choices.
- [Open harness integration](https://developers.openai.com/blog/codex-as-a-platform):
  applications can retain their product records and controls around the Codex
  harness. The unrelated sample application named Relay is not this repository.

Relay implementation inspected: `orchestrator/workers.py`, `supervisor.py`,
`gemini_worker.py`, `operation_session.py`, `task_relay/pipelines.py`,
`completion_recovery.py`, and the normal-entry/tool-loop delivery fixtures.

## Differences that matter

| Boundary | Codex evidence | Current Relay implementation | Consequence |
| --- | --- | --- | --- |
| Working context | A session carries history across steps and turns. | CLI assignments launch `codex exec --ephemeral`; each fresh worker is explicitly scoped away from the overall job. | Durable files and receipts survive, but the agent repeatedly reconstructs working context. |
| Work decomposition | Tools operate inside a continuing session loop. | Separate planners, authors, intermediate reviewers, merges and recoveries compose many small assignments. | Each additional boundary needs capacity, exact bindings and another successful handoff. |
| Recovery ownership | Runtime/session APIs own lifecycle; tool feedback can remain in the loop. | Model-facing controls exposed `resume`, `recover_planning`, `retry_planning` and `recover_work`. | A semantically correct continuation request could select an incompatible internal transition. |
| Persistence | Canonical session items plus workspace files. | Exact artifact versions, attempts, typed records and selected review checkpoints. | Strong provenance exists; general conversation continuity does not automatically follow from it. |
| Progress | Typed turn/item events and output deltas. | Supervisor telemetry and workflow/task projections exist, but their UI does not consistently explain useful current work. | Running state alone does not communicate progress toward the deliverable. |
| Verification | The inspected loop can run tools/checks and continue on feedback. | Independent review is frequently mandatory at intermediate operation boundaries. | Useful independent review becomes expensive when repeated on mechanically derived or unchanged evidence. |

This is not evidence that Codex always completes. Its protocol includes failed and
interrupted turns, usage limits and approval requests. Nor does the comparison
isolate model quality: Relay and the comparison used different model/provider and
tool configurations. The observed control and handoff failures are nevertheless
direct implementation evidence, independent of that confound.

## Migration order

Fresh bounded workers are a valid design when assignments provide adequate inputs,
tools, authority, time and output contracts. Freshness alone has not been isolated
as the cause of the live failure. More boundaries increase coordination obligations,
but their measured cost and benefit need comparison under matched conditions.

1. Expose user intent only: pause, continue, cancel. Resolve continuation from the
   current stage binding and confirmed receipts in the existing transaction owner.
   Keep all historical requests and legacy control receipts. Continuing does not
   grant additional capacity or permission to replay an uncertain effect.
2. Verify that each fresh-worker assignment is independently finishable with its
   exact inputs, allowed tools, authority, limits and output contract. Test larger
   deliverable-sized assignments and persistent sessions as alternatives under
   matched conditions; neither is an established cure. A persistent adapter would
   need actual installed-protocol qualification. Keep explicit provider choices;
   do not switch an existing Gemini run to Codex.
3. Present registered operations as tools inside that session where their effects
   permit it. Keep graph boundaries for actual dependency, permission, independent
   review and delivery boundaries. Do not require a new planner/worker/reviewer
   exchange for every mechanical projection or tool choice.
4. Bind independent review to a candidate version and criterion dependencies.
   Review final quality and substantive changes; code checks schema, identity and
   unchanged deterministic evidence. Never infer semantic acceptance from a cache
   hit, a completion seal or a producer's self-review.
5. Keep one controller for lifecycle and job-level authority, and adapter-specific
   proofs for external effects. Per-invocation timeouts are not new authorization
   boundaries by themselves. Persist useful progress and continue within the
   remaining job allocation; hold on real permission, billing or uncertainty.

The registry, exact artifacts, effect receipts and transactional controller are
assets to retain. The target is fewer compulsory handoffs, not another controller
layer or removal of independent quality review.

## Qualification corrections

Controlled tests remain valuable for atomicity, idempotence, stale bindings,
uncertain effects, provider errors and restart. They are not live delivery proof.

The prior billing rehearsal invoked `recover_work` directly. It supplied the
correct internal mechanism itself and therefore missed the ordinary-intake
`resume` failure. New regressions enter through interpretation/dispatch with only
continuation intent, including the historical `resume` response, and assert real
state effects, immutable history and no extra authorization. Typed billing tests
also exercise that public dispatch boundary with a saved partial checkpoint.

Live qualification must use the ordinary installed entry, actual model decisions
and actual tools. Freeze request, inputs, provider, limits and installed build;
retain initial and changed artifacts. Grade coverage, factual support, visual
quality and preservation of unchanged content separately from controller status.
Record elapsed time, usage and every intervention. A repaired or manually resumed
run cannot become an unattended pass. Missing revision or final quality evidence
must remain incomplete, not inherit success from component checks.

The current assisted run remains negative unattended evidence. A fresh complete
initial-and-change run is the acceptance gate for a new execution architecture;
it cannot be replaced by a larger scripted suite or a single resumed review.
