# Portable core and host adapters

Status updated 2026-09-12: O11 host/access/credential interfaces are implemented
within the [documented adapter boundaries](host-adapters.md). Native Windows/Linux
qualification and clean-host installation remain O12/O13; they are not established
by macOS or mocked checks.

## Product contract

One Task Relay codebase must run on macOS, Windows and Linux. The LLM interprets
intent and selects supported tools/actions. Shared code validates and records those
decisions. Host adapters provide OS-specific mechanisms. The model should see actual
host capabilities, not decide which operating-system command is safe to invent.

The initial common interface is Telegram. Apple Messages, menu-bar UI and desktop
application hooks are optional platform integrations. They must not be prerequisites
for starting the core, connecting an API provider or running an eligible CLI worker.
Local operation on any supported OS does not imply distributed multi-machine execution.

## Boundaries to introduce

| Interface | Responsibility | Proposed implementations / qualification |
| --- | --- | --- |
| Paths | Resolve config, state, artifacts, workspaces, cache and logs | OS-appropriate user directories with explicit overrides; preserve current paths during migration. |
| Credentials | Resolve a provider's secret reference without putting the key into LLM context | macOS Keychain, Windows credential storage, Linux Secret Service where available. Headless installations need an explicit supported secret source; no silent plaintext fallback. |
| Service lifecycle | Install, start, stop, status, upgrade and uninstall | macOS launchd; Windows service/task adapter to qualify; Linux user-service adapter where supported, plus foreground operation. No assumption that every Linux host runs systemd. |
| Process supervisor | Spawn workers with arguments, capture outputs, cancel process trees and recover receipts | Native POSIX and Windows implementations; do not translate Unix signals mechanically. |
| Filesystem access | Enforce granted project roots and read/edit scopes | Preserve protections against path escapes, links and race conditions, with native Windows junction/reparse-point handling. A string-prefix check is not an equivalent replacement. |
| Locking / IPC | Single-instance ownership and optional local desktop transport | Native mechanisms per host. The core must import without Unix-only modules. |
| Worker discovery | Locate a compatible executable and its supported protocol | Explicit configuration or executable discovery/version checks; no `/Applications/...` assumption. |
| Channel / desktop integration | Pairing, messaging and optional app control | Telegram shared; Apple Messages/macOS app launcher optional; report unsupported capabilities explicitly. |

A common config file may contain provider settings and credential references.
Whether a key comes from a native store or an explicitly selected private file is a
credential-adapter concern. Presence of a key makes a configured provider available;
it does not authorize switching providers or launching requests. Store access must
be tested in the actual background-service account/session, including locked or
missing stores. Custom encryption with a master key beside the ciphertext is not
the default design.

## Pre-O11 blockers (historical findings)

- `bridge.py` imports `fcntl`, uses flock, installs LaunchAgents and integrates with
  local desktop IPC/application bundles. Service and desktop hooks are mixed into
  the Telegram/core entry point.
- `file_tools.py` opens `/` and walks directory descriptors with `O_NOFOLLOW`,
  `O_DIRECTORY` and `dir_fd`; it needs a qualified Windows equivalent.
- `orchestrator/workers.py` defaults to a Codex binary inside a Mac app bundle.
- `orchestrator/supervisor.py` cancels POSIX process groups with signals.
- Finder `.command` wrappers depend on zsh and a machine-specific Python framework.
- Storage and assets are often resolved relative to source modules. Moving files
  into a package without a path abstraction would also move their expected data roots.

These are substantive portability issues. Using Python and SQLite alone does not
make the existing application platform-independent.

## Delivery approach

1. Establish package boundaries and a shared path/config interface as part of the
   [structure migration](project-structure.md), preserving the working Mac install.
2. Extract host-dependent operations behind small interfaces. Implement the Mac
   adapter first against existing behavior; core imports must not require it.
3. Qualify Windows and Linux adapters. Exercise path encoding, spaces, drive/UNC
   roots, case behavior, link escapes, file replacement/locking and cancellation.
4. Package one application CLI with OS-appropriate one-command bootstraps. Install
   only the required runtime and selected integrations; later setup uses the paired
   channel, with local interaction for required OS permissions or secret entry.
5. Use native CI and clean-host acceptance for install, task execution, delivery,
   restart/recovery, cancellation, folder enforcement, upgrades and uninstall.

Keep one workflow/database/artifact format across hosts. Absolute local paths belong
to host-specific bindings; moving work between hosts requires explicit rebinding and
file transfer, not interpreting a saved Mac path as a Windows path. Do not promise
unqualified provider/platform combinations or claim native coverage from mocked tests.
