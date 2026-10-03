> Historical custom-panel MCP prototype. The current skills-only plugin is documented in [the main guide](relay-chatgpt-plugin.md).

# Connect and test Task Relay Web

The current plugin uses `task_relay.web_plugin` (0.3.2), a stateless MCP service.
It needs no Desktop installation, local project/database grants, Relay signup or
cloud synchronization. A hosted server still supplies the review/reuse tools and
bundled UI; downloading a source package does not deploy that server.

The [product and operation guide](relay-chatgpt-plugin.md) describes the current
scope. The [legacy connection guide](relay-chatgpt-local-connection.md) retains
the earlier Competition database/tunnel test and must not be used as public V1
onboarding.

## Existing private development connection

Keep the existing registered app and tunnel identity. Its MCP command may still
start the old local project server. Update that launcher's source to import
`task_relay.web_plugin.main` with no `--db` or `--project` flags, retaining its
previous version privately. Restarting the existing tunnel/server and refreshing
tool discovery changes this private test to the new web tools; it does not need
another app registration. The database remains untouched.

The expected tools are `relay_open_reusable`, `relay_propose_reusable`,
`relay_import_portable_file`, `relay_import_selected_file`, `relay_prepare_reuse`
and the app-only `relay_review_export`. If discovery still shows local work tools,
the old process/configuration is still active. Verify discovery after restart
before claiming the updated plugin is connected.

Secure MCP Tunnel remains a private development mechanism, not the public-user
installation flow. Credentials remain local and are not part of exported files.
An app-backed plugin uses its server and Developer Portal release process;
Plugin Creator's standalone archive editor cannot update it.

## Connected acceptance exercise

1. Enable Task Relay in a chat with useful work and ask **Make this reusable**.
2. Verify the Skill contains general method, while the work contains instance
   conclusions, decision status, evidence gaps, artifact references and next steps.
3. Review/edit and choose Download for each independently. Where available,
   separately test Save to ChatGPT and confirm actual Library placement.
4. Start a new chat, enable Task Relay and choose Continue saved work. Open the
   files, enter a new request and click Continue in ChatGPT. Previewing context
   is optional. Do not open the original chat.
5. Verify the continuation uses the right method/state, asks for missing inputs,
   and does not claim to have read inaccessible artifact references.
6. Under Keep changes from this chat, choose Update saved work. Review the changes,
   new revision and retained questions. Export it without modifying the old file.
   Test Improve Skill separately.

Record supplied prompts, observable results, file hashes, missing information and
any misleading claims. Do not retain a whole transcript as plugin evidence.
Controlled fixtures establish transport and file behavior; only this exercise
establishes the actual ChatGPT experience.

## Hosted/public distribution

Deploy the stateless web service at a stable HTTPS `/mcp` endpoint. Use bounded
request sizes/rates, no user-content access logs, and the hosting provider's
normal process limits. This stateless file workflow does not need an account
store; a future private persistent catalog would require its own identity and
authorization design.

Build the connection package only after a real endpoint is available:

```sh
python3 scripts/build_relay_plugin.py --out /absolute/private/relay-web-remote-v1 --endpoint https://YOUR_ACTUAL_MCP_HOST/mcp
```

The ZIP contains the manifest, remote MCP configuration, workflow Skill with its
reference, README and existing logo. It does not contain a database, project
evidence, credentials or a local launcher. Packaging does not host or publish.

Public submission additionally needs publisher/domain verification, accessible
website/support/privacy/terms information, connected test cases and a reviewer
walkthrough. Use synthetic work for review. Keep existing plugin/app identities
and audience when releasing an update. Follow [OpenAI's submission guide](https://developers.openai.com/plugins/deploy/submission)
and the submission skill when public submission is requested.
