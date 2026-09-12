# Updates and release notifications

Starting with 0.12.0, Task Relay has an explicit update controller for compatible
core-package releases. It supports the owned Telegram service on macOS and Linux,
plus installations run in the foreground. Version 0.12.1 adds reviewed additive
schema migrations. Separate Messages deployments, custom launchers and unsupported
data transformations are refused.

## Find an update

While Telegram is running and paired, Relay checks the repository's latest stable
GitHub release at most once every 24 hours. Only public release metadata is
requested; no task content, credentials or account identifiers accompany it.
GitHub still receives ordinary connection information such as your IP address.
Drafts, prereleases and commits without published releases are not updates.
The check requires the release's official wheel asset and its GitHub SHA-256 digest.
See the [GitHub release API](https://docs.github.com/en/rest/releases/releases).

A newer release produces one Telegram notice with its version, release notes and
update command. Notice submission is recorded before sending. A failed or lost
acknowledgement is uncertain and is not automatically retried; avoiding duplicate
notices can mean a notice is missed. The CLI and doctor remain available to check.
Failed checks preserve cached metadata and wait until the next daily attempt.

```sh
task-relay update check
task-relay update status
task-relay doctor
task-relay update notifications off
task-relay update notifications on
```

`check` explicitly contacts GitHub. `status` and `doctor` read local cache only;
errors and stale information remain visible. Turning notifications off disables
automatic release checks as well as notices. It does not prevent an explicit
`update check`. The relay must be running for automatic checks; there is no separate
always-running updater.

## Install a selected release

Read the linked release notes and finish or cancel unfinished work first. Then
select the exact published version, replacing the example below:

```sh
task-relay update apply --version 0.12.1
```

This command explicitly authorizes downloading and activating that release. Relay:

1. Downloads only the official release wheel, verifies its digest and package
   identity, and installs it into a separate environment. The previous environment
   remains intact. Core dependencies must remain empty; optional integrations keep
   their separate runtime requirements.
2. Checks the update compatibility protocol, unchanged retained runtime files,
   data/project/output bindings, unfinished or uncertain execution and pending
   delivery. Saved buttons and completed upload/dispatch receipts stay unchanged
   and do not count as running work. Unknown execution states are refused. Resolve those records through normal task controls;
   never edit their database status to bypass the check.
3. Stops the owned Telegram service, acquires relay/setup locks and checks again
   for work that arrived during preparation. It takes a consistent SQLite backup
   and tests candidate initialization on a disposable copy. A schema change needs
   the exact reviewed migration plan described below; ordinary updates still
   refuse data or schema changes.
4. Replaces the owned service definition while retaining its path bindings. The
   new process reports readiness before provider workers start. Successful
   activation releases this startup gate. Startup failure restores the previous
   definition and code; it does not restore an older database.

A foreground relay must be stopped before activation; the controller does not kill
an unrelated process or start a service where none existed. Inactive owned services
remain inactive. Existing installed CLI launchers forward to the selected runtime,
so their commands keep working. Source-checkout commands retain their explicit
checkout context. Stop independent CLI workers before switching; the updater is
not a supervisor for unrelated processes using the data directory.

Preparation can be retried after interruption. Release environments live beside
application data in a `task-relay-releases` directory by default. Keep both the
original installation and retained release environments while they are referenced.
There is no automatic background download, installation or deletion of old code.

## Review and apply an additive migration

Use a migration-capable controller (0.12.1 or newer) and SQLite 3.35 or newer.
Replace `VERSION` with the exact published release and `PLAN_ID` with the full ID
printed by the plan command:

```sh
task-relay update plan --version VERSION
task-relay update apply --version VERSION --migration-plan PLAN_ID
```

Planning downloads and prepares that selected release, then runs its initialization
on a private disposable database copy. It does not stop services, alter the live
database or authorize an update. It displays forward/reverse SQL and stores a plan
bound to both code versions, schema and original data/project/output paths. Treat
plans and snapshots as private operational evidence.

This first scope supports new empty ordinary tables, indexes on those tables, and
nullable columns without defaults. It proves that the proposed operations reproduce
candidate initialization while preserving every existing row and row identity, and
that reversing them restores the original logical database. Seeded tables, record
rewrites, replacement/removal of existing schema objects, new triggers, virtual
tables and incompatible constraints need separately implemented migrations.

Applying the exact plan rechecks it against current data after stopping the owned
service and taking the update/bridge/setup locks. An intervening schema change or
initializer that now rewrites a row blocks application. SQLite commits the schema
and an immutable migration receipt together; the service remains gated until
activation commits. An interrupted switch uses that receipt to distinguish an
uncommitted transaction from a committed migration. Recovery reverses only the
recorded operation and retains its evidence; it never restores an old database.

To reverse a migrated release, use its plan ID shown by `update status`:

```sh
task-relay update rollback --migration-plan PLAN_ID
```

Reversal preserves newer records in existing columns. If a new table has any rows
or an added column contains any non-NULL value, rollback is refused before switching
services. Relay will not discard those values or infer permission to rewrite them.
A future data conversion must define how to preserve that information. The same
condition can block recovery after an unrelated writer changes the database; keep
independent workers stopped throughout an update. Receipt rows remain in
`relay_update_migrations` after reversal.

## Rollback and interrupted activation

```sh
task-relay update rollback
task-relay update status
task-relay update recover
```

`rollback` selects the retained previous code, repeats the idle/compatibility
checks and keeps current task data, including decisions made after the update.
For a migrated release it also requires the explicit plan ID and the lossless
reversal checks above.
A changed retained environment, unfinished work, or incompatible initialization
blocks rollback. The updater's protocol is also a compatibility declaration by
the release author; a snapshot initialization check cannot prove every possible
application behavior is compatible.

`recover` handles an activation interrupted before it committed. It restores the
recorded prior service selection and preserves current data. If activation may
already have committed, automatic rollback is not attempted: inspect `status`.
An active selection requires an explicit `rollback`, with fresh checks. Edited
service definitions require manual recovery rather than overwriting local changes.

Receipts, readiness records and private backups are under the application data's
`updates/` directory. Release-check state is in `updates.sqlite`; notification
preferences are in `update-preferences.json`. They contain local operational state
and do not belong in Git. Backups are recovery evidence; automatic rollback never
copies them over newer task history.

## Installations older than 0.12.0

Older installations do not have the update controller. Bootstrap once using a new
source-install environment. Preserve the original installation and use `paths` to
keep the same data/project/output bindings. After work is idle, remove the owned
Telegram service using the old installation's `telegram uninstall`, then install
it using the new environment's `telegram install`. Both commands retain data.
Source-to-package moves require deliberate path overrides; switching paths does
not migrate a database. Separate Messages installations are outside this updater.

## Moving from the 0.12.0 controller

The 0.12.0 updater uses protocol 1. Install 0.12.1 or newer into a separate source
installation/environment and invoke that environment's `task-relay update` command
with the same explicit path bindings. Keep both environments. If an active update
receipt already identifies the old service/code, the new controller retains that
identity for a compatible code-only switch. Both sides of a schema migration
must already use protocol 2: first activate the migration-aware baseline without
schema changes, then plan a later release migration. This prevents the original
controller from restoring old code after a partially committed migration. If no receipt exists, use the manual service
bootstrap described above to establish the new controller first.
An unfinished protocol 1 activation must be recovered with its original controller
before moving on. The new launcher is required once protocol 2 code is selected;
the 0.12.0 launcher refuses that protocol instead of attempting an unsafe recovery.

## Publishing a release

Maintain matching versions in `pyproject.toml` and `task_relay/releases.py`, and
update [release notes](release-notes.md). The compatibility protocol must change
when data semantics or the update/startup contract become incompatible. The
migration-aware controller uses protocol 2. Protocol 1 controllers refuse protocol
2 releases; they must never perform migration recovery. A protocol 2
controller can retain and restore recorded protocol 1 code after checking its
compatibility. Install the new controller before selecting a protocol 2 release.

Push a reviewed `vMAJOR.MINOR.PATCH` tag. The release workflow runs the relevant
controlled tests on macOS and Linux with Python 3.11, verifies version identity,
builds distributions and creates a **draft** GitHub release. Review its notes and
assets, then publish it as a stable release. Users are notified only after
publication and only when their running version is older. Publication is separate
from merging code or creating a tag. Published version identities must not be reused
for different runtime bytes; issue a new version for a fix.
