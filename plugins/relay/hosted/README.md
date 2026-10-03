# Task Relay for ChatGPT

**Turn useful ChatGPT conversations into reusable Skills and work you can pick up again.**

ChatGPT helps you figure out the work. Task Relay helps you keep and reuse what
was figured out.

## Make this reusable

At the end of useful discussion, invoke Task Relay. ChatGPT proposes general
know-how as a **standard Agent Skill**, instance-specific information as a
**work snapshot**, or just the category worth keeping. Review, edit and save or
ignore each independently. Nothing is saved automatically.

Skills contain `SKILL.md` and supporting resources where needed. Work snapshots
retain objectives, conclusions, decisions/proposals, evidence, artifact
references, unresolved questions and next actions. Project-specific corrections
stay separate from proposed reusable Skill improvements.

## Save and reuse

Save prepares a user-owned file: a standard Skill folder in `.skill.zip`, or a
versioned `.relay.md` work snapshot. Explicit Download is always available.
Where supported, the panel can explicitly attempt a ChatGPT Library upload;
host placement and file-type support need a connected account check.

In a new chat, select/upload your saved Skill, work snapshot, or both and supply
the new request. Task Relay prepares bounded context for ChatGPT to continue.
The original conversation is unnecessary. Update saved work and Improve Skill
produce separately reviewed outputs; previous files are not overwritten.

Skills, Saved Work and Recent show material opened/exported in this panel,
not a synchronized catalog or a search of the user's ChatGPT Library.

## Development package

The current web source is version 0.3.2, served by `task_relay.web_plugin` with
the Task Relay `plugin` dependency extra. It has no local database, Desktop
dependency, provider calls, local execution, full-history ingestion, cloud
synchronization or automatic Skill installation. It handles bounded proposals
and explicitly selected files without storing them on its server.

For local protocol development:

```sh
python -m task_relay.web_plugin
```

For a hosted ChatGPT connection, the same stateless service needs a reachable
HTTPS MCP endpoint. This source package does not deploy or publish that service.
See the [operation guide](../../../docs/relay-chatgpt-hosted-panel.md) and
[connection guide](../../../docs/relay-chatgpt-hosted-connection.md). The earlier local
project adapter remains separate and preserves its existing records.
