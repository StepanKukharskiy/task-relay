---
name: relay-author
description: Inspect, create and edit saved Task Relay canvas jobs, discover node contracts, and preview or start explicitly requested node runs through Relay's local authoring interface.
---

# Author Relay jobs

Use the installed app's supported interface. On macOS the launcher is:
`/Applications/Task Relay.app/Contents/Resources/resources/runtime/relay`
Use the user's actual app location when different. Quote it as `"$RELAY"` below.
Python package installations use `task-relay author`.

Start with `"$RELAY" author commands`. For an unfamiliar command, request its exact
JSON input schema: `author commands --input -` with `{"command":"edit-preview"}`.
All commands accept `--input FILE` or `--input -` (JSON on stdin); omit it for `{}`.
Responses contain `protocol`, `version`, `ok`, `action` and `result` or `error`.
A successful save is not a run. A successful run-start is admission, not completion.

If `author` is unavailable, use relay-manage for an authorized app update or report
that the installed app needs the authoring interface. Do not substitute imports
from Relay's implementation, database writes or old development scripts. Source
inspection is appropriate for a concrete defect or explicitly requested development.

## Find the job and relevant contracts

- `jobs` lists saved drafts; `jobs` with `{"kind":"job"}` lists workspace jobs.
  Follow `next_offset` with the same kind. Match the user's selected job; do not
  guess from a similar title. Workspace entries may be chats, plans or legacy jobs;
  only saved drafts and owning canvases are editable through this interface.
- `open` takes `{"kind":"draft","id":"..."}` or `{"kind":"canvas","id":"..."}`.
  For an executed canvas, use the owning run ID. Retain its returned revision,
  exact workflow, values, artifact references and original node IDs.
- `operations` with `{"query":"blender"}` returns compact matching operation names.
  `operation` with `{"id":"blender.animate"}` returns that operation's actual ports,
  defaults, output media types, preparation schema and runtime guidance. Fetch only
  relevant operations. No capability is implied by a similar name.
- `schema` returns the current workflow/node schemas. `setup` reports configured
  model/tool availability. Neither grants permission or configures credentials.
- `files` lists explicitly selected inputs. `file-import` with `{"paths":["/absolute/file"]}`
  registers user-supplied files and returns immutable artifact IDs and hashes.
  Read the user's selected project files when needed; do not scan unrelated folders.

A node input is a literal `{"value":...}`, exact `{"artifact":"..."}`, an upstream
`{"task":"node-id","output":"port"}`, or a declared `{"workflow":"input-name"}`.
Registered operations own their output ports. Model nodes explicitly declare
`input_definitions`, named `outputs` and their model. Preserve existing selections.
For preparation nodes follow the operation's returned instructions: the compiler
owns hashes, envelopes and bindings. Models supply the bounded requested fragment.

## Preview and save

Create an edit request with `target:{kind,id,revision}`, `title`, `workflow` and
`request` containing the user's exact change request. For a new draft use
`target:{"kind":"new","id":null,"revision":null}`. Retrieve a built-in template
through `templates` / `template` when useful. A template returning `workflow` can
be used in a new-draft preview. A template returning `package` needs the app's
Jobs → Templates import first; then open that saved draft here. This interface
does not import portable ZIP packages. Do not invent artifact references.

Send the request to `edit-preview`. Inspect the added, removed and changed nodes,
missing inputs and connections against the user's scope. Preserve unaffected nodes
and exact saved artifact versions. Keep the returned `proposal` and `fingerprint`.

When the requested edit is authorized, call `edit-save` with exactly those two
fields. No extra confirmation is needed for an already requested reversible edit.
Relay checks the base revision and contracts again, retains the original request
and prior version, and saves without executing. If stale, reopen and reconcile the
user's change; never overwrite a concurrent edit. Preserve request IDs. An exact
completed retry is recognized; don't create a new identity after a lost response.

## Run only the requested scope

Editing or saving does not authorize running. When the user requests execution,
call `run-preview` with the saved `target`, `revision`, `scope` (one node ID or
`"all"`), and `values`. Relay returns the exact `command`, plan, fingerprint,
blockers, paid nodes, host-code reviews and uncertain attempts. Do not expand a
single-node request to the whole graph. Resolve missing inputs without rerunning
completed producers when the existing exact artifact binding can be reused.

For `run-start`, supply the returned `command` and preview `fingerprint`, plus
explicit `allow_paid`, `approve_host_code` and `acknowledge_uncertain` choices.
Use `false`, `[]`, `[]` unless the relevant execution/host-code/new-attempt scope
has actually been authorized. Host reviews bind node/digest pairs. Uncertainty
acknowledgment authorizes a separate new attempt, never proves the old one failed.
Do not auto-copy these approvals merely to make admission succeed.

Keep the returned run ID. `run-status` with `{"run":"..."}` reads progress, versions
and results without dispatching. The running Relay service owns execution. Do not
start a second scheduler, call internal advance/tick methods, or repeatedly create
new run identities. Inspect errors and retained receipts before retrying.

Report the saved revision, admitted/completed state, relevant artifacts and any
blocker. Keep local paths and job contents private unless the user asks to share.
