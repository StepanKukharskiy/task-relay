# Prompt, model response and Relay reaction audits

Each execution keeps its original provider request/response/outcome files,
tool-call arguments and receipts, frozen assignment, and controller events.
Codex additionally records native thread instructions, the actual incremental
sent/event streams, and reported cumulative usage. Preserve these original worker
folders, including failures; an index is not a replacement backup.

The read-only `scripts/export_execution_audit.py` command builds a chronological
index without dispatching work or changing the execution database:

```
python3 -B scripts/export_execution_audit.py --database DATA/state.sqlite --workers DATA/orchestrator/workers --output PRIVATE/audits --run RUN_ID
```

Use `--run-prefix PREFIX` instead of `--run` to index related trials together.
Every export creates a new Markdown/JSON observation; `LATEST.md` points to the
latest observation, and the top-level `INDEX.md` retains other indexed runs.
Reports contain:

- Exact request envelopes with system instructions, supplied context and tools.
- Returned model text/tool calls, with links to complete raw responses.
- Relay's tool results, rejection reasons, correction and recovery receipts.
- Original controller event IDs, timestamps, tasks, attempts and event data.
- Native CLI wire journals and registered research/operation records.

File hashes identify observed bytes. Active streams may grow after export; a
later export records the new observation while retaining earlier index files.
Source journals remain authoritative and must be retained separately. Missing
responses remain missing; they are not reconstructed and do not imply zero usage.
Provider-private instructions or internal inference that the provider did not
expose are outside the observable record. These exports do not grant replay,
resolve uncertainty, or establish acceptance.

Two focused checks cover exact evidence hashes, model output/rejection links,
controller events, native streams with a partial final line, uncertain/missing
responses, registered search records, immutable prior observations and read-only
database behavior. No live provider or browser is used by the exporter.
