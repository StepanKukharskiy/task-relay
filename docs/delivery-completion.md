# Final-file completion contracts

New semantic workflows ending in one ungated PPTX output derive a versioned completion contract. Other workflows may explicitly declare one. The compiler preserves the original proposal and records the derived contract. Historical workflow specifications and user selections remain unchanged.

```json
{
  "version": 1,
  "stage": "deck",
  "output": "presentation",
  "coverage": {
    "inventory": {"stage": "inventory", "output": "items"},
    "catalog": {"stage": "catalog", "output": "options"},
    "options_per_item": 3
  }
}
```

The final stage must be a production stage with the named typed output. All stage gates must be none; explicit choices cannot be bypassed. Coverage references are optional for general files and required by the image-sourcing planner guidance. They select earlier JSON production outputs, inventory before catalog, both explicitly consumed as final-stage context.

Inventory JSON contains an items array with unique id strings. Catalog JSON contains items with the same IDs and an options array per item. Each option names a public HTTPS product_url. The controller records exact missing item/alternative slots. Repeated product paths with different query strings cannot pad counts. Slot presence does not establish product facts, picture identity, stock or semantic suitability; those remain independent-review obligations.

Activation records the exact original request as the recovery authority atomically. Planning-only workflows receive no recovery grant until Resume. This mode allows four recovery cycles per stage, each at most eight tasks under the new v3 grant, 600 seconds and 24 tool/provider calls per task. Existing read-only recovery checks still reject unresolved submissions, changed backends/browser grants and unknown host effects. Paused/cancelled workflows do not continue. Exhaustion remains explicit; this is bounded continuation, not an unlimited retry policy.

A short completed catalog records a native delivery_coverage_gap receipt. The controller rechecks its immutable inventory/catalog bytes, current producer version and original coverage policy before queueing a continuation. The old completed attempts and their reviews remain unchanged; the incomplete catalog is not accepted or handed to the final stage. Atomic queueing uses the existing production planner, scheduler and recovery transaction.

Workflow completion requires the unchanged bound final artifact, confirmed finished producer receipt and an independently accepted review of that exact current producer version. Structural file checks retain the declared format/quantity bounds. Passing an intermediate report cannot complete this contract. Optional review advisories remain recorded without becoming user acceptance; genuine decisions, permissions, missing requirements and unknown outcomes retain their distinct policies.

## Qualification boundary

The controller is generic and the image/catalog count adapter does not contain retailer prices or image-specific product rules. Controlled text fixtures exercise activation, planning-only Resume, per-stage recovery allocation, missing-slot continuation, final review identity and failure handling. The integrated controlled test additionally creates and reopens a real small PPTX, exercises native photo recovery/merge and final correction, and completes delivery without user decisions. These checks do not establish live retailer availability, full 48-option coverage or real-model image matching; full live delivery qualification remains separate.

## Integrated source/photo continuation

New completion grants use recovery policy version 3: four cycles per stage, up to eight tasks per cycle, one attempt per task, 600 seconds and 24 tools/provider turns per worker. Version 1 and version 2 grants retain their saved limits. Eight tasks allow discovery/review, download/review, and merge/review without exceeding a four-task legacy allowance. Admission reads the actual saved policy rather than a module default.

`images.merge` is a fixed local companion to `images.fetch`. Its first ZIP defines the complete subject set. Subsequent ZIPs fill only missing subjects; existing photo bytes, observation metadata and attributions cannot be replaced. The result retains each source ZIP hash and passes the normal strict bundle validator. A completion-mode photo stage with missing subjects records `delivery_photo_gap` and queues recovery before downstream handoff. An all-failed, confirmed native download may recover from its preserved diagnostic ZIP. Pending or uncertain actions remain ineligible. Recovery must deliver a reviewed merge with the exact base ZIP first; original attempts remain untouched.

Discovery plans are checked after resolving worker budgets. Browser photo batches reserve four calls/turns per subject plus four for setup and finalization. Larger work is split before Start. Completion stages may compile up to 30 tasks; recovery graphs retain their smaller saved aggregate limit. A single sourced ZIP supports at most 40 subjects, so larger rooms require multiple complete photo bundles. This is a feasibility floor, not a promise that every retailer can be researched in that number of calls.

Public text sourcing can read a third observed candidate after earlier candidates fail, within the operation's existing page allocation and domain restrictions. No additional paid search, authored URL, provider switch or expanded origin is introduced. Failures remain in the source pack. Browser discovery can narrow its original subject list and use its already granted alternate search site; it cannot acquire new origins.

Completion-mode PPTX planning requires independent specification and final-file reviews, but no candidate selection gate. The existing bounded local document correction loop can revise the specification, rebuild and re-review the PPTX automatically. Initial workflow receipts freeze available worker backends; only those exact models can participate automatically. Historical workflows without that receipt retain their approval behavior.

The completion ledger includes workflow timing and token totals. Accounting starts with the original orchestrator request, includes planning calls, workers, failed/replaced runs and registered recovery/continuation lineage, and freezes elapsed time at the final workflow completion event. Native public-source search journals supply usage when the aggregate operation receipt lacks it. Registered native search procedures contribute their provider calls; other local procedure tasks do not count as model calls. Cached input is included in reported input, not added twice. Missing usage or timestamps remain explicit. A durable `workflow_usage_recorded` event saves the completion accounting; this is not a balance check or billing estimate.

Controlled integration creates a real small PPTX from recovered catalog/photo versions, requests a final-review correction, rebuilds and delivers without user decisions. This verifies native file identity and orchestration; it does not qualify live full-room product selection, retailer availability, model behavior or visual review by a real model.

## Workload and evidence interfaces

Fresh connector-companion grants calculate typed sourcing requests from the number
of item submissions, bounded inspection calls, correction reserve and finishing.
Frozen user/provider ceilings still apply. A declared batch unable to submit every
item and finish must be split before dispatch. Typed catalog/review workers receive
the next exact inventory/candidate record and use registered fragment submissions;
code parses inputs and projects the JSON/Markdown files. They do not receive generic
file-writing or whole-pack reading tools. Empty alternatives with explicit gaps
remain valid under a target-count policy.

Code supplies bounded mapped excerpts with absolute selectable field/price offsets.
Other saved passages remain accessible through the source-read interface. Older
large tool results become hash-bound archive references with exact paginated
retrieval; current observations and model signatures are retained. Saved-page CLI
reviews use exact text batches, preserving distinct capture versions and explicit
duplicate aliases, with calls reserved for the final structured report. Neither
excerpts nor mechanical duplicates establish visual correspondence or US ordering.

Prepared search uses its registered eighty-request allocation. The optional
`web.sources.rendered` connector renders only public HTTPS candidates already
observed in its source-pack input. Code preserves the original entries, appends
rendered captures/failures and wires an independent source review before catalog
creation. Its fresh scope permits an isolated unsigned-in browser and bounded
GET/HEAD/OPTIONS reads; accounts, form submission, uploads and downloads are absent.
Missing browser outcomes retain an uncertainty receipt and cannot be replayed.
Unavailable/challenged pages remain explicit gaps. The companion is added only
when available and frozen for that request; historical grants do not acquire it.

Controlled qualification covers these interfaces plus the existing recovered-data
PPTX/correction/delivery integration. Live full-room delivery, retailer coverage
and token savings must be measured separately. Exhausted historical grants remain
exhausted; deployment alone cannot authorize additional work or accept a draft.

## Code-owned catalog assembly and coverage

A fresh scope that freezes the available `sourcing.merge` companion partitions
oversized typed catalog work into feasible contiguous inventory ranges after worker
resolution. The compiler constructs producer/reviewer pairs and retains the logical
catalog output port on a registered native merge. At a 24-turn ceiling, the current
reserve allows ten items per catalog batch. Exact sealed partitions, source and
inventory versions, and supported item-version review receipts are required by the
merge; duplicate, missing and unsupported records cannot be silently joined. The
model provides evidence fragments rather than the transport graph or final files.
This catalog partitioning does not promise automatic splitting for every connector;
source queries and browser photo discovery retain their separate declared bounds.

A fresh available `web.sources.coverage` companion performs one targeted search
round for inventory subjects below the supported priced-US-option target. It derives
queries from saved item mappings and preserves existing evidence and failures.
Fresh captures still require independent source and typed product review. This is
bounded completion effort, not a guarantee that three purchasable products exist.
The producer exports the composed source pack alongside its catalog. Code verifies
that export against exact native capture ancestry and regenerates its expected bytes;
a model-authored assertion of provenance is insufficient. Current catalog, source,
photo and slide versions propagate together through logical delivery ports.

For an explicitly frozen target policy, prospective semantic review treats quantity
shortfalls and missing photos as disclosed advisories. Incorrect prices, product or
variant identity, unsupported purchase claims, links and supplied photos remain
correction findings. Strict required-count scopes keep their original requirements.
Code-owned coverage recovery permits guarded baseline-record amendments while
preserving every previous version; it does not rewrite old contracts or verdicts.

Confirmed finished workers that commit new typed records and yield with an explicit
budget finding can resume under the existing completion cycle grant, even before
hitting the literal ceiling. The controller rechecks receipt, input, review-target,
record and assignment identities before dispatch and resumes only committed progress.
Unknown outcomes, missing inputs and zero-progress repeats stay held. Lifetime
attempt counters can cross three only through this code-owned, separately recorded
checkpoint continuation; the model retry schema stays bounded at three. An exhausted
historical grant remains spent. A new exact human request can authorize a separate
four-cycle extension for its stopped stage; its own request and baseline identity are
recorded and used as successor authority.

Normal desktop intake qualification uses a small image and controlled provider,
reviewer and network seams, with real native specification/PPTX/render/delivery.
It includes an early checkpoint yield, controller reconstruction and a twelve-item room flowing through code-generated catalog partitions and merge. Separate tests
cover zero/one/five alternatives, stale versions, unsupported review, correction and
unknown outcomes. These checks establish controller behavior, not live retailer
coverage, real-model visual matching, or unattended full-room product quality.

A first-request Gemini HTTP402 rejection can preserve an inherited typed catalog
or review checkpoint, but cannot trigger automatic retry under an older grant.
An exact new human recovery request must bind that stopped baseline. Code requires
one rejected request, zero worker tools, no pending response, recorded HTTP402
outcome and nonempty unfinished checkpoint; input/provider/criteria/limits remain
unchanged. Dispatch rechecks the outcome bytes and committed authorization.
This path performs no balance check and never assumes a top-up succeeded; the
new provider response determines whether execution can continue.
