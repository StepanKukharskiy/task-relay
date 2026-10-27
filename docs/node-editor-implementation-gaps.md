# Node editor implementation gaps

Status: implemented and installed as 0.13.237 on 2026-10-20.
The numbered audit below preserves the original findings. It is not authorization
for provider execution. Extend the existing operation
definitions, editor and runtime; do not introduce another node framework.

The current default catalog exposes 58 operations. Catalog registration establishes
an interface, not that a person can configure and execute it through the editor.
The previous native check established editing, model persistence and fail-closed
Run preparation, not successful execution of every catalog operation.

## Original confirmed gaps and intended fixes

1. **Direct prompts for generation.** `gemini.image`, `openai.image` and
   `openrouter.image` have no named literal prompt input. Their registered file
   bundle requires at least one source. `gemini.text` has the same file-first
   interface. The image adapter constructs provider text from the instruction
   and supplied documents, but the editor labels the objective as "Step name".
   Add an explicit prompt in the existing operation contract, with optional
   references where the provider/mode supports prompt-only generation. Preserve
   existing saved file-based bindings. Do not require another model call merely
   to produce a prompt file.
2. **Other generation modes still require files.** Runway and Higgsfield image/
   video and Meshy mesh already declare `prompt`, but also require `files`.
   Make required reference inputs follow the supported model/mode; do not assume
   every model permits text-only generation. Provider support needs verification
   before changing those requirements.
3. **External file inputs are not authorable.** The inspector offers only
   "From step" for artifact inputs, no file chooser or saved-artifact chooser.
   Workflow setup explicitly rejects artifact fields. This affects image
   references, existing PPTX files, room images and native CAD/model/script
   inputs. Register a selected file through the existing artifact mechanism and
   expose a typed file input; no raw arbitrary path or invented artifact ID.
4. **Multiple files cannot be composed through the picker.** There are 37
   artifact-list ports. `sourcePicker` displays one selected reference and
   replaces a list with `[selectedReference]`. It cannot add, remove or order
   multiple references, or explicitly set an allowed empty list. `images.merge`
   and `pptx.edit` require at least two files, so this is a functional blocker.
   Add list controls using the existing list binding. Preserve every reference
   when reopening/editing a saved list.
5. **Typed settings are rendered as generic text/JSON.** Literal enum settings
   such as aspect ratio, image quality and native permissions are plain text;
   numbers and booleans use JSON text areas. Searches require JSON arrays for
   queries/domains; acquisition subjects, crop coordinates and collection/layout
   parameters also expose JSON. Render controls from the existing schema, show
   defaults and requirements, and support optional/nullable inputs accurately.
   The current reference classifier also offers no literal-null choice for
   nullable reference ports. Do not flatten away the schema or relax validation.
6. **AI task authoring is confusing and incomplete.** The prompt is labelled
   "Task"; a new custom input defaults to an artifact rather than text and shows
   media-type machinery. Output editing requires raw JSON. Make the prompt
   explicit and provide named input/output controls. Preserve declared schemas.
   Additionally, changing provider is only held in the inspector until a
   nonempty model ID commits; clearing an existing model returns without editing
   the saved choice. Fix that state mismatch so Run cannot use a prior choice
   contrary to the visible controls.
7. **Connection choices lack compatibility guidance.** `sourcePicker` lists all
   outputs from all other nodes, without media/type compatibility filtering.
   Shared graph validation still rejects invalid connections; the UI should
   explain or disable them before the attempted edit. The `review` candidate is
   currently a literal task-ID field, not a node selector. Keep reviews optional
   as already requested; improve the selector only for explicitly added reviews.
8. **Run readiness and diagnostics have real gaps.** Installed Codex preview
   reports a missing qualified runtime receipt. Do not bypass that gate or imply
   that model selection proves readiness. Missing worker model errors are masked
   by `desktop_bridge.main` as "Invalid setup request." Show a safe, actionable
   node/field diagnostic. Separately, `desktop_node_runs.compile_plan` accesses
   `model` and `reasoning` inputs for `web.sources.codex` and
   `web.sources.prepared.codex`, but their public definitions omit those inputs.
   The unprepared search's pure compiler probe raises `KeyError('model')` before
   availability checks. Bind the exact search backend through the existing
   public contract and admission; do not invent missing settings.

## Evidence inspected

- `orchestrator/operation_definition.py`: definitions, catalog and presentation.
- `orchestrator/operation_adapters.py`, `orchestrator/execution.py`: registered
  parameters and file requirements.
- `orchestrator/media_adapters.py`: provider prompt construction.
- `orchestrator/node_spec.py`: graph/media validation and literal-only workflow
  setup.
- `task_relay/assets/companion-node-editor.js`: input/output rendering,
  `sourcePicker`, model commit and Run UI.
- `task_relay/desktop_node_setup.py`, `desktop_node_runs.py`, `desktop_bridge.py`:
  model setup, search backend compilation and error handling.

The audit enumerated the current catalog with the private Python interpreter
using `-B -X pycache_prefix=/dev/null`. A pure `compile_plan(None, ...)` probe used
one `web.sources.codex` node with literal query/domain arrays; it failed at the
missing `model` lookup before Runtime use or provider checks. No search, download,
model generation, live dispatch, installation or service startup ran. Native
observations from the preceding check are recorded separately in private evidence.

## Completion criteria and order

First make one AI response and one prompt-only image workflow authorable: prompt,
model, connection, defaults, useful readiness errors. Then add registered file
selection, ordered multi-file bindings and schema-based settings/connection
controls. Fix the Codex search contract mismatch before advertising that node as
ready for manual Run.

Use focused offline checks for each changed boundary, including save/reopen,
unchanged model choice, preserved multi-file order, incompatible bindings and no
dispatch on missing setup. Cover representative text, generation, file editing
and sourcing graphs. Native UI setup and actual provider execution are distinct
claims; paid/live execution still requires the applicable authorization. Preserve
prior runs and leave background services stopped. This audit changes docs only.

## Implemented changes (2026-10-20)

The existing definitions now declare literal prompts for Gemini text/image and
OpenAI/OpenRouter image operations. Prompt-only input is supported by adapters
that already implement that mode; Runway video still requires a source image.
Legacy file-based bindings remain compatible.

The existing editor now provides explicit AI Prompt fields, named outputs, typed
settings/defaults, compatible connection choices, optional empty references and
ordered multi-file controls. User-selected files register immutable versions in
the existing artifact store. Reusable workflows can ask for a file at run time.
Changing or clearing a model removes the previous saved choice immediately.
Free-form objects without declared properties still use an advanced JSON field.

Codex search exposes its exact backend settings and compiles them into the existing
trusted grant. Safe node diagnostics reach the inspector. A selected previously
qualified Codex receipt is verified against its evidence and executable before
being saved; this neither bypasses qualification nor proves current account auth.

Offline checks exercise the real prompt adapters with mocked transports, exact
file versions, save/reopen, ordered references and rejected invalid bindings.
Installed UI and live provider execution remain separate claims. No paid provider
execution is part of this work. Exact outcomes: private
`private qualification records`.

## Manual authoring after this update

- Text: **+ Step → AI task**, enter **Prompt**, then choose Provider and Model ID
  in that node's inspector. Save, then **Run → Check run**. Missing setup is shown
  before any dispatch. Codex can select an existing qualified runtime receipt from
  this inspector; account sign-in is still checked when execution actually runs.
- Gemini image: **+ Step → Gemini image**, enter **Prompt**, choose the model and
  aspect ratio. A prompt-only request needs no upstream file-producing node.
  Optional reference files are under **More inputs**. API execution still requires
  a configured Gemini connection and explicit paid opt-in.
- Files: choose local files or compatible upstream outputs, order the list, then
  **Apply files**. The workflow binds selected immutable copies. A later change to
  the original local file does not silently change the saved workflow input.

These are setup instructions, not evidence that a live model was executed.

## Verification outcome

365 checks /34 lifecycle groups passed on a frozen source copy, with candidate
runtime bytes matched before installation. Native AI/Gemini prompt setup and saved
Gemini reopen verified; text Run preparation succeeds without submitting a run.
Native file selection could not be completed because the automation stalled in the
macOS Go To popup. File registration, ordered bindings and save/reopen passed
offline; do not describe their native interaction as fully verified. The existing
qualified Codex receipt was selected through the installed setup bridge, with no
model call. Both services are stopped and all9 historical table counts/hashes match.
