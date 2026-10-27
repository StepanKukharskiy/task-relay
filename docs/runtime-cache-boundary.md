# Runtime dependencies and derived caches

Prospective private runtime snapshots use manifest version 2. Source, shared
libraries, executables, package metadata, links and unknown files retain exact
hash/identity checks. Only a regular `__pycache__/name.<tag>[.opt-N].pyc` with a
regular retained sibling `name.py` is derived. Such caches are omitted from the
copy and dependency inventory; sourceless bytecode and cache symlinks are not
exempt. Version 1 receipts still use their original complete inventory and are
never upgraded in place.

Ignoring caches alone would allow stale or poisoned bytecode to execute. The
shared `runtime_process` boundary supplies `-B -X pycache_prefix=<host null device>`
to the controller, supervisor, agents, registered steps, isolated code and other
Python host helpers. The null device cannot hold a cache tree, so imports use
retained source and generate no disk bytecode. Explicit flags also work with
`-I`, which ignores Python environment variables. The equivalent environment
propagates to ordinary descendants. A version-2 native identity binds the shared
process-policy source hash as well as its snapshot. Runtime/controller admission
requires the intended process policy. Native isolation grants are unchanged.

`controller_launch` owns the exclusive launch claim and at most one restart.
Only exit 75 with a newly committed matching run receipt permits that restart;
missing/foreign receipts, other exits and existing launch/restart evidence do not
permit replay. It preserves command, exit and restart-receipt hashes in an
append-only journal. Controller verification runs again on restart; completed
work and worker identities remain in the existing scheduler database.

Qualification must run this launcher and real controller/supervisor/worker
subprocesses with the private interpreter, including an outer launch without
inherited `-B`, a cache appearing before restart, and retained text delivery with
one dispatch. Poisoned-cache controls prove that normal Python can execute the
cache while the shared source-only path reads source. Source/binary changes and
unexpected files must still reject. Controlled transports do not establish live
Codex quality, browser accessibility or full pipeline acceptance. The current
installed host qualification is macOS; this does not assert Windows isolation.

Original AW incident records remain unchanged. Its failed controller and
uncollected terminal worker results are not rescued or promoted by a fresh run.
