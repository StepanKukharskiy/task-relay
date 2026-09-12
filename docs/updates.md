# Updates and release notifications

Starting with 0.12.0, Task Relay has an explicit update controller for compatible
core-package releases. It supports the owned Telegram service on macOS and Linux,
plus installations run in the foreground. Separate Messages deployments, custom
launchers and changes requiring data/schema migration are refused.

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
   and tests candidate initialization on a disposable copy. Any logical data or
   schema change requires explicit migration and blocks activation.
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

## Rollback and interrupted activation

```sh
task-relay update rollback
task-relay update status
task-relay update recover
```

`rollback` selects the retained previous code, repeats the idle/compatibility
checks and keeps current task data, including decisions made after the update.
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

## Publishing a release

Maintain matching versions in `pyproject.toml` and `task_relay/releases.py`, and
update [release notes](release-notes.md). The compatibility protocol must change
when data semantics or the update/startup contract become incompatible. Current
updaters reject another protocol; migration tooling must precede such a release.

Push a reviewed `vMAJOR.MINOR.PATCH` tag. The release workflow runs the relevant
controlled tests on macOS and Linux with Python 3.11, verifies version identity,
builds distributions and creates a **draft** GitHub release. Review its notes and
assets, then publish it as a stable release. Users are notified only after
publication and only when their running version is older. Publication is separate
from merging code or creating a tag. Published version identities must not be reused
for different runtime bytes; issue a new version for a fix.
