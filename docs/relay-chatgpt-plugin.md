# Task Relay for ChatGPT

Task Relay 0.4.2 is a skills-only plugin: turn useful ChatGPT conversations into
reusable Skills and work you can pick up again. ChatGPT supplies interpretation,
review and native file creation. No Relay MCP server, tunnel, custom panel,
separate Relay account or Desktop connection is required.

## Use it

1. After useful discussion, invoke Task Relay and ask **Make this reusable**.
2. Review the proposed standard Skill and work snapshot independently. Ask for
   changes to either; ignore an output that is not worth keeping.
3. Explicitly approve/save only the output(s) you want. ChatGPT uses its available
   native file tools to create a Skill folder ZIP and/or versioned `.relay.md`.
4. In a fresh chat, attach/select your saved files, give the new request and ask
   **Continue saved work**. The original chat is unnecessary.
5. After the task, **Update saved work** proposes instance changes as a new file.
   **Improve Skill** proposes reusable lessons separately. Review before export.

A Skill contains standard `SKILL.md` YAML name/description and useful supporting
resources, covering when to use, inputs, instructions, outputs, checks and
exceptions. A work snapshot retains objective, conclusions, decisions/proposals,
evidence, artifact references, open questions and next actions. Saving a snapshot
never accepts every proposal. Referenced artifacts need their contents supplied
separately when relevant.

## Boundaries

Use only current context and explicitly supplied material. Do not request or
reconstruct a full transcript. The plugin cannot enumerate ChatGPT history or
Library files, automatically discover the latest version, execute local tools,
install Skills or synchronize a catalog. The user selects which files to resume.

File creation/selection depend on the current host capabilities. An unavailable
native tool must be reported honestly, with reviewed text as a fallback; no fake
attachment or external-server substitution is allowed. A typed save request and
a displayed download link are distinct from evidence that a user downloaded it.

Work metadata preserves the exact capture request and selected base identity.
When producing a linked update, use the actual selected base file bytes for its
SHA-256 and the host's actual clock for creation time. If those bytes are not
available, ask for the selected file instead of inventing a lineage hash.

## Package and publication

`plugins/relay/` is the canonical skills-only package. Its `plugin.json`, existing
logo and `skills/make-reusable/` have no MCP configuration or app bindings.
Build a portable archive with:

```sh
python3 scripts/build_relay_plugin.py --out /absolute/private/relay-work
```

The receipt stays outside the ZIP. Building does not install, register, submit or
publish the plugin. See [connection/publication](relay-chatgpt-connection.md).
Publisher pages describe only this skills-only workflow. This version is free,
with no purchases or payment processing, and targets all supported countries.

The earlier custom-panel source remains under `plugins/relay/hosted/`, with its
[historical implementation](relay-chatgpt-hosted-panel.md) and
[connection guide](relay-chatgpt-hosted-connection.md). Explicit `--python` or
`--endpoint` builds preserve those development profiles. They are excluded from
the default skills-only archive. Local project/database integration remains
separate and preserves its existing records. The temporary hosted web runtime
was stopped after the user chose this native workflow.

## Qualification

Packaging checks cover exclusion of servers/app bindings, exact workflow files
and preserved earlier builds. Skill metadata and publisher pages are checked
separately. Native ChatGPT capture, file export and fresh-chat reuse require actual
host evidence; controlled MCP/DOM checks of the old panel do not qualify them.
Directory review and publication are separate outcomes from a private installation.
