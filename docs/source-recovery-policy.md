# Shared source recovery policy

Registered evidence readers use the same collector and compiler contract across
providers, isolated rendering and native reading. No publisher or product-specific
rule is involved. Historical assignments and receipts are unchanged.

## Selection and retention

The compiler advances a recovery input to its unique confirmed append-only
descendant in the same run and operation grant. The registered `evidence_extension`
hook defines the relation; shared code verifies exact input identities, terminal
operation receipts, output materialization and artifact hashes. This works for
standalone operations and committed in-worker operations even when the worker
subsequently stopped blocked. Larger files and newer timestamps are not proof.
Original proposals and artifacts remain intact; `evidence_recovery_bound` records
the exact chain and explicitly confers no acceptance. Uncertain, active or
unproven producers cannot supply a replacement. Divergent confirmed branches
require an explicit merge rather than silently dropping one branch.

One recovery continuation may consume an evidence lineage at a time. Duplicate
readers are rejected atomically, including future output references. Independent
lineages and unrelated modeling/presentation work remain schedulable. Repeating
an in-worker reader with unchanged input bytes reuses its committed result, even
under a different request key. A subsequent recovery consumes that richer result.

The collector retains the literal original entries and all prior read receipts.
Each result records its parent content digest, policy and selected groups. Item
IDs define groups when present; otherwise the original literal query defines a
stable group. Existing recovery counts carry across subsequent readers. Reads
are spread among groups with the fewest prior recovery reads, preferring groups
without observations, untried URLs and less-used publishers. An observation is
not semantic acceptance or proof that purchasing facts are complete.

## Bounds

Within a retained source lineage, policy version 1 permits at most three recorded
attempts per canonical URL, including original HTTP retrievals, and one recovery
attempt per reader class. Native helper versions and observation limits do not
reset the native-reader count. Captured URLs are not reread. Publisher hostnames
have a four-recovery-read ceiling and at most two reads in one batch. Tracking-only
URL variants share the existing conservative URL identity. Original operation,
time, request and domain limits still apply; these caps only reduce dispatch.

Selection exhaustion returns an explicit `no_eligible_unread_candidates_under_scope_and_caps`
outcome and retained evidence. It does not authorize fresh searches, broader
domains, another provider, acceptance, or a replay of uncertain effects. These
are continuation limits, not a global prohibition on separately authorized new
research with different evidence. Safari's unresolved scroll failure from AR is
preserved; this policy does not claim to fix that native host failure.

## Qualification

Controlled qualification and original logs are in
`private qualification records`. Tests use small synthetic documents,
scripted model decisions and controlled host observations, through the real
compiler, collector, scheduler, artifact and review boundaries. They establish
the exercised recovery paths, not live sourcing quality or complete cross-tool
success. The fresh complete workflow remains a separate live qualification.
