# Bounded execution providers

Updated 2026-10-02 against source 0.13.152. O04's original Codex/Gemini boundary
now includes the profile families below. The source defines 19 production
executor profiles; a particular installation advertises only eligible configured
profiles. Installation, model metadata checks and controlled transport tests do
not establish live execution for every provider/profile combination. See the
[capability inventory](capability-registry.md) and [roadmap](../ROADMAP.md) for
connections and recorded qualification.

## Production executor profiles

| Profiles | Count | Tools and work boundary |
| --- | --- | --- |
| `codex-cli` | 1 | Files/shell and declared-image inspection through Codex's native workspace-write sandbox; exact file grants and confidential read isolation are not provided by that shell profile. |
| `gemini-agent`, `openai-agent`, `qwen-agent`, `deepseek-agent`, `openrouter-agent` | 5 | Read declared UTF-8 inputs, write declared text outputs, and submit delivery/review reports. No shell, browser or host apps. |
| `gemini-code`, `openai-code`, `qwen-code`, `deepseek-code`, `openrouter-code` | 5 | Declared text/binary files and isolated Python through a verified runtime identity. No network, subprocesses, installation or host-app execution. [Code workers](shared-code-workers.md). |
| `gemini-browser`, `openai-browser`, `qwen-browser` | 3 | Scoped website actions, text/DOM observations, declared transfers and viewport PNG captures. Saved pixels are not sent as visual inputs to these workers. [Browser contracts](general-browser.md). |
| `gemini-computer`, `openai-computer`, `qwen-computer`, `deepseek-computer`, `openrouter-computer` | 5 | Safari observe/navigate/scroll with an exact session/URL contract, ownership and native receipts. Foreground and background scripting transports have different host requirements. [Computer Use](computer-use.md). |

Claude's managed account/Agent SDK tasks and Codex desktop routing are separate
connections. There is no production `claude-agent` profile in this registry.
Registered operations are also separate: `gemini.text` is one tool-free request,
and native/modeling/media operations retain their own contracts and budgets.

## Profile and assignment bounds

The current API profile ceiling is 1,800 seconds and 24 tool calls. Declared-file
profiles allow 512,000 input bytes and 200,000 output bytes. Python profiles allow
100 MB of inputs and outputs; each code call has its own 120-second bound. Browser
profiles allow 512,000 bytes of text inputs, a separate 10 MB PNG input pack and
10 MB of outputs. Safari sessions have stricter native-action/evidence limits,
including a maximum 300-second session; the worker ceiling does not extend it.
The Codex catalog ceiling is 1,800 seconds, 60 tool calls and 100 MB of outputs.
Assignments may retain lower limits and the surrounding stage's ceiling.

The shared API loop defaults to eight provider requests and 4,096 response tokens
per request. Explicit frozen budgets can permit up to 24 requests and 16,384
response tokens; they cannot be increased during execution. New code assignments
derive a missing request budget from their existing tool allowance, capped at 24;
producer responses default to 16,384 tokens and reviewer responses to 4,096.
These request ceilings are separate from tool-call, time and native-action bounds.

Descriptor-based file access refuses linked parents/inputs and paths outside the
declaration. Input hashes are checked before transport and on result collection.
Outputs remain versioned, including partial results from confirmed interrupted
workers. The declared-file adapter's trusted Python process is not itself a
separate OS security container; code isolation is a distinct host adapter.

## Choice and connection eligibility

`plan_production` accepts an optional executor from the captured eligible
`snapshot.capabilities.graph_executors`. Per-task `worker.requires` can instead
request registered capabilities, optionally naming a captured executor. See
[capability resolution](capability-workers.md). The chosen backend/model and tool
profile are frozen into the plan and shown before approval. Clarifications and
next stages retain the prior backend unless the user explicitly changes it.
Unsupported shell/binary work cannot be submitted to a declared-text profile,
and unavailable providers never
silently fall back to another provider.

Gemini verification uses read-only `models.get`; OpenAI, Qwen, DeepSeek and
OpenRouter use model catalog reads. The private receipt is tied to the exact
model, credentials and endpoint. It does not expire solely with elapsed time;
changed configuration invalidates it, and a refresh invalidates the previous
success before making its request. Availability is checked at catalog publication,
planning, approval and dispatch. A disconnected,
changed or stale connection blocks the step. Model metadata establishes connection
and model eligibility; it does not guarantee generation quota or billing access.

Refresh through the selected provider's connection controls, or run the relevant
metadata check explicitly:

```sh
python3 -m orchestrator.executors verify-gemini
python3 -m orchestrator.executors verify-openai
python3 -m orchestrator.executors verify-qwen
python3 -m orchestrator.executors verify-deepseek
python3 -m orchestrator.executors verify-openrouter
```

Run only the check for the provider you intend to use. Checks generate no content.
Browser session/site grants, native permissions and code-runtime verification are
separate checks. OpenRouter production profiles require an exact model rather
than `openrouter/auto` or `openrouter/free`. Refreshing permits retrying approval
of the same saved plan; it does not restart a blocked or uncertain attempt automatically.

## Receipts and recovery

Each attempt uses the existing supervisor, cancellation signal, timeout enforcement,
artifact collection and review/user-decision gates. Every API request has a durable
intent written before transport and a separate response/outcome file. Each local
tool has an arguments/result receipt. Provider response IDs and usage are retained;
unknown monetary cost stays unknown. Provider-native response parts, call IDs and
reasoning continuation fields, including Gemini thought signatures, are preserved.

A missing response after a request intent is uncertain. Local process termination
and upstream request outcome are distinct: cancelling a worker stops local tools
but cannot undo an accepted remote request. Runtime restart observes the existing
session; it never replays an uncertain request or switches providers. A terminal
uncertain API request retains that state without pretending a child is still running.
Validation errors in received tool/report calls may be corrected within the same
frozen request/tool budgets; they do not allocate another worker attempt.

## Evidence and limits

The original Gemini adapter follows the official [function-calling API](https://ai.google.dev/gemini-api/docs/generate-content/function-calling),
[thought-signature contract](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)
and [model metadata API](https://ai.google.dev/api/models).
Provider-specific request envelopes share the same runtime assignment, tool and
receipt contracts. OS isolation, browser availability and native application
qualification remain host-specific; the profile list is not a live-access claim.
