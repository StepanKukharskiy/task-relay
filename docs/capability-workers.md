# Capability-driven workers

Updated 2026-10-02 against source 0.13.152. Capability-driven workers were first
included in local 0.13.24; the current registry includes 19 profiles across files,
Python, browser and Safari execution. [Execution providers](execution-providers.md)
lists the exact profile IDs and bounds. The [roadmap](../ROADMAP.md) separates
source, installed and live qualification; no blanket live-provider claim follows
from registration. Installation does not approve or dispatch a workflow.

The planner creates roles and assignments for each request. It can now specify a
different worker for each task using requirements from a captured executor catalog.
The five bundled starters are versioned planning examples; they do not require five
domain-specific worker implementations.

An agent task can include:

```json
{"worker":{"requires":["files.text","code.execute"]}}
```

The task still declares its role, objective, instruction, exact versioned inputs,
outputs, dependencies, review criteria, independent deadline and attempt limit.
An optional `worker.executor` selects one captured executor ID. Relay supplies the
exact backend/model and tool profile; model responses cannot insert a backend,
command, endpoint, or permission into the worker binding.

## Selection and execution

- `files.text`: declared text work.
- `images.view`: visual inspection of declared local image pixels, currently
  advertised by `codex-cli`. PNG capture or Python image statistics do not satisfy it.
- `files.binary`: binary file work through an existing file/code adapter. This does
  not certify any particular format library, visual reviewer or application.
- `code.execute`: the selected code adapter: existing Codex shell access or the
  verified native Python sandbox. Their different limits and permissions remain
  explicit; Python does not provide a shell or native application access.
- `browser.use`: the existing browser adapter, requiring an explicit browser
  contract. A browser worker is never selected merely for text work.
- `browser.capture`: explicitly granted viewport PNG captures and provenance,
  including metadata-only PNG inputs. This does not grant visual image reasoning.
- `computer.use`: owned Safari observe/navigate/scroll with an explicit native
  session and URL contract. The background scripting and foreground observation
  transports have distinct permissions and ownership rules. See [Computer Use](computer-use.md).

Automatic resolution selects the narrowest compatible capability set, then prefers
the default provider family among equally narrow choices and avoids a general
Codex shell when a narrower adapter suffices. It does not rank guessed cost or
invent model choices. Explicit executor choices have no fallback. A user-named
production executor locks the catalog for that scope. Clarifications retain captured choices;
old saved planning scopes without the catalog cannot gain dynamic permissions.
Binary files cannot be assigned to declared-text API workers. Provider profile
limits and the stage's existing ceiling both apply, without silently raising either.

Resolved bindings become part of the hashed plan, immutable assignment and dispatch
receipt. Cards show each worker's model, tools, requirements and external transfer.
Status uses the assigned model even before the worker starts; token counts remain
based on actual receipts, with missing counts unknown.

Start and dispatch recheck the exact selected executor. A disconnected or stale
executor blocks without selecting another provider. Restart observes the existing
attempt; it does not resolve a new worker or replay an uncertain submission.
Automatic script repair retains the original review worker's backend. Existing
plans without worker bindings keep their original single-backend behavior.

Whole-workflow intent continues to cover existing bounded work. A production that
proposes a worker backend different from its default needs an explicit stage Start;
the workflow cannot silently expand provider transfers. This first implementation
does not add a persistent multi-provider auto-approval policy.

## Starter requirements and remaining integrations

| Starter | Requirements |
| --- | --- |
| Research/report | Research route, text authoring, code/document tooling when exporting |
| Architecture/presentation | Research, text concepts, requested Rhino or Blender operations, reference-image generation, editable PPTX |
| Model revision | Matching native inspection, script/check authoring and validation, exact-approved native execution |
| Carousel/reel | Text/asset adaptation and a separately verified composition/render environment |
| Data/presentation | Code/data libraries, reproducible analysis, editable PPTX |

`browser.research`, `image.edit`, `native.model`, `native.inspect` and `media.compose`
in starter definitions describe stage requirements. They are not arbitrary worker
capability IDs. The planner maps research and image requirements to their existing
routes and native requirements to the requested registered operation. `media.compose`
still requires a qualified environment; neither shell access nor video generation
proves that a complete editable reel can be produced.

The supported profiles include Codex file/shell, Gemini/OpenAI/Qwen/DeepSeek/
OpenRouter declared files, verified native Python and Safari workers, and
Gemini/OpenAI/Qwen scoped browser workers. See [shared code workers](shared-code-workers.md) for the bundled
document checks and current macOS-only code isolation. New tools still need
integration and availability checks. Native execution, generation
providers and PPTX creation remain registered operations, preserving their exact
input and approval contracts. No application installation, licensing, provider
configuration, media generation, or message delivery happens during resolution.

`web.research` and `geometry.modify` are possible future semantic abstractions,
not current registered worker capability IDs. The existing capability catalog
must be used as it stands; a provider-neutral request cannot remove an operation's
format validation, side-effect grants, evidence requirements or explicit user
provider choice. Relay's MCP server exposes work state to clients; it does not
currently consume arbitrary external MCP servers as executors.
