# Shared operational storage

The local relay, Messages pairing/delivery, all managed provider queues, and the production runtime use
`private/state.sqlite`. Production records live in `production_runs`,
`production_tasks`, `production_assignments`, `production_attempts`,
`production_artifacts`, `production_events` and `production_decisions`. The existing
provider `artifacts` table keeps its separate meaning. IDs and JSON contracts are
unchanged; worker files and immutable artifact blobs remain in their existing folders.

Each background thread keeps its own connection, as before. Production scheduling
shares that thread's State connection. CLI operations against `private/orchestrator`
resolve to the same database. Explicit isolated experiment roots use their own
single `state.sqlite`; they are not another live application store.

## Atomic changes and external actions

Production revision assignments, guide usage, scheduling flags and relay receipts
commit together. Continuation creation, lineage, inputs and its registration receipt
also commit together. Reference registration, its ready receipt and delivery queue
entries share a transaction. Nested operations use savepoints instead of committing
the caller's transaction. Production inspection reads relay and runtime metadata
within one SQLite snapshot.

Worker claims still commit BEFORE external process submission. The scheduler rejects
an uncommitted enclosing transaction at this boundary. Telegram/model/desktop calls
retain durable outboxes, submission receipts and uncertain-state handling. Sharing a
database cannot make an external API call transactional. Completion-to-notification
recovery remains idempotent through existing delivery IDs.

WAL allows readers during writes. SQLite still permits one writer at a time; long
artifact-registration transactions can delay other writers. This migration preserves
current file-copy behavior and does not promise parallel writes or unify provider-job
and production-job execution semantics.

## Migration and retention

Stop the launch service and any standalone runtime writers. Confirm idle submissions,
then use SQLite backups of both original databases. The explicit offline migration is:

```sh
python3 -m orchestrator.storage --state private/state.sqlite --legacy private/orchestrator/runtime.sqlite
```

It checks database integrity, known schema, every imported row (including row order),
and all registered artifact hashes/sizes. It imports into namespaced tables in one
transaction and records `storage_migrations.production-runtime-v1`. Interrupted or
failed import rolls back; populated conflicting production tables are not merged.
An existing receipt makes the same import idempotent. Unexpected custom schema must
be reviewed rather than silently discarded. Existing relay rows are left unchanged.

The application refuses to silently initialize empty production history while an
unmigrated legacy database exists. After verified cutover, `runtime.sqlite` is retained
read-only as a historical recovery copy. The subsequent Messages consolidation
archives that inactive file with its verified snapshot under `backups/`; see
[Messages consolidation](messages-pilot.md#consolidating-older-installations).
Cleanup may remove a redundant retired copy only when the verified snapshot remains.
It is not opened by the scheduler, status reader or CLI. Future operational backups
need the single state database plus the separately stored artifact/input files.

Do not restore either old database underneath a running service or resume old code
against divergent histories. Recovery requires stopping writers and reviewing the
migration evidence and matching code/database versions together. After new work has
committed, reverting to the pre-migration copy would lose that newer history.
