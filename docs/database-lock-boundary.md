# Shared database observation and write boundary

Record observations must not acquire a SQLite writer lock. Progress, complete
record verification, projection reads and continuation diagnosis use explicit
read transactions on the existing shared store. Standalone observation opens
mode=ro; a missing database is an error, never a new authority.

A WAL reader can retain a snapshot while another connection commits. Promoting
that snapshot with BEGIN IMMEDIATE can produce SQLITE_BUSY_SNAPSHOT immediately,
even with a busy timeout. Waiting or blindly replaying the whole caller is not a
safe remedy: it can duplicate a committed operation or reuse stale authority.
Keep observation read-only and revalidate actual mutations inside their existing
write transaction. Submission/amendment/import retain BEGIN IMMEDIATE, unchanged
timeouts, exact request keys, revision checks and frozen assignments. Transient
writer contention waits before entering the body. Exhaustion preserves the error;
no new model request, retry budget or external dispatch is authorized by a lock.

Nested observations use savepoints and cannot commit an enclosing transaction.
Schema setup remains at runtime initialization. Exact bytes and original receipts
remain required for observations; read-only access grants no semantic acceptance.

Controlled contention tests and copied-history replay establish this mechanism.
They do not identify an unrecorded historical lock holder or prove live final
quality. Historical runs and uncertain effects must never be silently repaired.
