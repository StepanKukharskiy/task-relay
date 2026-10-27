# Owner continuation on independent outcomes

Prospective `owner_progress_version: 1` replaces the owner-wide batch barrier.
New delegation-v4 jobs capture this policy; saved jobs without it retain their
existing continuation behavior. The implementation is an isolated candidate and
has not been applied to the active quality run.

A waiting owner can resume when a child has a new exact completed, blocked or
cancelled outcome, even when unrelated children or reviews are still running.
The owner can use accepted branch results to admit compatible downstream work.
Starting a task, polling, log output and an unreviewed candidate are not wake-up
signals. Simultaneous outcomes are coalesced into one continuation.

Code records the child outcome identities actually exposed in the owner's state
snapshot. Both the ordinary yield checkpoint and the transactionally committed
admission checkpoint retain this cursor. Collection publishes it to the durable
owner-yield event; the existing wake boundary compares it with current outcomes.
It does not take a fresh baseline at yield: a result arriving while the owner is
thinking must still be available for the next continuation. Scheduler restart and
confirmed admission recovery retain the cursor. Owner state changes and wake
receipts stay atomic; dispatch remains outside the transaction.

The existing scheduler owns concurrency, native resource leases, dependency
readiness, independent review and exact artifact binding. This policy adds no new
scheduler, domain stages or inferred dependencies. A join waits for its declared
prerequisites. The owner brief encourages batching independent ready branches and
using completed results while other work runs; it does not remove dependencies
chosen by the owner or guarantee that model planning is efficient.

Unknown effects, cancellation in progress and user gates retain the existing
continuation restrictions. They are not permission to duplicate an operation.
No unchanged result buys another invocation. The final remaining owner invocation
is reserved until pending work settles, so partial progress does not consume the
last opportunity for final inspection/delivery. All original limits remain in force.

Qualification uses small text graphs and scripted clients through the actual
owner loop/controller: overlapping downstream work, reviewed joins and final
completion, simultaneous results, failures, unchanged-state waits, scheduler
restart, completion during an owner turn, confirmed admission crash recovery,
legacy grants and uncertain-effect holds. These are offline checks, not live
model quality or installed host qualification. Commands and limitations are in
`private qualification records`.
