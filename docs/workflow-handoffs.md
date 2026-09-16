# Declared workflow handoffs

New `plan_pipeline` actions use `contract_version: 1`. Every stage has a `handoff`
with `outputs` keyed by its existing deliverable IDs, and an `inputs` list of edges.
This contract applies to inferred workflows as well as templates; it does not
prescribe research, modeling or presentation as a fixed sequence.

An output declares `media_type` and may declare `max_bytes`, `slides` (PPTX only),
and `companions` (other output IDs from the same stage). Unknown byte sizes and
slide counts are reported as unknown, not presented as verified capacity.
An input names an earlier `stage`, `deliverable`, matching `media_type`, and
`consumer`: either `context` for worker preparation or the exact selected operation
for a direct file input. Research/conversation results are inline context; a worker
must prepare a file before a registered operation can consume them directly.

For example, a Rhino stage can declare a native model and a separate PNG preview.
A visualization stage can consume that preview; a presentation stage can consume
the resulting image and research context. Raw native model files cannot be used
as direct image-generation or PPTX inputs. Companion declarations require paired
edges, such as an image and its provenance document.

The compiler checks declared edges, operation versions/availability, types, known
byte bounds and input counts before the first workflow stage starts. A single
PPTX currently supports 50 slides and 50 MB; a declared 600-slide requirement is
rejected before workers start. The planner must retain explicit requested quantities.
It must not omit the quantity, shrink it or substitute multiple final decks to pass
validation. Automatic section assembly is not implemented.

At stage planning, logical outputs are bound to exact task outputs and input edges
to the exact upstream artifact IDs. Equal hashes do not authorize substituting a
different selected version. Clarification and preparation-to-execution retain those
bindings. Registered operations and workers retain their existing source checks,
schemas, limits, review and approval requirements. Declared byte bounds, UTF-8 text
and exact PPTX slide counts are also checked when outputs are collected. The PPTX
builder checks declared count against expanded slides before creating the file.

Managed image stages produce one selected PNG and accept up to six exact image
references. They use the declared image edges rather than every previous image.
Textual context remains in the saved request; native files remain available for
appropriate consumers without being forwarded as image references.

Saved workflows and legacy procedure exemplars are not silently upgraded. Their
original contracts remain in effect. New typed procedures preserve their saved
handoffs when proposed for review.

If a complete new proposal has incompatible or noncanonical type declarations,
Relay allows one structural correction before dispatch. It supplies registered
operation types and keeps both responses. That correction has no research/file
tools and may change only media-type fields and corresponding edge types. It
cannot change quantities, stage instructions, providers, gates, limits or explicit
user format requirements. Unsupported capacity and uncertain provider responses
are not automatically retried. A confirmed saved rejection can be recovered through
a validated type-only successor without overwriting the failed request.

These checks establish declared compatibility and artifact identity, not semantic
correctness. They do not prove that an AI used research accurately, that a generated
image preserves geometry, that native files are valid outside their host validators,
or that every provider/OS combination works. Unknown future sizes and task schemas
still need execution-time checks. Unified repair eligibility and large-document
assembly remain separate work; uncertain external submissions are never replayed.
