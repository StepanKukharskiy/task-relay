# Token usage tracking

Reports cover local Codex and Claude sessions plus recorded Relay API calls,
including work started outside Relay. Reading usage does not call a model or send
session content to a service.

## Read a report

In the paired Telegram chat:

```text
/usage
/usage 30 model
/usage 7 project
/usage 30 day
```

The default is seven UTC calendar days, grouped by provider. Commands read the
cached ledger and show source freshness and incomplete coverage. Up to 20 groups
are shown in chat. The CLI provides the full report:

```sh
python3 usage_tracker.py --days 30 --group model --json
python3 usage_tracker.py --refresh --days 7
python3 usage_tracker.py --enable
python3 usage_tracker.py --disable
```

The native desktop Tasks tab shows recorded usage through Task Relay separately
from the wider indexed local total. Its direct API-task number is a subset of
Relay usage, which also includes planner/chat calls and managed workers. The
app reads the ledger; Refresh does not call a provider or import new logs.

Enable/disable controls background indexing; disabling retains recorded usage.
The installed Relay must contain this worker for background indexing to run.
`--refresh` explicitly performs one bounded import, regardless of that switch.
`--max-bytes 250000000` increases a manual local-log read budget; each file is
limited to about 8 MB per pass and a line can exceed the budget by up to 1 MB.
Repeat refreshes to advance a large archive. `--relay-only` skips local-log
refresh; it does not remove previously indexed local records from the report.

The worker uses its own database connection and refreshes every 30 seconds, with
a 32 MB local read budget. A large first import can take many hours. Reports do
not wait for it. No daily message or usage alert is sent automatically.

## Sources and storage

- Codex: `sessions/**/*.jsonl` and `archived_sessions/**/*.jsonl` under
  `CODEX_HOME`, or `~/.codex`. Session/model/project metadata and cumulative token
  counters are read incrementally. Repeated counters are ignored. Identical
  archived/copied events are deduplicated by timestamp, project and counter
  fingerprint. Fork baselines and counter resets are skipped when fresh usage
  cannot be established; affected totals are lower bounds.
- Claude Code: `projects/**/*.jsonl` under `CLAUDE_CONFIG_DIR`, or `~/.claude`.
  Assistant request/message identities deduplicate streaming fragments. The
  largest observed total for each identity is retained. Missing log sources are
  reported explicitly.
- Relay: recorded OpenAI, Qwen, DeepSeek, OpenRouter and Gemini API responses;
  orchestrator conversations/searches; planner calls; production worker receipts;
  and new Claude SDK results. Existing Claude jobs without saved token counts
  remain unmeasured. Messages provider calls use the same main database and
  collector. Consolidation rebinds historical usage identities so those calls are
  counted once. A selected model without a recorded call does not appear as zero usage.

The ledger, source health and byte cursors are new tables in the **existing
`PATHS.state` database** (currently `private/state.sqlite`). There is no additional
usage database. Local logs and original Relay receipts remain untouched. The
ledger stores usage counts, timestamps, identities, model and project paths, and
reported costs; it does not copy prompts, completions or keys. Normal private
database backups include it.

## Interpretation and limits

Input includes cached reads; Claude cache creation is also included in normalized
input. Output includes reasoning where the provider supplies that breakdown.
Cached input, cache writes and reasoning are subsets, not extra tokens to add to
the total. The JSON report preserves these breakdowns. Missing fields remain
`null`; an empty log source is different from measured zero usage.

Relay receipts take precedence over local logs for managed sessions with known
usage, avoiding a second count of the same work. This is session-level matching:
additional local activity in the same managed session may be omitted. Native
worker receipts without session identity cannot be reliably matched. Project
grouping uses available attribution: a filesystem project for local sessions,
or a saved focus/run for some Relay calls. Missing attribution is explicit.

Dates use recorded event/assignment timestamps in UTC. Historical per-call
timestamps are not available for every Relay backend, so some steps use the
job's start time. Undated usage is counted separately and excluded from dated
totals. Logs missing usage fields, rewritten history and incomplete backfills
limit accuracy. Source warnings appear in reports.

This is **local recorded activity**, not an account-wide bill or remaining
subscription quota. Provider-reported costs and Claude SDK usage values are
shown separately; SDK values are not subscription charges. No prices are guessed.
API calls made by unrelated applications, cloud-only sessions, image/video tool
charges without receipts, and provider billing exports require further adapters.
The CLI and Telegram command are implemented; an Apple Messages `/usage` command,
natural-language usage tool and budget alerts are not implemented by this change.
