# Artifact replacement decisions — A02

Relay can record that one exact saved selection replaces another **within the same
recorded job and decision purpose**, then mark affected outputs for review. This
works for registered file types across applications. Both versions must already
have saved selection decisions; a draft, filename, newer date or matching hash is
not enough. Independent jobs and different purposes are rejected.

In Telegram, ask to replace the old selected version with the new selected version.
The orchestrator uses saved decision IDs to prepare a card showing the old/new
paths and hashes, job/purpose and recorded impact. Confirm **Replace selected
version**, or **Keep current version**. Ambiguous versions need clarification.
The card does not start workers. Cards currently support Telegram, not Messages.

Confirmation checks the paired owner, delivered message, expiry, exact decision
state/revision and selected bytes. Pending feedback anywhere in the same job blocks
confirmation. Duplicate confirmation is idempotent. A reversed decision does not
revive an older card. Replacement, validity flags, events and confirmation outbox
entry commit together; a database failure rolls them back together.

**Check status** reports the number of affected outputs. **Inspect stage** and
focused orchestrator context include `artifact_replacements`: current decisions,
bounded replacement history and affected output IDs, paths and reasons. Original
selections and executed assignments remain unchanged. An outdated flag is advisory;
it does not revoke historical acceptance, cancel an existing authorization or
pause already authorized workers.

Dependencies conservatively include every declared frozen input, including prior
drafts and guides; this is not proof of semantic use. Historical replaced selections
and their transitive consumers are flagged only inside the recorded job. Traversal
can cross another job and return, but that other job's outputs are not changed.
The currently selected version stops traversal, so a revision that used the old
draft as context does not invalidate itself. Reversal recomputes flags and retains
the earlier decisions/events. Late or future registered outputs using an old
version receive flags atomically when registered. Unregistered files are outside
this graph.

To update affected work, describe the desired bounded stage. The existing
`plan_production` approval flow applies. An eligible `previous_run` carries relevant
current replacement artifacts, exact hashes and prior history without rewriting
old assignments. Its approval snapshot binds all replacement head revisions in
the job; intervening replacement requires a fresh proposal. Replacement alone does
not authorize a rebuild or bypass stage eligibility/budgets.

Local commands use exact **decision IDs**, available in inspection:

```sh
python3 -m orchestrator replacement-preview OLD_DECISION_ID NEW_DECISION_ID
python3 -m orchestrator replace-selection OLD_DECISION_ID NEW_DECISION_ID \
  --revision REVISION_FROM_PREVIEW --receipt UNIQUE_DECISION_TOKEN \
  --note 'Exact user replacement instruction'
```

The second command records the decision immediately; it does not show a Telegram
card. Reusing its receipt is allowed only for the identical old/new/revision/note.

All records use Relay's existing shared SQLite database. Views expose at most 50
replacement histories, 200 historical members per history plus its current member,
20 recent decisions per history and 200 outdated artifact/history entries, with
truncation disclosed. Preview exposes the first 50 affected outputs plus the total.
Core validity calculation and approval revision checks are not truncated; large
histories may take longer. No background watcher or second database is introduced.
