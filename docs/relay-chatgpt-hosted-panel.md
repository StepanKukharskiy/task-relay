> Historical custom-panel MCP prototype. The current skills-only plugin is documented in [the main guide](relay-chatgpt-plugin.md).

# Task Relay — ChatGPT Web Plugin

**Turn useful ChatGPT conversations into reusable Skills and work you can pick up again.**

ChatGPT helps you figure out the work. Task Relay helps you keep and reuse what
was figured out. The 2026-10-02 brief supersedes the database-backed web-plugin
direction. The [earlier local runtime guide](relay-chatgpt-local-runtime.md)
preserves its contracts and evidence; Desktop and its saved records are unchanged.

## Product loop

**Make this reusable → Review → Save/export → Select in a new chat → Continue.**

ChatGPT analyzes useful context already available in the conversation and
proposes two separate outputs where relevant:

- **Reusable Skill:** general know-how, using standard Agent Skills structure.
  `SKILL.md` has YAML name/description, when to use, inputs, instructions, output
  requirements, checks and relevant exceptions. Supporting UTF-8 resources may
  use `references/`, `scripts/` and `assets/`; exported scripts never run here.
- **Work snapshot:** objective, current conclusions, decisions/proposals,
  evidence, artifact references, questions and next actions for this instance.

One useful category is enough; the model should not invent a Skill for every
conversation. Each output starts with Review and Ignore. Review opens a readable
preview, with file editing and selected-prior-version comparison under details.
The user explicitly chooses Download or optional Save to ChatGPT after review;
there is no extra confirmation checkbox or intermediate file-preparation step.
Nothing is persisted by a proposal, and exporting does not accept every decision
or install a Skill.

Save packages standard Skills as `skill-name.skill.zip`, containing
`skill-name/SKILL.md` and any supplied supporting files. Work exports as
`work-id-r001.relay.md`: ordinary Markdown with YAML identity, revision, exact
capture request, timestamp and prior-snapshot hash. The body retains seven work
categories. Work metadata is not a proprietary Skill format.

Download always remains available. The panel feature-detects ChatGPT Library
selection/upload. Library helpers and support for generated Markdown/ZIP exports
are host-dependent and require an actual account test. It never depends on
overwriting, listing or automatically finding all Library files.

## Reuse and capture

In a fresh conversation, the user selects/uploads one Skill and/or one work
snapshot. The selected files appear together, followed by the new request.
Continue in ChatGPT prepares their exact contents and supporting resources with
that request, up to 60,000 characters, and sends them on that explicit click.
Preview what will be shared is optional and sends nothing. Oversized context is
rejected without truncation; changed inputs during preparation block dispatch.

ChatGPT executes the requested task using its available tools and permissions.
References to artifacts are not the artifacts themselves: inaccessible files
must be reported or explicitly supplied. The original conversation is unnecessary.
Selected content cannot authorize unrelated tool calls or external actions.

**Update saved work** requires the selected work snapshot. Relay preserves its
work ID and creates revision + 1 linked to the exact prior bytes. Edited identity,
revision or parent hash cannot silently switch an update to another job.
**Improve Skill** requires the selected Skill and produces a separate proposal.
Project-specific lessons never become global instructions automatically. Neither
action overwrites a previous file or installs a Skill.

## Interface

The 0.3.1 first-use screen has two choices: Make this reusable and Continue saved
work, with a short explanation for each. File controls appear only after choosing
the continuation path; the request appears after opening files. Update saved
work and Improve Skill live under Keep changes from this chat, and appear only
for the relevant selected file type. Skills, Saved Work and Recent remain under
Other files opened here. A new chat starts with a new selection; these labels do
not imply a server catalog, cloud sync or library-wide access. Graph is absent.

The component reuses Task Relay's existing logo and Desktop control styles. It
uses normal document flow and declares inline and fullscreen support, preferring
inline for the conversation's review/capture interaction. It does not force an
inline panel to expand. Actual placement remains a host decision. It notifies
content height and consumes the initial tool result without another opener
request. Proposal previews render as safe text; raw files appear only when
editing. The first capture action sends a readable chat request. New proposals
append without discarding existing review edits. A host upload failure retains
the reviewed download. No work data is put in localStorage or widget state.

## Tools and runtime

`task_relay.web_plugin` exposes six tools:

| Tool | Purpose |
| --- | --- |
| `relay_open_reusable` | Open the empty review/reuse panel; no catalog discovery. |
| `relay_propose_reusable` | Validate bounded ChatGPT-derived Skill/work proposals and selected bases. No save. |
| `relay_import_portable_file` | Read explicitly supplied Markdown or a text-resource Skill ZIP. |
| `relay_import_selected_file` | Read an explicitly selected ChatGPT file using the supported file-input contract. |
| `relay_prepare_reuse` | Prepare exact selected material and the new request within the context budget. |
| `relay_review_export` | App-only explicit Save: return exact reviewed download bytes; no server file write. |

The packaged `make-reusable` Agent Skill gives ChatGPT the workflow and category
boundaries. The server validates/packages supplied proposals; it does not call
another model, infer chat history, execute scripts, use a local `.relay` database,
record workflows or store user files. Requests are independent. There is no
separate Relay account requirement for this stateless workflow.

Direct selected-file fetching accepts bounded HTTPS ChatGPT file origins only,
without redirects or inherited proxy credentials. Unknown origins and expired
links fall back to direct upload. Archives have bounded entry/byte limits, safe
relative paths and UTF-8 resources; duplicate paths, symlinks, encryption,
ambiguous metadata and YAML aliases are rejected. Binary Skill assets are not
supported by this text-resource V1.

## Run and package

Install the source runtime with its `plugin` extra in an isolated environment.
`mcp==1.30.0` and `PyYAML==6.0.3` provide protocol and standard header validation.
Run the web server through stdio:

```sh
python -m task_relay.web_plugin
```

Build a local source profile without a database:

```sh
python3 scripts/build_relay_plugin.py --out /absolute/private/relay-web-v1 --python /absolute/relay-plugin-env/bin/python
```

For an HTTPS deployment behind an ingress:

```sh
python -m task_relay.web_plugin --transport http --host 0.0.0.0 --public-origin https://YOUR_ACTUAL_HOST
```

Then build the remote package using `--endpoint https://YOUR_ACTUAL_HOST/mcp`.

For an isolated container, use `scripts/build_relay_web_server.py --out` with a
new private deployment directory; see [hosting](../plugins/relay/server/README.md).
The HTTP transport reports its version at `/health` and bounds request size,
upload inactivity, concurrency and per-process request rate. These guards do not
store request bodies or user identities. The custom review panel needs this
hosted code even though no user work is stored there. A skills-only package can
instead use the host's native conversation/file controls without a Relay server;
it does not provide this custom panel or deterministic server validation.
The builder preserves previous directories/ZIPs and excludes local data and
credentials. Public hosting still needs request limits, rate controls, publisher
policies and connected qualification. The local source/profile is not a deployed
or published plugin. See [connection and testing](relay-chatgpt-connection.md).

Explicit `--db` profile builds still target the legacy local runtime; they do not
include the new web workflow Skill. Their old work-state APIs are not exposed by
the web entrypoint.

## Acceptance and evidence

The target is: useful messy discussion → Make this reusable → independently
review/export Skill and work → new chat → select saved material → continue
correctly, without finding the original chat. Verify that a work update preserves
remaining questions/decision status and that a Skill improvement needs separate
review. Compare what the user can resume with what would otherwise need searching.

Controlled small-text tests cover actual export/import/reuse, exact edits, work
lineage conflicts, independent categories, corrupt/unsafe files, over-budget
context, no database access, fresh-call isolation and actual SDK stdio. The
controlled UI uses the real portable Python service. Browser preview exercises
actual local HTTP MCP tool calls with synthetic proposals. These checks do not
establish model interpretation quality, live ChatGPT Library behavior, a deployed
connection or public acceptance. Commands, results and limitations are recorded
under ignored `outputs/`.
