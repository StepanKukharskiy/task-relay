# Runtime pinning and unstarted review recovery

Prospective native code qualification may use `code_runtime.configure(True,
pin=True)`. The host copies a self-contained Python distribution into private
storage, retains a complete hash manifest, verifies relocation, and checks the
existing sandbox/tool contract. It never installs packages or refreshes an old
run. File copies are independent, not hard links. Internal links relocate;
inert external packaging links retain exact text and cannot gain a newly existing
destination. Active external links and source changes during copying reject.

The frozen backend runtime ID binds the private copy and manifest. Availability
and native execution verify that copy rather than a mutable installation.
Native code agent commands use its interpreter. Controller/registered-operation
launchers can use the same verified interpreter so their descendants retain the
same libraries across restart. Missing or modified pinned files fail closed.
Legacy receipts still require exact current-installation identity. No historical
receipt is promoted, no runtime permission is inferred, and no limits increase.

A new correlated `capability_unavailable` event for an unstarted reviewer records
its unchanged assignment/spec, candidate attempt, backend and exact input hashes.
The existing controller may requeue that same slot after availability returns.
It rechecks evidence, dependencies and review identity in an atomic transaction;
ordinary claim and external dispatch occur afterward. Re-admissions are bounded
by the original max-attempt count and each failure event is consumed once.
Executed reviews, unknown effects, changed inputs/assignments, stopped owners and
old bare failure events never qualify. This is infrastructure recovery, not a new
semantic gate or acceptance. Codex still owns substantive decisions and final review.

Controlled qualifications and the authorized fresh live outcome are recorded in
ignored `private qualification records`. Offline checks do not prove live
browser accessibility, provider behavior or final artifact quality.
