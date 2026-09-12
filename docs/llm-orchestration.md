# LLM decisions, validated execution

Ordinary user text goes to the configured conversation model with saved state,
conversation history, project evidence and the capability catalog. The model can
answer, ask a clarification question, use the existing file/web tool loop, or return
one registered structured action. Relay does not decide the action from verbs or
question words in the message.

This change removes three language-dependent routing shortcuts:

- Guide discovery no longer runs because a message contains “create”, “update” or
  similar words. The model returns `{"kind":"discover_guides","query":"topic"}`;
  query is optional and does not replace the original request. The search visits
  at most twenty known project roots and offers at most six saved candidate guides.
  User selection resumes the same request with complete selected guide versions.
  No matches also resumes the request with a recorded result; repeat discovery for
  the same request is rejected, preventing a search loop.
- Production focus no longer hides task/capability catalogs unless the user uses
  certain handoff words. One model context includes both. Instructions explain that
  ordinary editorial feedback belongs to the focused production, while an explicit
  handoff can share an unreviewed draft without accepting or advancing that run.
- Research source identities are never guessed from “two” or the catalog size.
  With a nonempty research catalog, Codex routing must include `research_ids`:
  selected IDs, or `[]` for none. Missing fields or nonexistent IDs fail validation.

Deterministic code still handles slash commands, reply addresses, guide choice
buttons, schema validation, known project/file access, hashes, queue receipts,
task availability, budgets and approval gates. Search ranking still uses lexical
matching; it retrieves evidence and does not authorize actions. Destination guide
checks remain part of the handoff adapter after the LLM selects a destination.

The runtime is still limited to implemented tools/actions. This does not add
arbitrary pipeline creation, unrestricted command execution, cross-task memory
synchronization, or automatic provider fallback. Provider errors preserve the
request and do not turn into a procedural guess about what the user meant.

Regression tests exercise structured model outputs and execution boundaries.
They do not establish that a live model will always choose the right action.
