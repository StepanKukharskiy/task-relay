# Shared capabilities and dispatch

The catalog in `task_relay/capabilities.py` and operation registry in
`orchestrator/execution.py` describe existing execution paths. They do not give
a language model new powers or grant native tool permissions.

## Version and availability

Updated 2026-10-02 against the 0.13.153 working source and the verified local
0.13.153 installation. The development ChatGPT integration is version 0.2.1.
Individual guides and the roadmap record which paths were bundled and what was
actually qualified. Uncommitted source changes can differ from the installation
even when the version string matches. This documentation audit did not run any
provider, native application, browser, delivery or installation check.
The latest public beta recorded in this repository is 0.13.89; see its
[release notes](release-notes.md) for the contents of that download. A source
capability is not automatically present in an older installer. At request time,
Relay's capability catalog reports configured operations, eligible workers and
current blockers. Registration or a saved provider credential does not establish
live provider access, host compatibility, output quality or user acceptance.

The current source defines **seven text/agent connections, three additional media
providers, 19 production executor profiles and 35 registered execution operations**.
These count different layers: a provider can serve several profiles, and an
operation can use a local application or a provider. They are not 35 SaaS connectors.
ChatGPT/MCP, channels and host infrastructure are listed separately below.

## Provider and agent connections

| Connection | Implemented routes | Documentation and qualification boundary |
| --- | --- | --- |
| Codex | Existing desktop task routing/creation, approvals and progress; supervised `codex-cli` files/shell worker; local project context and usage reads | [Routing](natural-language-routing.md), [runtime](worker-runtime.md), [context](project-context.md), [usage](usage-tracking.md). A desktop task's plugins/browser tools are separately available and authorized. |
| Claude | Managed account/Agent SDK tasks with coding tools and native permission requests; local usage reads | [Setup](onboarding.md), [routing](natural-language-routing.md), [usage](usage-tracking.md). Claude desktop detection does not provide desktop UI control or a production `claude-agent` profile. |
| Gemini | Conversations; declared-file, Python, browser and Safari workers; grounded search; images/edits, speech and Veo video | [Profiles](execution-providers.md), [web](orchestrator-web.md), [media](media-workflows.md). Each route has its own tool, scope and evidence boundary. |
| OpenAI API | Conversations; declared-file, Python, browser and Safari workers; production image generation/edits | [Profiles](execution-providers.md), [browser](general-browser.md), [media](media-workflows.md). This API connection is separate from Codex account access. |
| Qwen / Alibaba Model Studio | Conversations; declared-file, Python, browser and Safari workers; regional API endpoints | [Setup](onboarding.md), [profiles](execution-providers.md). Local Qwen serving and image/video generation are not included. |
| DeepSeek | Conversations; declared-file, Python and Safari worker profiles | [Profiles](execution-providers.md), [Computer Use](computer-use.md). No registered DeepSeek Playwright browser profile. |
| OpenRouter | Conversations; declared-file, Python and Safari worker profiles; production images | [Profiles](execution-providers.md), [media](media-workflows.md). Bounded workers require an exact model; automatic/free routing is excluded. |
| Runway | `runway.image`, `runway.video`, with supported image references | [Media](media-workflows.md#runway-higgsfield-and-meshy). API adapters are implemented; live account access and paid generation remain unqualified. |
| Higgsfield | `higgsfield.image`, `higgsfield.video`, text-prompt inputs | Same media guide and qualification boundary. Website subscriptions do not establish API access. |
| Meshy | `meshy.mesh`: text-to-3D, one untextured GLB | Same media guide and qualification boundary. Image-to-3D and texturing are not implemented. |

Provider definitions live in `providers.py`, `api_providers.py` and
`cloud_providers.py`. [Execution providers](execution-providers.md) lists all 19
production profiles. The runtime advertises only currently eligible choices;
registration alone does not establish model tool compatibility or quota.

## Registered operations and work controls

| Capability family | Registered operations or route | Detailed scope |
| --- | --- | --- |
| Task routing and creation | Existing Codex/Claude/provider tasks, `route_task`, `delegate_task`, explicit Codex task creation | [Natural-language routing](natural-language-routing.md), [project tasks](project-tasks-and-starters.md); target availability and permissions are checked before dispatch |
| References and public research | Reference collection, project text/PDF reads, conversational web search/fetch; registered `web.sources` in local 0.13.94 | [References](reference-collection.md), [PDF reads](#direct-pdf-reading), [web research](orchestrator-web.md); these do not grant browser control or establish fact verification |
| Text and files | `text.bundle`, `gemini.text`; bounded file and document workers | [Mixed execution](mixed-execution.md), [shared code workers](shared-code-workers.md) |
| Request-derived jobs | `plan_pipeline`, stage decisions and controls; exact artifact lineage and scoped replacement | [Workflows](request-derived-pipelines.md), [artifact dependencies](artifact-dependencies.md), [replacements](artifact-replacements.md) |
| Reusable procedures | Reviewed procedure versions and opportunity discovery in development source | [Procedures](reusable-procedures.md), [opportunities](automation-opportunities.md); historical similarity is a candidate, not an approved automation |
| Versioned job context | Read-only `.relay` JSON/SQLite process and artifact views, bounded stage context and `context_read` | [Workflow handoffs](workflow-handoffs.md); shared committed state remains authoritative, and declared inputs alone are potential dependencies |
| Images and sourcing | `gemini.image`, `openai.image`, `openrouter.image`, `runway.image`, `higgsfield.image`, `images.collect`, `images.fetch` | [Media](media-workflows.md), [image sourcing](image-sourcing.md) |
| Video and 3D services | `runway.video`, `higgsfield.video`, `meshy.mesh`; conversational Gemini/Veo video, including one first-frame image in local 0.13.91+ | [Media workflows](media-workflows.md) |
| Editable local video | `media.compose`, `hyperframes.preview`, `hyperframes.render` | [Reels](reels.md); optional renderer qualification applies |
| Native models | `blender.startup`, `blender.scene`, `blender.mesh_scene`, `blender.inspect`, `blender.run_python`, `blender.import_asset`, `blender.animate`; `rhino.startup`, `rhino.inspect`, `rhino.run_python`, `rhino.render`, `rhino3dm.create`, `rhino3dm.run_python`, `rhino.grasshopper`; `sketchup.startup`, `sketchup.inspect`, `sketchup.run_ruby` | [Blender](local-applications.md), [Rhino](rhino.md), [SketchUp](sketchup.md); host availability differs. Grasshopper native source fixtures passed; installed-app graph execution remains unqualified. SketchUp native qualification awaits activation. |
| Presentations | `pptx.create`; `pptx.edit` for guarded exact text runs and pictures | [Presentations](presentations.md); chart and layout editing is outside `pptx.edit` |
| Evidence-linked revisions | Explicit reviewed XLSX material/translation links and bounded PPTX text/picture/notes links; conservative impact, native candidates, companion bundles and separate review/selection | [Workflow handoffs](workflow-handoffs.md), [roadmap](../ROADMAP.md). The real plant deck demonstrated selected-set continuation through a second revision in an isolated job; general dependency discovery and installed-app execution were not established by that case. |
| Managed browser research | `browser_research` for Perplexity Search with the saved Chrome profile | [Perplexity browser](perplexity-browser.md); enabled browser and real session are checked separately |
| Channels and installation | Telegram, optional macOS Messages text pilot, companion setup and explicit updates | [Onboarding](onboarding.md), [Messages](messages-pilot.md), [app updates](app-updates.md); channel and platform support differ |

The operation IDs above are an inventory, not an execution grant or a claim that
every route has run live. The detailed guides state input, review and platform
limits. The [roadmap](../ROADMAP.md) distinguishes controlled checks, local
installation and live qualification.

## Browser, context, channel and infrastructure connections

| Connection | Current scope | Documentation and evidence boundary |
| --- | --- | --- |
| Chromium / Playwright | Gemini/OpenAI/Qwen scoped browser workers; DOM interactions, viewport captures and declared file transfers | [General browser](general-browser.md). Screenshot pixels are saved locally; these profiles receive page text and image metadata rather than visual reasoning inputs. |
| Signed-in browser sessions / local CDP | Explicit account-site registry, manual login confirmation, managed persistent profile or attachment to one existing local Chromium context | [Account sites](account-sites.md). Confirmation is user-attested; attachment does not discover credentials or authorize every site. |
| Perplexity Search | Dedicated managed Chrome research route; separate older extension and Codex-delegated pilots | [Perplexity](perplexity-browser.md), [desktop browser](desktop-browser.md). The delegated Zen pilot used the Codex task's tools; Relay has no direct Zen attachment adapter. |
| Safari | Shared `*-computer` profiles with owned observe/navigate/scroll sessions; foreground observation and separate background scripting transport | [Computer Use](computer-use.md), [roadmap](../ROADMAP.md). Background research has installed-run evidence; stricter research quality and broader live qualification remain open. |
| Google-grounded search / public HTTPS | Conversational tools and `web.sources`; captured queries, source versions and gaps | [Web research](orchestrator-web.md). Search candidates are not independently verified facts. |
| Wikimedia Commons / observed publisher images | `images.collect` and `images.fetch`; image bytes, provenance and attribution | [Image sourcing](image-sourcing.md). Identity, suitability and rights require review. |
| Document libraries / filesystem | DOCX, XLSX, PPTX, PDF and PNG through qualified Python tooling; scoped text/PDF reads, frozen attachment imports and exports | [Code/document workers](shared-code-workers.md), [host grants](host-adapters.md), [presentations](presentations.md). File tooling is separate from controlling open Office applications. |
| Local Codex project context | Authorized collection of canonical messages and Markdown knowledge, source-linked topics and context exports | [Project context](project-context.md). CLI pilot packaged in local 0.13.153; no dedicated Desktop context interface or connected-host qualification follows from packaging. |
| ChatGPT / Relay MCP server | Work inspection, understanding, reviewed changes, continuation and result capture; stdio/HTTP, project scopes, authentication and MCP Apps UI | [Plugin](relay-chatgpt-plugin.md), [connection](relay-chatgpt-connection.md), [roadmap](../ROADMAP.md). Private connected capture/fresh-chat return is recorded. General worker dispatch, full-history access and public distribution are not provided by this integration. |
| Telegram / Apple Messages / Relay Desktop | Shared-runtime intake, review/control and result surfaces; original delivery destination retained | [Onboarding](onboarding.md), [Messages](messages-pilot.md), [roadmap](../ROADMAP.md). Messages is an optional macOS pilot with narrower channel coverage. |
| Local usage records | Codex/Claude sessions and recorded Relay API usage | [Usage](usage-tracking.md). Incomplete coverage and unknown costs remain explicit. |
| GitHub release/update transport | Release discovery and explicit package update handling | [App updates](app-updates.md). Reading releases does not install an update. |
| Host and credential adapters | Filesystem grants, worker discovery, process ownership, locks/IPC, macOS launchd, optional Linux systemd, private-file/environment/macOS Keychain secrets | [Host adapters](host-adapters.md), [native qualification](native-qualification.md). macOS is the primary execution host; Windows task execution remains unavailable. |

## Capability selection and work-state ownership

Agent tasks already request supported capability IDs through `worker.requires`.
Relay resolves them against a captured eligible catalog and freezes the actual
provider/model/tools before Start. See [capability-driven workers](capability-workers.md).
Registered native/media operations keep their versioned domain contracts and exact
side-effect grants. A shared capability name does not make different validation,
authentication or cancellation semantics interchangeable.

Relay records requests, assignments, artifacts, decisions and receipts independently
of the selected worker. The plugin's authoritative `work_*` records coexist with
production records. A [common result completion bridge](execution-results.md)
retains frozen observations through existing completion/admission paths. Owned
text/plugin results capture automatically; other outcomes require explicit host
work links. Blanket synchronization of all production jobs is pending.
`.relay/job.sqlite` remains a read-only projection. The MCP integration currently
exposes Relay to clients; a generic client for arbitrary external MCP executors,
arbitrary HTTP workers or unregistered CLI commands is not implemented by it.

## Execution paths

Relay's direct web tools perform public search/fetch, not browser interaction.
The [Perplexity browser route](perplexity-browser.md) is a separate managed Chrome
research action. With Browser use enabled, an explicit request can select
`browser_research` from Telegram or Messages; `/perplexity` is also available.
The worker checks the saved website session before submission. The older
standalone CLI/extension pilot remains distinct. Sign-in can be started with
`/browser connect` in either channel or through Telegram Providers.

O03 provides `plan_production` (template, project, reference pack, explicit research IDs,
planning-only intent, optional prior plan ID) and `authorize_production_plan`
(saved plan ID). The first saves a bounded planning operation; the second presents
an existing plan for approval. Neither starts workers directly. A delivered,
version-bound Start card registers one producer/reviewer stage in the existing
runtime. See [new workflow planning](new-pipeline-planning.md) for limits and evidence.

| Path | Capabilities | Execution evidence |
| --- | --- | --- |
| Direct orchestrator file calls | List/search project text and read text or PDF sources | Private request/response/read journal; existing file policy |
| Direct orchestrator web tools | Google-backed search with configured Gemini; public HTTPS page text | Grounding metadata, cited URLs, timestamped page hashes and source report |
| Existing Codex desktop task | File inspection/editing and shell; additional plugins/web are not assumed | `task_routes`, then native task progress/result |
| Existing Claude task | Read, Glob, Grep, Edit, Write, Bash, WebSearch, WebFetch | `backend_jobs`, native permission requests and result |
| Existing Gemini/OpenAI/Qwen/DeepSeek/OpenRouter text task | Four read-only file tools, including PDF text extraction | `backend_jobs`, native provider/tool receipts |
| Relay actions | Existing image, reference, research-folder and production/workflow controls | Existing adapter receipts and user gates |
| Registered production worker | Exact selected files/shell, declared-file, Python, browser or Safari profile | Runtime attempts, frozen capabilities and tool contracts, artifacts, independent review and user selection |
| Direct Rhino 7/8 host operations | Startup, selected `.3dm` inspection and exact-approved interpreter-specific creation/editing and native rendering on macOS | Exact script/input grants, process ownership, native candidate, independent reopen checks and viewport preview; [scope](rhino.md) |
| Grasshopper authoring (local 0.13.108) | `rhino.grasshopper`: new definitions with sliders, components, wires, panels and embedded Python/templates through Rhino 7/8/macOS | Exact script and library hashes; native `.gh` and `.ghx` save, independent reopen/solve and output-count checks; small native fixtures passed from development source, while installed-app graph execution remains unqualified; [scope](rhino.md#grasshopper-authoring) |
| Managed Perplexity research | One explicit Search in the app-managed Chrome profile when Browser use is enabled | Frozen original request and website query, browser journal, originating-channel delivery; [scope](perplexity-browser.md) |

Every ordinary orchestrator request receives a current capability catalog. Targets
include their project, provider, declared capabilities, availability/blocker and
configuration fingerprint. Busy, uncertain and workflow-owned destinations are
unavailable; independent tasks in the same project remain usable. Provider setup
is checked locally. Authentication and remote model tool support are only verified
when execution occurs. No API keys or configuration contents enter the catalog.
The managed-provider catalog lists at most 50 recent tasks and reports truncation.

## How dispatch works

The model can return a typed `delegate_task` action containing an existing task ID,
its provider, and required capabilities. Relay validates that choice, then checks
the destination again before queueing. It sends the original user message verbatim.
Provider choice and project relevance are part of the model's routing instructions;
deterministic checks enforce the declared provider/capability match, current task
identity and availability. They do not independently interpret all natural-language
intent. Ambiguous destinations should produce a question.

Direct file calls and immediate actions use the shared dispatcher. Card-gated
controls retain their existing approval path. A `capability_dispatches` receipt
links each immediate action to its native queue/control record. Queue insertion,
receipt and acknowledgement commit together; repeated dispatch returns the saved
receipt, and a changed action for the same request is rejected. The native worker
owns execution, interruption recovery and results. An uncertain submission is never
automatically replayed or switched to another provider.

Acknowledgements for delegated work are replyable task messages. Queueing is not
completion; recent capability receipts read status from their underlying queues.
Production replies continue through their registered stage controls and do not
expose general worker targets as an escape from frozen scope.

## Examples

- “Use Claude in my existing Agent research task to search online and cite sources.”
- “Use Codex in Fix incomplete floor layout solver to inspect the failing tests.”
- “Read the roadmap and explain the next step.” (Direct file tools can suffice.)

If no suitable connected task exists, the orchestrator explains the missing path.
Task creation remains available through `/new`; arbitrary new task/graph creation
from the delegation action is not implemented. [Direct web research](orchestrator-web.md)
is available. Media operations use their own registered contracts; the bounded
planner also supports the mixed text graph nodes below.
The O06 [mixed graph adapters](mixed-execution.md) now expose `graph_operations`
alongside this direct-dispatch catalog. Registered `text.bundle` and `gemini.text`
steps share the production runtime's artifacts and receipts with Codex assignments.

## Research handoffs and remembered content guides

Codex route/choice/delegation actions can carry `research_ids` from the registered
research-document catalog. Sources are copied and hashed before choosing a task;
the selected task receives complete readable file paths, purposes and hashes.
Copies are checked again immediately before submission. The user's exact request
is preserved. A legacy request explicitly asking for the only two registered
research documents can resolve that unique pair; other missing/ambiguous source
selections block instead of sending an instruction without its documents.

Guide discovery spans topics and visible local guide/skill/playbook/style files.
Routing can search the selected destination project; the orchestrator's explicit
`discover_guides` action can search up to 20 known projects. Up to six candidates
are offered, and a saved user choice freezes which guide versions enter the
handoff. Remembered `project_guide_profiles` identify discoveries, not permission
to apply a guide automatically. Bounded scans disclose incomplete coverage;
AGENTS.md remains native project instruction rather than an optional guide.
See [guide discovery and managed-worker handoffs](natural-language-routing.md).

Previously registered video workers already carried copied content guides. Guide
presence does not establish that an editor followed the desired voice or that a
draft is acceptable. Creative review and the user's corrections remain necessary.

## Large desktop file-change approvals

Telegram file-change approvals include complete literal diffs and requested access.
Small reviews stay inline. Reviews larger than 6,000 UTF-8 bytes use a compact card
and a named `.txt` document. The report is tied to the exact request fingerprint and
stored under the data directory's `approval-reports/` folder.

Allow is accepted only after the card and document are delivered, the report hash
still matches, and the desktop owner, request and diff remain unchanged. You can
use the card buttons or reply to its document with `/allow` or `/deny`. Delivery
failure never makes a summary sufficient for approval. Missing diffs or requests
above the 1 MB serialized UTF-8 detail bound retain desktop review. This replaces
the former 10,000-character escaped-JSON cutoff for file changes; command and
permission cards retain their existing limits. No approval is submitted automatically.

## Direct PDF reading

`pdf_read` reads the actual PDF under the selected project's existing read grant.
It is offered to the orchestrator and workspace-enabled Gemini, OpenAI, Qwen,
DeepSeek and OpenRouter text tasks. `file_search` still searches text files only;
use `file_list` to locate PDFs, then `pdf_read` to inspect their content.

Arguments: `path`, one-based `page`, character `offset`, `limit` (1–24,000), and
`sha256` (empty initially). Responses contain numbered page text, the source hash,
`total_pages`, `next_page` and `next_offset`. Continue with the returned hash to
reject a changed source instead of combining versions. A response covers at most
eight pages; it does not imply the whole document was inspected. Cite PDF page
numbers and disclose remaining unread pages. Wiki summaries do not replace a
requested read of the current PDF.

Bounds are 20 MB, 500 document pages, eight pages/24,000 characters per call and
15 seconds per extraction process. Decoded stream limits also apply. Parsing runs
in a separate local process over bytes from the existing protected file opener;
no additional path grants are created. Symlinks, private paths and traversal
remain excluded. Malformed/encrypted/oversized PDFs and timeouts return explicit
errors without automatic retry. `pypdf` is a pinned core dependency, included in
the packaged desktop runtime. This is text extraction: no OCR, image/diagram
interpretation, table-layout verification, embedded-script execution or external
link fetching. Pages lacking text are explicitly marked as blank or needing OCR.
