# Media workflows

Controlled qualification uses tiny media fixtures and fake model responses.
No paid generation, native modeling or live message delivery was run for this change.
Packaged Task Relay.app installations require
an app update; restarting an existing bundle does not activate repository changes.

## Models by task

In the desktop app, open **Settings → Models by task**. Connect each provider
once: use AI connection for text providers, and **Image, video & 3D connections**
under Models by task for Runway, Higgsfield and Meshy. Select the provider, enter its
API credential, then save the desired task default. Higgsfield uses `ID:SECRET`;
Runway and Meshy use API keys. These are API connections; saving a credential does
not verify access, credits or entitlement from a website subscription. The task
selectors reuse credentials, including private file, environment and Keychain references. The page reads saved catalogs without
making generation calls. Catalog presence is not proof of quota or account access.

| Task | Current choices | Execution |
| --- | --- | --- |
| Conversation | Connected Gemini, OpenAI, Qwen, DeepSeek, OpenRouter | Existing text orchestration and task adapters |
| Images | Gemini, OpenAI, OpenRouter, Runway, Higgsfield | Gemini direct image task or provider-specific production image operation |
| Video clips | Gemini/Veo, Runway, Higgsfield | Gemini `/video DESCRIPTION`, or a reviewed Runway/Higgsfield production plan |
| 3D assets | Meshy | Reviewed text-to-3D plan producing one untextured GLB |
| Modeling and rendering | Available Blender/Rhino workflows | Existing planned native operations |

Existing defaults appear before any preference is saved. A save records one
capability/provider/model choice and its revision atomically in the Relay database.
Concurrent stale windows must reload before saving; failed saves roll back.
Credentials are never copied into preference records or returned to the page.
`/providers` updates a selected model through the same preference record;
`/orchestrator provider NAME` changes the conversation provider without changing
image/video/3D choices. Disabled or unavailable chosen providers do not cause an
automatic provider switch.

Request overrides and existing task selections precede defaults. New runs freeze
the chosen model using their existing job or production-plan records. Changing
settings never edits those records, resubmits an uncertain job, changes artifact
versions or infers acceptance. The orchestrator's `generation_jobs` view projects
recent direct image/video jobs and production image/video/mesh/modeling attempts into a shared
status shape, retaining the original receipt IDs, frozen models and artifact hashes.
Attempt completion remains distinct from review, acceptance and delivery.

Video composition and editable Blender/Rhino work retain their separate workflows.
Choosing a default does not submit generation or purchase credits.

## Replies and source versions

The reusable layer is the artifact catalog, request-owned hash-checked copies,
registered capability schemas, explicit dependency graph, LLM intent decision and
durable dispatch/recovery records. These mechanisms do not match a tower name or
Rhino keyword to choose an action. The adapters still implement their own formats,
limits and transport. Context handoffs now share an archive/projection contract,
and coverage guards check all selected operations plus declared deliverables of any
file type. This is a shared foundation, not universal tool support
or proof that a live model will always select the right tool.

Reply normally to an image with an edit, a question, or a change of tools such as
“Use Rhino to make a facade drawing.” The orchestrator receives the exact request,
image task, recent instructions and generated artifact versions. The LLM selects
the next action. A native drawing requires a native application route; an image
that resembles a drawing does not satisfy it. Missing dimensions remain questions.
Explicit `/image` on a selected native Gemini task remains an image command.

An image edit selecting the latest candidate keeps the native task and history.
Selecting an older/different candidate or another model starts a new image context
from those exact files. Production and generated-media artifacts are copied and
hash-checked before handoff. Sharing never accepts or supersedes a candidate.

If an image request would exceed Relay's 16,000,000-byte JSON cap, the runner starts
a new native context containing exact previous user prompts, visible responses,
latest generated images, current references and the current request. The complete
original input/response archive is unchanged, including opaque model signatures.
A `.context.json` receipt records source/archive hashes and the outgoing request hash;
the delivery manifest includes that receipt. If this handoff still exceeds the
cap, the request stops before provider transport.

Gemini text tasks with a workspace and direct OpenAI, Qwen, DeepSeek and OpenRouter
text tasks use the same handoff format. All exact user requests stay in context;
older responses may be replaced with explicit archive markers. The agent can read
those exact responses using `context_read(turn, field, offset, limit)`; reads check
the archive hash and share the existing tool budget. A changed archive is rejected.
Space is reserved for follow-up tool results. Current instructions/references that
still exceed the bound stop before transport. This handles Relay's byte bound,
not every provider's model-specific token window. In-flight native reasoning/tool
exchanges remain intact and are never compacted midway through submission.

## Image operations in production

| Operation | Configuration | Output |
| --- | --- | --- |
| `gemini.image` | Gemini image default; exact model, aspect ratio and token bound frozen in plan | One PNG candidate |
| `openai.image` | OpenAI → Default models → Image in `/providers`; exact GPT Image model, size and quality frozen in plan | One PNG candidate |
| `openrouter.image` | OpenRouter → refresh models → Default models → Image; exact image model slug and aspect ratio frozen in plan | One PNG candidate |

These image operations accept text and up to six PNG/JPEG/WEBP references, including an upstream
Blender preview. Inputs total at most 11 MB; output at most 50 MB/40 million pixels;
one request/attempt, at most 600 seconds. The plan requires independent review and
a candidate selection gate. AI imagery does not validate the source geometry.

Pillow is required for decoding/conversion. Source installs use `task-relay[images]`;
the macOS app includes a pinned, hash-verified wheel. Missing conversion support
blocks before an attempt/provider call, rather than after generating the image.

“Make a Blender model and turn its preview into an architectural photograph” can
now produce a graph containing both native rendering and image generation. If the
orchestrator selects operations, validation rejects a plan that drops any of them.
Exact host Python approval can still require a later stage; planning must disclose
that boundary and the pending requested outcome via `deferred_operations`. It
requires a gated preparation producer with selected outputs and independent review.
Deferred operations remain visible in the card and frozen plan; no later stage
starts automatically. `deliverables` maps stable IDs to requested descriptions;
the planner's `deliverable_map` binds each ID to a real reviewed output or explicit
deferral. These records travel in the frozen plan. Legacy envelopes remain readable;
semantic completeness of the LLM's interpretation still requires qualification.

OpenAI uses the existing configured OpenAI API credentials, separately from Codex
account access. A text-model setting alone does not enable its image operation.
The adapter uses the [Images API](https://developers.openai.com/api/reference/resources/images/methods/edit):
JSON edits contain exact image data URLs; generation uses `images/generations`.
Provider responses, usage and outgoing intent are recorded before/after transport.
Interrupted or ambiguous submissions never automatically retry or switch providers.
Image defaults are frozen at planning time; subsequent configuration changes do
not silently alter an approved plan. Account/model access is checked by the actual
provider when invoked, not inferred from a local configuration entry.

Immediate Gemini image requests can specify an exact model; otherwise they retain
the image task's selection or use the image default for new work. OpenAI image work
uses an approved production stage. OpenRouter uses its
[dedicated Image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation),
including base64 `input_references`, one result, a fixed model and
`provider.allow_fallbacks=false`. Only PNG/JPEG/WEBP results are decoded; remote URLs
and SVG outputs are not fetched/executed. Model-specific reference and parameter
support is ultimately checked by the provider. Image catalog discovery generates
no content and does not prove account access. Unsupported providers require a
protocol adapter; Qwen/DeepSeek text connections do not imply image/video generation.
Veo's existing direct video command retains its configured model. Project-level
media profiles, additional provider models and a Gemini graph video step remain open.

## Runway, Higgsfield and Meshy

These adapters use the same frozen production plans, independent review, candidate
selection, artifact delivery and recovery receipts as existing operations. The
orchestrator writes the actual generation brief into the plan while preserving the
exact original request. Named providers never silently fall back to another provider.

| Operation | Initial models | Inputs and output |
| --- | --- | --- |
| `runway.image` | `gen4_image` | Text and up to three image references → PNG |
| `runway.video` | `gen4.5` | Text and optionally one first-frame image → MP4 |
| `higgsfield.image` | `higgsfield-ai/soul/standard` | Text → PNG |
| `higgsfield.video` | `bytedance/seedance/v1/pro/fast/text-to-video` | Text → MP4 |
| `meshy.mesh` | `meshy-6`, `meshy-7` | Text → untextured GLB |

Image/video operations expose landscape or portrait; clips expose 2–10 seconds.
Meshy prompts are bounded to 800 characters, other prompts to 1,000. Runway image
references are bounded to 3.5 MB each before encoding. Unsupported references or
models are rejected before transport. Meshy texturing and image-to-3D are not yet
implemented; they require their own request and authorization scope.

Each attempt records its exact outgoing request before one generation POST, then
saves the accepted task ID before bounded polling. An interrupted or ambiguous
submission never causes another POST. Saved task IDs support continued polling
in the same job; no new automatic UI recovery action is introduced. Local Stop
ends waiting, but remote work may continue and incur usage. Successful output is
downloaded within the approved byte bound, with public HTTPS validation and no
API credential forwarded to the download server. Provider usage is retained when
supplied; unknown cost is not invented.

Image validation decodes the PNG; video validation checks MP4 container structure;
mesh validation checks GLB structure and rejects external resource paths. These
checks do not establish playback, geometry quality, physical dimensions or native
application compatibility. Those require separate review. Output URLs may expire;
a failed download retains the generation receipt and does not regenerate output.

The initial request schemas follow the official
[Runway API guide](https://docs.dev.runwayml.com/guides/using-the-api/),
[Higgsfield API documentation](https://docs.higgsfield.ai/docs) and
[Meshy Text to 3D API](https://docs.meshy.ai/en/api/text-to-3d).
Live account access, paid generation and resulting media quality remain unqualified.

## Qualification

The focused regression command and result are recorded under
`outputs/media-pipeline-verification/`. It covers routing, source tampering,
native-history handoff, image graph dependencies/review, frozen model choices,
omitted outcomes, no replay after uncertain transport, and usage attribution.
Blender/Rhino execution is simulated here; their native application qualifications
are separate. Passing these tests does not qualify live LLM interpretation,
provider visual quality, account access, or Telegram/Messages transmission.

Cloud provider checks are recorded in `outputs/cloud-media-checks.md`: controlled
transport/recovery, production artifacts, settings and native installation checks.
