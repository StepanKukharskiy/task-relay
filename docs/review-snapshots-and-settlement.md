# Exact review snapshots and terminal collection

Prospective `review_snapshot_version:1` distinguishes two uses of the existing
`review_of` intent. A new producer has one completion gate, declared before it
starts. An already completed producer can receive an independent snapshot review
with additional exact artifacts in `inputs`. Code owns output declarations and
pins every task/output binding to its existing producing attempt. The original
producer criteria, handoff closure, visual checks and final finding obligations
still apply. No extra report-author worker or new controller is introduced.

The shared contract validates snapshots at admission, dispatch and collection.
A changed/noncompleted dependency blocks dispatch. Original stage gates remain
unique; snapshots neither replace their verdicts nor reopen/retry producers.
Rejected findings enter the existing correction lifecycle and invalidate stale
final approval. Combined final review covers only exact frozen artifacts; final
delivery still checks current completed producers, hashes, rendered observations
and resolution of all outstanding findings. Unknown outcomes enter the existing
durable reconciliation hold and cannot be automatically recollected or replayed.

Owners receive explicit routing instructions; malformed ordinary-worker outputs
report their required `{name, media_type, purpose}` shape. Code never coerces bad
proposals or supplies semantic review content.

When an owner stops while dispatched workers remain, Runtime.status reports
`active` with `settlement` containing the terminal outcome, pending tasks and
`dispatch_allowed:false`. The existing scheduler continues collection only.
Runtime.claim blocks new child/reviewer/native dispatch before authorization.
After known active transports finish, the derived status becomes blocked,
completed or uncertain as the retained state requires. Restart uses the original
handles; collection stays atomic and idempotent. This does not accept results,
raise capacity, reopen the owner or authorize another run.

The subsequent [receipt and draining contract](receipts-and-terminal-draining.md)
extends this rule to every run stop path, including a waiting owner with an
uncertain child, ordinary graphs, user holds, pause and cancellation.

Qualification commands and limitations are recorded in
`private qualification records`; offline fixtures and original AK
compiler replay are distinct from subsequent unscripted live qualification.
