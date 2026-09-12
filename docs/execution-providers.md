# Bounded execution providers (O04)

The shared runtime supports Codex CLI and Gemini agents. Gemini executes through
its own API and supervised Python process; it does not require the Codex binary.
Registered O06 operations remain separate: `gemini.text` makes one tool-free text
request, whereas `gemini-agent` runs a bounded file-tool loop.

| Profile | Supported work | Bounds per assignment |
| --- | --- | --- |
| `codex-cli` | Existing files/shell assignments, fixed model and reasoning | Existing declared limits and Codex sandbox |
| `gemini-agent` | Read exact declared UTF-8 inputs, write exact declared text outputs, submit a delivery or independent review report | At most 600 seconds, 24 tools, 200,000 output bytes, 512,000 input bytes, eight API requests, 4,096 output tokens per request |

Gemini has no shell, browser, application, messaging or arbitrary filesystem tool.
Descriptor-based file access refuses symlink parents, linked inputs and paths
outside the declaration. Input hashes are checked before any API request and by
the shared runtime when collecting results. Outputs are retained as versioned
artifacts, including partial output from a confirmed interrupted worker. This
bounds model tool authority; the trusted Python process itself is not a separate
OS security container.

## Choice and connection eligibility

`plan_production` accepts optional `executor: "gemini-agent"` or `"codex-cli"`
from `snapshot.capabilities.graph_executors`. The chosen backend/model and tool
profile are frozen into the plan and shown before approval. Clarifications and
next stages retain the prior backend unless the user explicitly changes it.
The existing default policy is preserved. Unsupported shell/binary work cannot
be submitted to the file-only Gemini profile, and unavailable providers never
silently fall back to another provider.

Gemini requires a recent successful read-only `models.get` check for its configured
text model. The private receipt is tied to the model and credential fingerprint,
expires after 15 minutes, and is invalidated before a refresh. Availability is
checked at catalog publication, planning, approval and dispatch. A disconnected,
changed or stale connection blocks the step. Model metadata establishes connection
and model eligibility; it does not guarantee generation quota or billing access.

Refresh through `/providers → Gemini → Check connection / refresh models`, or:

```sh
python3 -m orchestrator.executors verify-gemini
```

The check generates no content. Refreshing permits retrying approval of the same
saved plan; it does not restart a blocked or uncertain attempt automatically.

## Receipts and recovery

Each attempt uses the existing supervisor, cancellation signal, timeout enforcement,
artifact collection and review/user-decision gates. Every API request has a durable
intent written before transport and a separate response/outcome file. Each local
tool has an arguments/result receipt. Provider response IDs and usage are retained;
unknown monetary cost stays unknown. Full model response parts, call IDs and thought
signatures are preserved in subsequent requests.

A missing response after a request intent is uncertain. Local process termination
and upstream request outcome are distinct: cancelling a worker stops local tools
but cannot undo an accepted remote request. Runtime restart observes the existing
session; it never replays an uncertain request or switches providers. A terminal
uncertain API request retains that state without pretending a child is still running.
Validation errors in received tool/report calls may be corrected within the same
frozen request/tool budgets; they do not allocate another worker attempt.

## Evidence and limits

The adapter follows the official [function-calling API](https://ai.google.dev/gemini-api/docs/generate-content/function-calling),
[thought-signature contract](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)
and [model metadata API](https://ai.google.dev/api/models).
