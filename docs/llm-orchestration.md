# LLM decisions, validated execution

Ordinary user text goes to the configured conversation model with saved state,
conversation history, project evidence and the capability catalog. The model can
answer, ask a clarification question, use the existing file/web tool loop, or return
one registered structured action. A separate runtime-owned request intake now
precedes answering/routing: the model interprets the current request in conversation
context and Relay freezes the requested outcomes before any drafting. Code validates
that interpretation and the resulting route; it does not infer intent from article
keywords or force a task per deliverable.

This change removes three language-dependent routing shortcuts:

- Guide discovery no longer runs because a message contains “create”, “update” or
  similar words. The model returns `{"kind":"discover_guides","query":"topic"}`;
  query is optional and does not replace the original request. The search visits
  at most twenty known project roots and offers at most six saved candidate guides.
  User selection resumes the same request with complete selected guide versions.
  No matches also resumes the request with a recorded result; repeat discovery for
  the same request is rejected, preventing a search loop.
- Production focus no longer hides task/capability catalogs unless the user uses
  certain handoff words. One model context includes both. Instructions explain that
  ordinary editorial feedback belongs to the focused production, while an explicit
  handoff can share an unreviewed draft without accepting or advancing that run.
- Research source identities are never guessed from “two” or the catalog size.
  With a nonempty research catalog, Codex routing must include `research_ids`:
  selected IDs, or `[]` for none. Generated artifacts follow the same rule with
  `artifact_ids`. Nonexistent IDs fail validation. A response missing source fields
  gets one model correction using the exact request, conversation and captured
  catalog before any dispatch. The model can select sources, exclude unrelated
  sources or ask a normal source/version question. Code never guesses relevance.

Requests to proceed with previously discussed work do not require a command or
explicit provider name. The LLM resolves scope from user history and current
project evidence, then chooses an eligible route or asks for a destination.
`choose_task` presents relevant existing Codex tasks; standalone bounded production
still uses its plan approval. Questions and exploratory discussion remain distinct
from authorization to execute.

The source correction may add only missing fields or return a question with no
action. It cannot change destinations, capabilities or existing source selections.
The first response is retained in a correction receipt; each pass has a separate
provider/read journal and the usual six-round, twelve-call read budget. There is
at most one correction pass. A repeated omission asks which files to include;
invalid IDs, changed inputs and provider failures never dispatch. Interrupted
calls retain the existing uncertain state and are not automatically replayed.

Deterministic code still handles slash commands, reply addresses, guide choice
buttons, schema validation, known project/file access, hashes, queue receipts,
task availability, budgets and approval gates. Search ranking still uses lexical
matching; it retrieves evidence and does not authorize actions. Destination guide
checks remain part of the handoff adapter after the LLM selects a destination.

The runtime is still limited to implemented tools/actions. This does not add
arbitrary pipeline creation, unrestricted command execution, cross-task memory
synchronization, or automatic provider fallback. Provider errors preserve the
request and do not turn into a procedural guess about what the user meant.

Regression tests exercise structured model outputs and execution boundaries.
They do not establish that a live model will always choose the right action.

Production planning compiles fixed operation metadata before displaying its plan
card. Registered output paths determine omitted media types, and those types flow
to declared consumers. A scene/mesh operation must identify one unambiguous upstream
scene JSON; its producer and consumers receive `application/json`. Other explicit
types are preserved or rejected on conflict. Declared input edges add direct
dependencies without removing review dependencies. Fixed operations use one
invocation, independent of an agent's tool-call budget. No source version, task,
output path, executable code or approval gate is invented by this completion step.
The original model response and compiled plan remain separately recorded; existing
frozen assignments are not updated and failed plans are not replayed.

Scene and mesh planning also registers `operation-support/<capability>/contract.json`
and `validate_scene.py` as hashed inputs. The script copies the actual scene/mesh
validation functions and requires only Python's standard library. These inputs
reach both the producer and reviewer in their isolated workspaces, rather than
being visible only to the planner. Their instructions require JSON preparation
and data validation; the downstream registered host task owns Blender startup,
native save/reopen and rendering. A sandbox startup failure in past conversation
does not establish that data preparation is blocked. This is assignment guidance,
not an additional shell security boundary.

An intermediate user review retains the scheduling grant (contract digest and
control epoch). A recorded selection resumes remaining runnable work only if that
grant is unchanged; final selection does not restart completed stages. Deliberate
pauses/cancellation and modified contracts stay stopped. Older review pauses that
lost their grant can be explicitly resumed through `resume_production` or the
status card, provided the original started plan, current assignments and selection
record still match and no deliberate lifecycle control was applied. The action
records a receipt atomically; the scheduler dispatches after commit. Asking about
status never authorizes resume, and no attempt budget is reset.

New production planning contexts include a bounded metadata catalog of prior
outputs (`available_sources`) alongside already selected sources. The planner can
choose exact artifact IDs as producer inputs even if chat routing omitted them.
When this catalog is nonempty, a ready response includes `input_basis`: `new` with
no baseline, or `modify_existing` with exact baseline IDs. Each modification
baseline must be an input to a producing task, and its reviewer inherits it.
This classification is an LLM decision; code does not infer edit intent from
keywords. Missing or ambiguous versions should produce `needs_input` before any
worker starts. A conversation mention or screenshot is not an editable baseline.

Only selected candidates are read/verified, listed in the preview/source manifest
and supplied to workers. Hash and size checks run before preview and at Start;
catalog metadata does not assert file availability. Clarifying an unstarted ready
plan preserves its selected candidates as required inputs. Candidate reuse neither
accepts the old output nor replaces a recorded user selection. The existing plan
approval and blocked-attempt boundaries remain unchanged.

## Request intake, decomposition and response recovery

Character budgets are separate from provider output-token limits. The JSON
envelope allows 1,000,000 characters, accounting for escaping and advisory data.
Decoded direct answers allow 32,000 characters; action answers allow 6,000 and
serialized action data allows 16,000. Provider writing schemas and saved-answer
recovery use the same limits. Duplicate-key, schema and scoped-action checks still
apply. Raising a provider token setting does not correct these local limits.

The first provider submission permits only `relay_intake`, a bounded structured
scope interpretation. It returns answer, new_work, existing_work or clarify, plus
explicit outcomes for requested work: stable IDs, descriptions, separate output
counts, requested suffixes, procedural checks and semantic validation requirements.
The model resolves context and sources; quotes, status questions, ideas and inline
writing remain answers. Ambiguous essential scope remains clarification. A saved
workflow step retains its existing stage scope rather than authorizing new work.

Relay freezes the interpretation in the provider journal and adds runtime-owned
scope metadata to the response envelope. New work requires a scoped work route;
an inline answer cannot fulfill file outcomes. Production routing preserves exact
outcome descriptions and expands counts into distinct required output slots.
Questions/clarifications cannot dispatch work, and a final response cannot replace
the frozen interpretation. If later evidence reveals missing inputs or capabilities,
`work_status:needs_input` or `blocked` permits a concise no-action reply while
retaining all original outcomes. This neither completes the work nor changes scope. Workflow stages must retain every requested outcome;
their original contract follows queued stages, narrowed to the current outputs.

General plans may use 2–the frozen max_tasks tasks (12 for fresh scopes, retained
limits for older scopes). The planner chooses parallel producers, shared
preparation, sequential dependencies or grouped small outputs according to the
work and compatible worker budgets. Every requested deliverable maps to a distinct
actual output and independent review, or an existing validated operation deferral.
A file count is not a task count. A stage currently supports eight deliverable
slots; larger scopes need separately bounded workflow stages. Unsupported overall
scope must remain unresolved rather than silently dropping outputs or increasing
user budgets. Native-operation, source-version and approval checks still apply.

Generic delivery checks enforce requested suffixes, nonempty files, UTF-8, valid
JSON and complete code examples where declared. Reviewers assess semantic coverage
and disclose actual execution evidence; a code block does not prove running code.
Missing outputs block completion and preserve the other completed artifacts.
Historical assignments retain their original contracts; no job is automatically
replayed or retroactively accepted.

Normal conversations use one additional provider request for intake. The existing
six-round, twelve-call evidence budget and output-token ceilings are unchanged.
Bounded source/workflow routing corrections reuse the frozen intake, retaining
separate correction receipts. Intake itself cannot read files or dispatch work.
Provider responses and scope data are retained before validation; interrupted or
rejected submissions do not trigger automatic retries. Controlled transport tests
cover Gemini, OpenAI, Qwen, DeepSeek and OpenRouter; they do not qualify live models.

Saved direct replies can be exported without a provider retry:

```sh
python3 -m task_relay.conversation_recovery \
  --database /absolute/path/to/state.sqlite \
  --job 222691303 \
  --destination /absolute/path/to/recovered-response
```

The CLI also exposes this as `recover-response`. It opens the database read-only,
validates the saved response against captured offered tool IDs, refuses action
proposals, and exports the exact raw reply, decoded answer and hash receipt.
For legacy drafts, contiguous numbered `## Article N:` sections may also be split
for convenience; these exports do not establish requested-outcome coverage.
Exports remain unreviewed text and leave original status/error receipts intact.
An unchanged partial export can resume; edited files are never overwritten.

Recovery also exports unreviewed direct text that was rejected for violating the
frozen production route. Its receipt retains that scope and records
`request_fulfilled:false`; extraction neither accepts the output nor dispatches
its action. The original five-article response remains exportable without a new
provider request. Controlled verification logs and deployment limitations are
recorded under `outputs/universal-orchestration-*`.

## Large project histories

The conversation starts with a compact overview (up to 160,000 UTF-8 JSON bytes),
not every historical file and task detail. The current user message is preserved
verbatim. `context_overview` identifies omitted list tails and prose excerpts; the
model must read relevant missing instructions, criteria and decisions before using
them. Catalog omissions do not prove a task or artifact is absent.

`context_read` accepts a JSON pointer, character offset and limit (up to 16,000
characters). It returns exact JSON pages from the evidence captured for this turn,
with a hash, total size, completeness flag and next offset. It accesses no arbitrary
files and changes no project state. Existing file tools remain the route for fresh
canonical project documents. Context reads share the 12-call, six-round read budget
and are recorded alongside other provider requests and tool results.

Models see the overview; action validation uses the full in-memory snapshot and
existing live revision/authorization checks. Saved conversation snapshots contain
the overview and omission metadata; selected read results remain in the turn's read
journal. Original task records, artifacts, assignments and decisions stay intact.
An unrelated large production no longer trips the former 500,000-character global
snapshot rejection. Actual corruption/missing references and provider failures are
still reported. A previously failed request is not automatically requeued.
