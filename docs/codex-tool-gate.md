# Codex implementation of the universal tool-authority contract

Relay owns operation dispatch across providers. Autonomous provider runtimes must
prove that internal local tools cannot bypass the frozen declarations. Codex uses
a small maintained patch against official upstream revision
`740e5af33c71225640e0c1c1555c514c2c93ab74` (release
`rust-v0.162.0-alpha.17.2`). This is a separate app-server executable; the desktop
application, installed CLI, saved authentication and user configuration are unchanged.

The adapter supplies `relay_tool_authority` at thread creation. Missing, malformed
or mismatched declarations fail before inference. The immutable core ToolPolicy
exposes only exact granted names. Direct tool exposure is enforced even when model
metadata normally selects code-mode-only; that metadata cannot hide the approved
callbacks behind an ungranted internal wrapper. A core runtime must also be an
eligible executor before registration and dispatch: a client-brokered dynamic
handler, or the exact provider search extension under the separate search grant. Thus shell, MCP,
plugins and future internal handlers cannot run, including when a dynamic tool
shares their name. Denial records a no-effect warning with call identity and
arguments, then returns a tool error to the model for ordinary bounded correction.
The search grant maps to hosted Responses search or the provider
`web.run` executor for models using Responses Lite. The latter preserves normal
search events and source results. Search is not enabled for ordinary workers.

The shared provider-neutral manifest and batch validation remain in
`orchestrator/tool_authority.py`. Codex-specific protocol encoding, executable
selection and enforcement live in the adapter. No domain names or workflow
controllers enter the runtime patch. Relay continues to invoke Blender, Rhino,
PPTX and other operations through their registered interfaces and exact grants.

## Build and qualify

From the repository root:

```sh
python3 scripts/build_codex_gate.py --checkout outputs/codex-gate/upstream
python3 scripts/qualify_codex_gate.py \
  --binary outputs/codex-gate/upstream/codex-rs/target/dev-small/codex-app-server \
  --output outputs/codex-gate/offline
```

Select the generated **absolute** `qualified.json` path with
`TASK_RELAY_CODEX_GATE_RECEIPT`, or place a trusted receipt at the configured Relay
data directory's `codex-runtime/qualified.json`. Receipt selection verifies the
patch and revision identifiers, all required checks, evidence hash and executable
bytes before admission and again before dispatch. Changes require qualification.
The qualifier uses an ephemeral local HTTP fixture and MCP sentinel, with no
provider credentials or paid model calls. It starts the actual binary, tests
rejection and continued dynamic dispatch, name collisions, hosted scope and
restart. It does not substitute those scripted responses for a live pipeline.

The live adapter still verifies ChatGPT authentication before inference and has
no paid API fallback. Original protocol and execution journals retain failed and
unknown outcomes. Upstream changes require an explicit patch rebase and the same
qualification, rather than silently using an unqualified installed runtime.

## Evidence, 2026-10-12

The actual custom binary passed all eleven offline enforcement checks. Forty-nine
shared Python integration cases were exercised; 47 initially passed and two search
fixtures failed because their admission setup still selected the real runtime.
Those two fixtures were corrected to inject their controlled selector and both
passed. No behavior was relaxed to make fixtures pass. Live P exposed a model-metadata override that hid permitted tools; its three
text-only replies and bounded stop are retained as a failed qualification. The
additional offline case failed against the retained first binary and passed after
the direct-exposure fix. Q exposed a second metadata-dependent distinction:
Responses Lite requires the client-mediated search executor. Nine turns returned
no source evidence; Q was cancelled and remains failed. The added offline case
reproduced this against the retained second binary. The final binary passed
authorized search dispatch with recorded source URLs and denial without the grant.
R reached real sourcing and Blender review, then stopped on an unresolved search
response after the adapter imposed a 120-second timeout inside a much larger
remaining operation allowance. Shared source deadline propagation was corrected
and 21 focused controlled checks passed. Its unknown outcome remains unchanged.
S completed substantive Blender correction and independent re-review, but failed
at the shared worker tool-surface transition. Persistent transports now register
the finite lifecycle ceiling, while each response remains subject to current
authority; ordinary workers receive bounded denial feedback. Controlled checks
include all six providers and the actual gated binary. T exposed a script-entry
import error before inference; that was fixed and the script entry qualified.
U reached real sourcing, native Blender/Rhino, corrected PPTX/PDF and final
independent review, but that review rejected links, copy/evidence and native review
capability. Recovery exhausted its task slots. Shared metadata, committed draft
evidence and terminal task-capacity fixes passed focused offline checks. Fresh V
ran actual sourcing, native Blender/Rhino, authored/rendered PPTX/PDF, scheduler
restart and independent reviews. Codex owned native and presentation corrections.
Final acceptance failed on remaining source evidence and presentation quality;
the unchanged task grant was exhausted. The typed capacity hold stopped further
proposals. The later shared tagged-union diagnostic fix passed 32 offline checks;
it has not been live-qualified. No full unattended pass is claimed.
Private local commands and receipts are under `private qualification records`.

## Composed live result, 2026-10-13

Fresh source-runtime attempt X passed the complete original-image sourcing, actual Blender/Rhino, PPTX/PDF workflow. Codex owned source correction, native-script recovery, final-review-driven drawing crops and deck correction, and independent re-review. The scheduler restarted after committed delegation and resumed the same job. Delivery binds exact artifact bytes to accepted reviews covering 18 rendered pages and both native previews; no manual artifact/assignment rescue or acceptance override occurred. The run used ChatGPT-authenticated Codex only, with 39 recorded auth receipts, and no paid API provider. Internal provider request counts/usage are not inferred from silence.

X consumed 27 delegated task slots and 10 owner invocations under an explicitly new 60-slot grant; per-worker requests remained 24. Offline checks separately exercise expanded graph admission, atomic over-capacity rejection and durable idempotency. W remains a failed live qualification: automatic text continuation fragmented a deck, and its unchanged grant could not fit another correction/review pair. Fixed boxes now reject overflow before commit; collection/table pagination remains available. Literal HTTPS citations are clickable and verified after reopening.

This qualifies the exercised source-runtime graph, not all providers/tools or an installed Relay service. Retail alternatives retain unknown price/dimension/stock/photo fields; geometry uses labeled estimated dimensions. Final review used registered native saved/reopened evidence and previews, not a second application rerun. PPTX rendering used LibreOffice; native PowerPoint/Keynote fidelity and SketchUp were not exercised. Original failed attempts, exact requests/responses/reactions, final hashes and commands remain in ignored outputs/shared-boundary-20261013 and private qualification records
