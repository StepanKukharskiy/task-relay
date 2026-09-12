# Task Relay 0.12.1

- Review additive SQLite migration plans before applying a selected release.
- Commit schema changes and migration receipts atomically; reverse them only when
  newer data can be preserved. Record rewrites and destructive conversions remain
  unsupported.
- Recover interrupted migration/service switches without replaying work or
  restoring an older database over newer decisions.

This version uses update protocol 2. Existing 0.12.0 users need the documented
controller bootstrap. These changes are unreleased until a corresponding stable
release is published. The desktop launcher is planned, not implemented.

Separate Messages updates, native Linux service-switch qualification and live
provider/delivery qualification remain open. See [update instructions](https://github.com/StepanKukharskiy/task-relay/blob/v0.12.1/docs/updates.md)
and the [roadmap](https://github.com/StepanKukharskiy/task-relay/blob/v0.12.1/ROADMAP.md).
