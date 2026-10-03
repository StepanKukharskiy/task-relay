# Legacy private project connection

Historical database-backed development setup; use the [web connection guide](relay-chatgpt-connection.md) for the current portable V1.

# Connect Task Relay to ChatGPT

The development connection serves real saved work through Task Relay's MCP
server and renders its bundled interface inside a compatible ChatGPT host.
The static HTML preview is separate. Test one deliberately connected project
before preparing public distribution.

## Private development connection

Use [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
to connect a local stdio server without a public listener. Tunnel setup requires
Platform tunnel permissions and a runtime API key; ChatGPT Developer mode is a
separate account/workspace permission. Credentials stay local.

Prepare a project-scoped connection directory with the Python environment that
already has Task Relay's `plugin` extra:

```sh
python3 scripts/prepare_relay_chatgpt.py \
  --out /absolute/private/chatgpt-test-v1 \
  --python /absolute/relay-plugin-env/bin/python \
  --db /absolute/private/state.sqlite \
  --project EXACT_WORK_ID
```

The command validates that the project exists, then writes a private stdio
launcher, local developer profile, tunnel launcher and `CONNECT.txt`. It neither
starts a tunnel nor registers a plugin. The server uses the selected live
database; captures and explicitly reviewed changes persist there. It exposes
only the chosen project. Use a separately retained database copy if the test
should have its own work history.

1. Open [ChatGPT on the web](https://chatgpt.com/), then its account settings.
   The official connection guide uses **Settings → Security and login → Developer
   mode**. These are ChatGPT settings, separate from Codex's settings in the
   desktop app. If the switch is absent on the web too, check account/workspace
   access rather than searching Codex settings for it.
2. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels).
   Create a tunnel and associate it with the target ChatGPT workspace. Ensure
   your account has permission to use it.
3. Download `tunnel-client` using the link in tunnel settings. Keep its runtime
   API key in your local environment or enter it at the hidden launcher prompt.
4. Run the generated launcher in Terminal:

   ```sh
   /absolute/relay-plugin-env/bin/python /absolute/private/chatgpt-test-v1/start-tunnel.py \
     --tunnel-id YOUR_TUNNEL_ID --client /absolute/tunnel-client
   ```

   It initializes a named profile, runs the client's doctor and keeps the tunnel
   running. Its MCP command uses absolute paths, so it does not depend on your
   Terminal's working directory. Stop it with Ctrl+C after testing.
5. In **ChatGPT Plugins → + / Add**, open **Create MCP App**. In the earlier
   interface, open **Create app**, then **Create MCP App** if an archive-upload
   dialog appears. Use the name **Task Relay** and select **Connection → Tunnel**.
   Choose the tunnel from the list or enter its exact ID; the form should resolve
   its name. **No tunnels yet** means Platform setup and workspace association
   must be completed first. This local stdio server uses tunnel access without
   a separate OAuth login: select **No authentication** for this private test.
   Create the connection and inspect the discovered tools. **Create plugin** is
   a separate package authoring path.
6. Complete the app's **Connect** step. If the post-creation dialog cannot load
   connection details, open the registered plugin's **More actions → Manage**
   page and use **Connect** there. Registration alone can leave the underlying
   app disconnected. Verify **Connected accounts** and **Connected on** before
   testing; do not create another app to retry this step.
7. Enable the connection in a new chat and ask **“Open my work in Task Relay.”**
   A single authorized project opens automatically. Otherwise choose work from
   the sidebar.

These steps follow the official [connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).
If Developer mode or Tunnel is unavailable, account/workspace access must be
resolved or the server must use a reachable HTTPS deployment. Do not substitute
the preview URL or a local file URL in ChatGPT.

## Exercise the real work loop

Use a project already connected to Task Relay; installation does not ingest your
chat library. Keep a short private record of prompts, observed tool calls,
results and any errors. Do not record a whole chat log as plugin evidence.

| Step | Action | What to verify |
| --- | --- | --- |
| Understand | Open Current and inspect supporting records | Objective, unknowns, considered/cited coverage and reviewed state are clear; unverified candidates remain candidates. |
| Continue | Choose one suggested action, inspect the context, then send it | Task Relay prepares and validates that exact action before the host receives its context; stale context is rejected. |
| Capture | Explicitly ask to retain the result notes/questions, or use Capture result in the component | A saved continuation receives the supplied notes; the overview shows changed work. Decisions and artifact selections remain separate reviews. |
| Return | Start a fresh chat, reopen Task Relay and refresh understanding | Captured notes remain available from the server; the new overview cites connected evidence and reflects limitations. |

ChatGPT's optional widget persistence retains only navigation identities and the
capture-packet ID. It does not store work records, confirmation tokens or result
drafts. Reopening always fetches fresh authorized work. Hosts without that
extension still use the same durable server data; select the project again and
use the packet ID returned by the continuation tool for capture.

For the return-to-work comparison, answer the same questions using original
chats and Task Relay: objective, current decisions/artifacts, unresolved issues
and next action. Record time, missing information and misleading claims. Repeat
after time away. Protocol tests do not establish that this experience is better.

## Prepare public distribution

Secure MCP Tunnel is a development/private connection. Public submission requires
a stable public HTTPS MCP endpoint. The current external OAuth adapter is scoped
to one configured owner; it does not provide public multi-user tenancy. Decide
how each signed-in user's work is isolated before offering public access.

Once a real endpoint exists, create a separate portable package and ZIP:

```sh
python3 scripts/build_relay_plugin.py \
  --out /absolute/private/remote-plugin-v1 \
  --endpoint https://YOUR_ACTUAL_MCP_HOST/mcp
```

The ZIP contains only the portable manifest, remote `mcp.json`, product README
and logo. It excludes the local database, launcher, developer profile, credentials
and build receipt. The receipt stays beside the package files and lists pending
qualification. Packaging does not deploy or test the endpoint.

Before submission, finish real OAuth login/account isolation, publisher identity,
domain verification, accessible website/support/privacy/terms URLs, reviewer
sample account, connected review cases and walkthrough. Use sample work for
public review; Competition's private evidence stays outside the package.

Use [OpenAI's submission guide](https://developers.openai.com/plugins/deploy/submission)
to upload the ZIP, resolve findings, complete review and publish after approval.
A package containing registered-app references is a local installation format;
the public candidate uses the remote MCP URL instead. No registration, deployment,
review submission or publication is implied by a local build receipt.
