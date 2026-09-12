# Changelog

## Unreleased — public product baseline

- Published product documentation, portable setup instructions and an explicit
  source/distribution inventory. Personal research, installation records and
  one-time migration/replay programs are kept outside the public repository.
- Added a publication check for excluded files, personal home paths, credential
  signatures, personal runtime identifiers and links into private evidence.
- Messages first setup now requires an explicit task ID; subsequent starts reuse
  the saved task. Diagnostic launchers ask for the current pairing code. Existing
  pairing and execution records remain authoritative.
- Native launch wrappers resolve Python from the user's environment instead of a
  particular local framework installation.

## Packaged runtime — 0.11.0 development series

- Packaged application and orchestration modules, CLI entry points and maintained
  assets. Centralized data/project/output paths with explicit overrides.
- Added host interfaces, private-file/environment/Keychain credential sources,
  declared read/edit grants and frozen worker-support identities.
- Added optional Linux systemd user-service management with activation rollback.
  POSIX cancellation handles an exited parent and resistant descendants.
- Added native Linux text-runtime and Windows installed-boundary CI profiles.
  Windows task execution and native provider/delivery qualification remain open.
- Implemented bounded planning, worker handoffs, output decisions, mixed execution,
  artifact dependency/replacement records and usage reporting.

See [the roadmap](ROADMAP.md) for scope and [native qualification](docs/native-qualification.md)
for platform evidence. Development-series versions do not imply production readiness
or qualification of every provider, channel and application adapter.
