# Confirmed responses and terminal draining

The shared receipt boundary separates a correlated operation response from later
local cleanup. An adapter commits the validated response before teardown, binding
its exact request/terminal identity, operation scope and original journal hashes.
Unresolved tool effects prevent confirmation. A cleanup failure is a separate
diagnostic; it cannot replace a verified response with uncertainty. All cleanup
actions are attempted, and an existing request error takes precedence.

The Codex transport normalizes its thread/turn protocol into this contract. The
source adapter assigns each submission a unique operation identity. After a
restart, it can reconcile a submitted search only from the matching verified
response. It preserves the original search record in a separate recovery receipt,
does not launch a provider, and does not infer acceptance. Missing terminals,
pending effects, different submissions and altered evidence remain fail-closed.
This does not reconstruct receipts for historical runs or replay unknown effects.
Provider-private requests and missing usage remain unknown.

Runtime uses one stop/settlement derivation for owned and ordinary graphs. A stop
decision (including uncertainty, user hold, pause, cancellation and owner failure)
with known dispatched work reports `active` plus `settlement`:
`terminal_outcome`, `pending` and `dispatch_allowed:false`. Claiming is disabled
before authorization or external dispatch. Existing handles are collected through
the ordinary atomic collection path, including after scheduler restart. Once that
work drains, the retained terminal outcome becomes the derived status. Unknown
receipts remain unknown; collection is not acceptance or permission to replay.

Production views expose the same settlement descriptor. Controls retain pause,
resume and cancellation intent during draining; queued work is shown as stopped.
No extra controller, provider fallback, domain special case or budget expansion
is introduced. Run status consumers must use the derived status and settlement,
not the stored production flag alone.

Offline evidence and precise limitations are in
`private qualification records`. A local protocol peer reproduces a
completed search followed by teardown PermissionError; this is a demonstrated
failure mode consistent with AL, not a recovered stack trace from AL. Controlled
tests do not establish live native quality or full workflow completion.
