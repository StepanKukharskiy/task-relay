# Local job authoring

Available from Task Relay 0.13.323. The installed app exposes saved canvas jobs
through the same validators, artifact store and run controller used by its UI.
An agent can discover relevant node contracts and edit a job without importing
Relay modules, writing its database or reading implementation files.

## Entry point and skill

On macOS, use the launcher in the user's installed app:

```sh
RELAY="/Applications/Task Relay.app/Contents/Resources/resources/runtime/relay"
"$RELAY" author commands
"$RELAY" author skill-install --destination "$HOME/.codex/skills/relay-author"
```

Python package installations use `task-relay author`. The Mac launcher uses bundled
Python, independent of the current directory. Commands honor the selected desktop
data binding and explicit path overrides; a malformed binding fails instead of
silently selecting another folder. No source checkout is needed. An older app
must update before these commands become available; see [local management](local-management.md).

Skill installation is explicit, preserves an identical installed copy and refuses
to overwrite a different copy or follow destination symlinks. It does not register
an MCP server or change other agent settings. The skill becomes available when
the agent reloads its skill inventory, normally in a new chat. `relay-manage` covers
installation and recovery; `relay-author` covers jobs. Conversation-reuse plugins
have a separate purpose.

## Discover the contract

Each command accepts one JSON object with `--input FILE` or `--input -` for stdin.
Omitting input means `{}`. Requests are limited to 600,000 bytes; workflow documents
retain their existing size limit. Responses are JSON with `protocol: 1`, `version`,
`ok`, `action`, and `result` or `error`. Errors exit with status 2. Preserve the
request identity after an interrupted or unsuccessful response and inspect the
saved state before retrying.

```sh
printf '%s' '{"command":"edit-preview"}' | "$RELAY" author commands --input -
printf '%s' '{"query":"blender"}' | "$RELAY" author operations --input -
printf '%s' '{"id":"blender.animate"}' | "$RELAY" author operation --input -
```

`commands` lists the public commands; `commands` with a command name returns its
exact input schema. `operations` gives compact search results. `operation` returns
one registered definition, ports, media types, defaults, preparation schemas and
runtime guidance. `schema` returns the canonical workflow and node schemas.
Read only the relevant operation contracts, rather than loading the whole registry.

| Command | Purpose |
| --- | --- |
| `jobs` | Page saved drafts; `{"kind":"job"}` pages workspace jobs. Follow `next_offset`. |
| `open` | Read `{"kind":"draft","id":"…"}` or an owning `canvas` run, including revision and workflow. |
| `setup` | Read configured model/tool availability without configuring credentials. |
| `files`, `file-import` | List selected inputs or register explicitly chosen absolute paths as immutable artifacts. |
| `templates`, `template` | Inspect built-in templates. A returned workflow can seed a draft; a returned package requires import through Jobs → Templates first. |
| `edit-preview`, `edit-save` | Validate and save a revision-bound edit without running it. |
| `run-preview`, `run-start` | Preview and explicitly admit a saved revision for one node ID or `all`. |
| `run-status` | Read a run's status and artifacts without advancing or retrying work. |
| `skill`, `skill-install` | Locate or explicitly install the bundled authoring skill. |

Workspace listings also contain chats, plans and legacy jobs. They are not all
editable canvases. Open the selected draft or the owning canvas, preserving its
existing node IDs, inputs, values and exact artifact bindings.

## Edit without execution

Supply the full proposed workflow and the user's exact request to `edit-preview`:

```json
{
  "target": {"kind": "canvas", "id": "owning-run-id", "revision": "saved-revision-sha256"},
  "title": "Existing job title",
  "workflow": {},
  "request": "The user's exact change request"
}
```

The empty workflow above is a placeholder: use the actual document returned by
`open`, modified within the requested scope. For a new draft, use
`{"kind":"new","id":null,"revision":null}`. Preview returns a normalized
`proposal`, fingerprint, changed-node summary and validation details. It does not
save. Send exactly `{"proposal":…, "fingerprint":…}` to `edit-save` when the edit
is authorized. Keep the preview-generated canonical UUID `request_id` intact.

Save repeats validation and checks the original revision and operation contracts.
The exact user request is retained with the revision. Canvas history remains in
its immutable event journal; replaced draft records are retained under
`node-drafts/history/ID/REVISION.json`. Existing execution assignments are unchanged.
A retry matching the current completed save returns `reused: true`; a stale
request cannot overwrite a later revision. An incomplete attempt can be retried
with its original identity after inspection. Application update/recovery locks
also protect these mutations.

## Execute only when requested

`run-preview` takes `target`, saved `revision`, `scope` and `values`. Scope is one
node ID or `all`. The result contains a `command` with its request ID and a
`preview` with the fingerprint, compiled plan, blockers and review requirements.
Existing exact upstream artifacts can be reused without resubmitting completed
producers. Preview does not grant execution.

`run-start` takes that `command`, `preview.fingerprint`, and explicit
`allow_paid`, `approve_host_code`, and `acknowledge_uncertain` choices. Use false
and empty arrays unless those scopes are authorized. Host approvals bind the
reviewed node and code digest. Uncertainty acknowledgment authorizes a separate
attempt; it does not claim the previous attempt failed. The existing admission
controller rejects changed inputs, stale previews and insufficient approvals.

From 0.13.324, a stopped Codex node with Files or isolated Local Python tools can
offer a separate attempt when its exact terminal receipt records only unknown
model replies. Run that node individually and explicitly acknowledge the retained
attempt. Its assignments, files, receipts and unknown response stay unchanged;
the new attempt does not resume its session or replay its calls. Missing stop
evidence, unfinished Python/native effects, broader tool authority and whole-job
replacement remain blocked. Updating Relay does not itself retry the job.

Successful start means admitted, not completed. Keep its run ID and inspect it
with `run-status`. Relay's service owns dispatch; the CLI does not start a second
scheduler or automatically retry work. An exact repeated admission uses the same
request identity. Source inspection remains appropriate for a concrete defect or
explicit development work, not as a prerequisite for ordinary job editing.

## Qualification

`python3 -B -m unittest tests.test_authoring` exercises the public CLI from an
arbitrary directory, schema discovery, revision and contract rejection, retained
requests/history, duplicate recognition, updater exclusion and a composed scoped
rerun using synthetic jobs and fake workers. These tests do not establish live
provider success or clean-machine installation. Release qualification and
installed read-only checks are recorded separately.
