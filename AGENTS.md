# Task Relay

Use `ROADMAP.md` for milestone scope and order. Continue authorized work; do not
turn deferred milestones or unrelated acceptance exercises into prerequisites.
Update the affected roadmap status and `CHANGELOG.md` when behavior changes.

Follow `docs/universal-architecture-decision.md`: compose compatible registered
interfaces; models provide bounded fragments and code owns envelopes, evidence
bindings, handoffs, capacity and recovery. Fix shared boundaries rather than
adding per-domain collectors or controllers. Qualify affected compatible graphs
with synthetic data and distinguish those checks from installed and live results.

Preserve exact user requests, artifact versions, decisions, executed assignments
and recovery receipts. Keep database mutations atomic and external dispatch after
commit. Never infer acceptance, duplicate uncertain submissions, or silently
expand a stage's authorization. Keep OS-specific behavior behind host adapters.

Run tests according to the change's impact, not the size of the repository.
Before testing, identify the changed behavior, plausible regressions and affected
integrations. Start with focused regression tests; add one representative composed
path when a shared boundary changes. UI changes need relevant UI/contract checks;
installer changes need maintenance, interruption and no-replay checks. Neither
requires unrelated sourcing, rendering, media or whole-runtime suites by default.
Documentation-only changes need inspection, not a lifecycle rerun.

Use the full `scripts/qualify_lifecycle.py` matrix for public release candidates,
changes affecting the runtime broadly (such as central scheduling or transaction
semantics), or an explicit request for the full matrix. Explain why the full matrix
is necessary before starting it and check time/disk cost. A local app rebuild or
installation alone is not a reason. Never skip cases or widen grants to claim a
full gate passed. Keep targeted results distinct from full qualification and live
behavior. Once relevant checks pass, stop; repeat only checks affected by new code,
a failure or a specific unresolved concern. Finish code review before expensive runs.

Use small text fixtures and temporary directories by default. On success retain
compact evidence: command, scope, source identity, result/counts and limitations.
Do not retain every synthetic database, copied runtime, image or successful tool
exchange. On failure retain the useful log and minimal reproducible inputs; keep
large fixture trees only when needed to diagnose the failure or explicitly requested.
If a full audit gate binds retained evidence, preserve its verifiable receipt and
required evidence (lossless archiving is acceptable); do not silently discard it.
Do not delete existing runs or evidence without authorization. Preserve live user
work, exact executed assignments and uncertain external-effect receipts separately
from disposable test fixtures. Prefer reusing verified builds over rebuilding or
copying runtimes merely to inspect them.

Record only checks actually run: command, scope, result and relevant limitations.
Keep logs under `outputs/` and distinguish controlled tests from deployed checks.
For every live execution attempt, retain the exact Relay-supplied system prompt,
context and tool declarations, provider-returned output, and Relay's tool,
delegation, review and recovery reactions. Maintain a readable audit index over
the original journals, including failed attempts and unknown or missing responses.
Do not reconstruct provider-private instructions or infer zero usage from silence.
Do not claim a service was reloaded, a provider ran or a message reached the user
without evidence. Code changes alone do not authorize live messages or paid work.

Public source must pass `python3 scripts/check_publication.py --staged` before
commit. Keep personal research and installation records in ignored private storage.
