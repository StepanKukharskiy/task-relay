# Failed registered-operation evidence

New owner grants can enable `work_diagnostics_version: 1`. The shared work compiler
then declares `outputs/work-diagnostics.json` as a code-owned output for every
registered in-worker operation graph. Historical grants do not acquire it.

A confirmed failure commits its normalized terminal receipt, exact input and
assignment identities, and an inventory of declared partial outputs and fixed
execution journals. Text excerpts carry original byte counts, hashes and explicit
truncation flags. Binary content remains identity-only. Links and undeclared paths
are excluded. Original journals and partial files remain unchanged. The registered
preparation schema accompanies the diagnostic projection when applicable.

The active worker reads this output through ordinary `file_read`. Collection
verifies it against the committed journals before registering it, including when
the producing worker is blocked. The owner can bind that exact artifact to an
ordinary recovery assignment. No new filesystem, execution, provider or acceptance
authority is granted. Partial native files are never published as successful work.

Restart reconstructs the same projection from committed receipts without replay.
Changed diagnostic evidence fails verification. An explicitly uncertain operation
propagates the existing uncertainty hold, including for local procedures; it cannot
be downgraded to a confirmed failure by exception handling.

Diagnostics reserve at most 512 KB and one eighth of the original output allowance;
operations receive the remaining allowance. Text capture is bounded to 16 KB per
file and half the diagnostic reserve per failed call. If the aggregate projection
cannot fit, the worker stops with the original journals retained. Truncated or
identity-only evidence is not complete semantic inspection. There is no automatic
retry or domain-specific error-to-repair mapping.

Offline qualification and exact retained-failure replay are recorded under
`private qualification records`. Live qualification remains separate.
