# Universal collection interfaces

Status: implemented, packaged-runtime qualified and installed. Live
research quality and unattended room delivery are separate acceptance checks.

Relay now uses registered lifecycle hooks and a shared collection compiler.
Plants, furniture and component records differ through semantic field definitions
and source policy. They do not select separate stores, batching loops or recovery
controllers. The historical sourcing names remain compatibility interfaces; old
plans retain their contract identity, providers, input versions and authorization.

## Implemented boundaries

| Responsibility | Code owns | Model supplies |
| --- | --- | --- |
| Planning | Compatible typed ports, resolved paths, review companions, dependencies and scoped capabilities | Requested subjects, fields, quantity goals and task intent |
| Collection | Registered source adapters, ordering, capacity, checkpoints and found/missing outcomes | Queries and judgments within the declared source policy |
| Records | IDs, literal field extraction, validation, transactional receipts, amendments and projections | Exact evidence spans, comparisons, explicit unknowns and gaps |
| Recovery | Exact baseline binding, preserved captures, confirmed-stop eligibility and dependent versions | Additional fragments and correction judgments |
| Review | Duplicate/hash/count checks and exact candidate versions | Semantic correspondence and visual/factual judgments |
| Presentation | Record-to-slide projection, source/image bindings, editable PPTX creation and bounded layout correction | Content intent and independent quality findings |
| Accounting | Existing whole-workflow timing/token aggregation across attempts and recovery | Provider usage receipts; missing counts remain explicitly unknown |

Registered validators interpret content. They cannot replace the controller,
expand authorization or execute code supplied in job data. Source adapters remain
necessary for Commons, observed pages and rendered browser reads; format adapters
remain necessary for PPTX and other files.

## Compact collection intent

```json
{
  "records": {
    "family": {"id": "collection.options", "version": 1},
    "inputs": {
      "inventory_path": {"source": "selected-subject-artifact"},
      "source_pack_path": {"producer": "sources", "output": "delivery/source-pack.json"}
    },
    "parameters": {
      "field_definitions": {"name": "text", "price": "price", "dimensions": "text"},
      "identity_field": "name",
      "options_per_item": 3,
      "count_policy": "target",
      "max_records": 20
    }
  }
}
```

Code resolves these references to exact local versions, constructs the producer
and reviewer contracts, adds the summary companion and derives batches from the
registered work-unit costs and frozen allowances. The model submits small
fragments. It does not author the catalog, captured price, Markdown envelope or
composed source pack. Indexed context includes relevant subject evidence rather
than repeating unrelated source-page indices.

Field definitions currently support bounded text and captured price rules.
A different content type needs a registered validator/format adapter; it does not
need a new scheduler. For example, botanical name and climate use text fields;
name, price and dimensions use text/price fields; designation and load rating use
text fields through the same interface.

The shared native interfaces are `records.merge`, `images.catalog` and
`collection.slides`. They reuse the same adapters as the historical sourcing
interfaces. `images.catalog` binds images to exact source pages or, when explicitly
configured, catalog subject identity. Commons fallback requires that subject
policy and retains reuse metadata. Missing photos remain explicit. A bounded
catalog can contain more than forty photo subjects; the common bundle capacity,
input/output bytes and time limits still apply.

A target of three accepts zero, one or five supported alternatives and records
shortfalls. An explicitly required minimum remains a requirement. Unknown fields
are data, never guessed facts. Semantic review still matters: code can prove a
literal price and URL, but cannot prove that the photographed chair matches that
retailer variant. Incorrect facts need correction; quantity shortfalls under a
target policy do not add a user approval gate.

## Checkpoints and recovery

The collection engine validates the entire saved snapshot before dispatch. It
records intent before an adapter call and commits the confirmed outcome afterward.
Committed outcomes are reused; an unresolved intent needs its exact receipt to be
reconciled. A restart never guesses whether an uncertain external request ran.
The record store preserves exact submitted fragments, amendment history and
receipts. Confirmed continuation uses registered eligibility rather than family
name tests, preserving spent attempts and frozen allowances.

Recovery composition uses the declared catalog family, exact inventory hash and
sealed baseline field configuration. Old captures keep their indices, new captures
are appended, and the composed source export reaches review, joins and the deck
builder. A changed baseline or semantic configuration is rejected before new
records commit. The saved-plan compiler does not append another replenishment
round or repartition its already bounded pairs.

## Inspection and qualification

`orchestrator.operation_contracts.interface_catalog()` exposes serializable record
schemas/builders, lifecycle capabilities, code/model ownership and registered
planning capacity. Desktop Library data includes this as `record_interfaces` and
also exposes native adapter and scope metadata. Runtime registration contains
46 operations and 9 content-contract families. The baseline audit counted 43
operations and 7 families before these additions; those baseline receipts remain
preserved in ignored local storage.

The shared controlled harness in `tests/test_universal_interfaces.py` exercises
three field configurations through the same compiler and runtime. It covers
0/1/5 alternatives, an empty inventory, 42 photo subjects, derived partitions,
reviewed joins, exact source/photo versions, Commons fallback, real editable PPTX
creation, final review and automatic layout correction without human decisions.
It also covers amendments, confirmed continuation, restart, commit failures,
uncertain effects, stale versions and sealed-baseline recovery composition.
Public transports and model judgments are scripted; the native document and
record code runs normally. Historical regressions remain to protect saved work.

Actual commands, results and limitations are recorded under ignored
`outputs/universal-interface-integration/`. The source integration check passed
203 tests; the initial maintained-runtime package check exposed a wording
regression and its corrected check passed 218 tests. Later recovery integration
passed 27 tests. The final maintained-runtime check passed 219 tests in 63.606 seconds, with no exclusions. The signed installed bundle and all 62 cumulative overlays match that candidate; fresh core service health was observed. The installer retained its separate Messages permission status. No new live sourcing was dispatched by this work.
No paid provider or live room sourcing ran in these controlled checks.
