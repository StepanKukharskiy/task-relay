# Host, credential and access adapters (O11)

The common application imports without Messages, launchd or a Unix locking module.
`task_relay.host.Host` selects mechanisms at use time. Unsupported operations fail
before starting a process or opening project files. `task-relay host` describes
the selected host and its qualification boundary; it performs no installation.

## Host mechanisms

| Operation | Implemented boundary |
| --- | --- |
| Telegram service lifecycle | macOS adapter retains existing launchd paths, configuration ownership, data-root refusal and reload rollback |
| Messages lifecycle | Optional macOS entry point delegates launchd operations to the host; the existing signed app remains unchanged |
| Worker discovery | Explicit `TASK_RELAY_CODEX`, then PATH, then macOS app locations; an invalid override fails without fallback |
| Process ownership | POSIX sessions/process groups, bounded termination then forced cancellation, and process identity inspection |
| Locks / desktop IPC | Lazy POSIX flock and Unix socket adapters; unavailable mechanisms report a host blocker |
| Paths | Existing checkout data roots and wheel defaults preserved; environment interpreter paths selected by host |

Native macOS behavior and the bounded Linux text-runtime profile are checked.
Linux has optional systemd user-service management, with native service activation
still open. Windows installed imports and unavailable-operation boundaries pass
on a native runner; process-tree, locking, credential ACL and junction/reparse-point
enforcement remain unavailable. O12 remains in progress.

Each newly frozen worker assignment records hashes of host/access/credential support.
The supervisor receives a frozen copy of its host process implementation and checks
its hash before startup. Agent/procedure workers reject changed support before
using it. Existing assignments, submissions and recovery receipts are preserved;
there is no retry or authority expansion when a support check fails.

## Credentials

Provider and Telegram code resolve secrets through `task_relay.credentials`.
Existing configured JSON files retain their explicit private-file source and are
not migrated or rewritten by this change. Credential files must be owned by the
service account, mode 0600, regular and unlinked. Reads walk directory descriptors
without following links; writes use the same host boundary, exact file scope,
owner-only temporary files and atomic replacement.

Configuration can select `api_key_ref` (or `token_ref` for Telegram) instead of an
inline secret. Supported references are:

```json
{"source": "environment", "name": "MY_PROVIDER_KEY"}
{"source": "private-file", "path": "/absolute/private/provider.json", "field": "api_key"}
{"source": "macos-keychain", "service": "task-relay.provider", "account": "my-account"}
```

A reference is authoritative. Missing environment variables, denied/locked Keychain
items, unsafe files or unknown sources fail without using an old inline key or
another source. Environment references must exist in the actual service's
environment; terminal configuration alone does not establish background availability.
Catalog refresh/enable preserves a reference. Explicit new-key setup selects the
existing private-file storage path. There is no automatic Keychain migration or
plaintext fallback from a failed reference.

`task-relay credentials PROVIDER` reports availability/source and allowlisted public
settings, never secret values or references. Keychain resolution is implemented and
has controlled missing/locked/unsupported checks; live Keychain access was not
selected or exercised. The running services continue using their original private
configuration files. New credential sources need service-account verification when
selected. Provider/account authorization and paid calls are separate from resolution.

## Explicit filesystem grants

`filesystem.Grant` binds an absolute root, authority, allowed read paths and exact
editable output paths. The host filesystem implementation enforces it at each open
or write, with no-follow directory descriptors, traversal and protected-path checks,
regular-file checks and hard-link rejection. Output parent creation and atomic
replacement stay beneath the granted root. Unsupported hosts stop before access.

Selected project roots already supplied by configured tasks and project discovery
become read-only grants for direct project tools. Hidden/private file exclusions
remain in those tools. A caller can supply a narrower `Grant` to `Workspace`; its
root must match the selected project. A model's path argument cannot grant another
root or make a read-only tool editable.

Gemini execution derives its grant from the exact frozen assignment: declared
inputs and already-written outputs are readable; only declared output paths are
editable. Input hashes, output bounds and receipt rules remain in force. These
grants do not authorize new projects, change recorded user decisions or move data.

These are enforced boundaries for Relay's direct file operations and the declared-
file worker. Codex shell execution retains its native workspace-write sandbox,
which permits additional temporary writes and does not provide confidential read
isolation or exact-file grants. Its catalog and frozen capabilities explicitly
report that limitation. Exact-code host-approved application operations retain
their separately recorded unrestricted-host authorization. Neither is silently
treated as confined by the in-process file adapter. Channel-based project/grant
setup remains O13; no live project authorization was added here.

O12 adds optional Linux systemd user-service management and cancellation after a
parent exits. See [native qualification](native-qualification.md) for evidence,
foreground operation without systemd and the remaining Windows implementation.
