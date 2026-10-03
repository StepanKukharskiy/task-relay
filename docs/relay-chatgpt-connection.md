# Test and publish the skills-only plugin

Task Relay 0.4.2 uses native ChatGPT skills and file capabilities. There is no MCP
URL, runtime server, Secure MCP Tunnel, API key or Relay account to connect.

Build the default package using `scripts/build_relay_plugin.py --out` with a new
private output directory. Inspect the ZIP: root package identity `relay-work`,
Task Relay logo, one make-reusable Skill and its work-format reference. Exclude
`mcp.json`, app bindings, old server profiles, databases and receipts.

Save/install that package as a private plugin for rehearsal. Updating the previous
app-backed development wrapper may require a separate native package, since its
generated account identity is not the canonical source package identity. Preserve
the old prototype and its recovery records; do not retry a name mismatch using an
invented package name. Later edits use the native plugin's verified account ID,
current release ID and existing audience.

## Acceptance exercise

Use synthetic data in a new ChatGPT conversation with the native Task Relay
plugin selected. Make a method and instance progress reusable. Verify that the
Skill is general, work facts are separate, decisions remain proposed and neither
output is exported automatically. Approve one output at a time and obtain actual
files through native file tools. Keep the exact exported versions.

Open another new chat, explicitly attach/select those files and state a new
request. Verify continuation without the original conversation, visible evidence
gaps and no inferred artifact contents. Then separately test Update saved work
and Improve Skill. A work update is a new revision based on the actual selected
file; a Skill change needs its own review.

## Public release

The publisher website, support, privacy and terms pages must be public and match
this version's practices. Configure them in `extensions.com.openai.interface`.
The confirmed publisher is Stepan Kukharskiy, the service is free with no commerce,
and country restrictions are empty to cover all platform-supported countries.
Actual identity verification still needs confirmation in the submission portal.

Prepare and validate the final skills-only ZIP, then upload it to the public
submission portal with the intended verified developer identity. Skills-only
packages do not need MCP review cases, a server connection, reviewer login or an
MCP demo video. Resolve scans and have the authorized publisher complete the
current legal/policy attestations. Upload creates a draft; submitting requests
review. Publish only the intended approved release and verify the result.

See [OpenAI's submission process](https://developers.openai.com/plugins/deploy/submission).
No private plugin registration, code change or local check establishes public
publication. Keep deployment, account and test receipts in ignored private storage.
