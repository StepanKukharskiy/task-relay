# Task Relay

Use `ROADMAP.md` for milestone scope and order. Continue authorized work; do not
turn deferred milestones or unrelated acceptance exercises into prerequisites.
Update the affected roadmap status and `CHANGELOG.md` when behavior changes.

Preserve exact user requests, artifact versions, decisions, executed assignments
and recovery receipts. Keep database mutations atomic and external dispatch after
commit. Never infer acceptance, duplicate uncertain submissions, or silently
expand a stage's authorization. Keep OS-specific behavior behind host adapters.

Run only tests needed for the changed behavior and its affected integrations.
Use small text fixtures for orchestration, delivery identity and recovery tests.
Do not rebuild videos, generate media, exercise browsers or run unrelated suites
unless that capability is part of the task being changed. Add regression tests
for meaningful failure/recovery behavior, not assertions that mirror the code.
After relevant checks pass, repeat or broaden testing only for new changes,
failures or unresolved concerns.

Record only checks actually run: command, scope, result and relevant limitations.
Keep logs under `outputs/` and distinguish controlled tests from deployed checks.
Do not claim a service was reloaded, a provider ran or a message reached the user
without evidence. Code changes alone do not authorize live messages or paid work.

Public source must pass `python3 scripts/check_publication.py --staged` before
commit. Keep personal research and installation records in ignored private storage.
