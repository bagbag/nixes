# Work protocol

Doing one claimed design or implementation item. Read
`$HOME/.agents/skills/shared/work-tracking.md`,
`$HOME/.agents/skills/shared/decision-protocol.md` and
`$HOME/.agents/skills/role/protocols/review.md` (Evidence and gates) before
step 1.

## Entry

One of: an open item is ready for your session's `design` or `implement`
pull; a dispatch brief names an item id and this protocol.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops.

1. **Claim.** `board claim` for your pulls or
   `board claim <id>` for a named item.
   Output: `claimed <id> (<kind>)`, plus the items you still hold.
2. **Read.** The item (`board bd show <id>`), its brief, the project instructions,
   and every released ruling linked to it with that ruling's owner section;
   linked rulings bind, planned (closed) ones included. Bring a better
   evidence-backed alternative to a ruling as a question (global Challenge on
   receipt). When a ruling or landed change has removed the item's outcome,
   close it as moot, naming that ruling or change.
   Output: ruling ids and owner anchors read, or `<id> moot: <reason>`.
3. **Areas.** Comment the files and modules you expect to edit on the item;
   claims inform others and are never refused.
   Output: `areas: <list>`.
4. **Do.** Design items: architecture where open, the package graph, and
   needed decisions as questions blocking their dependents; no implementation.
   Implementation items: tests alongside the change. Rule trivial and entailed
   choices under
   [Decision authority](../../shared/decision-protocol.md#decision-authority)
   and comment them on the item; raise every other choice as a question
   blocking the affected part, and continue unaffected parts.
   Output: one line per completed part.
5. **Evidence.** Run the item's gates under the review protocol's
   [Evidence and gates](review.md#evidence-and-gates); comment each command
   and outcome.
   Output: one line per gate: command, exit code, and passed/failed/skipped
   counts for tests.
6. **Hand over.** With complete evidence, hand over under
   [Hand-over and acceptance](../../shared/work-tracking.md#hand-over-and-acceptance).
   In the handover evidence, map each addressed finding ID to its repaired
   scope, evidence and the gates its acceptor reproduces.
   With partial work, follow its step 2 and unclaim the item
   (`board unclaim <id>`).
   Output: `handed over <id>` or `kept <id> open: <remainder>`.
7. **Remainders.** Record every gap and follow-up as a new item or question
   discovered from this item; planning sessions (plan protocol Entry) place
   them under [Milestones](../../shared/work-tracking.md#milestones).
   Output: new ids, or `none`.

## Shared working tree

- Edit files instead of overwriting them whole; when an edit fails as stale,
  re-read and retry.
- Leave others' changes in place; attribute failures in their areas instead
  of fixing them.
- Cross-cutting mechanical sweeps edit in-flight files too; adapt your work to
  a sweep that touched it.
- Tracked-file moves use `git mv`: as a dispatched worker, supply the rename
  map to your dispatcher and edit after the move; when your session does the
  item itself, run `git mv`. Keep Git otherwise read-only; staging and commits
  belong to the user.
- Inventory destructive actions (deletion, reset, discard) with exact targets
  and return them to your session or the user; execute only on confirmation.

## Stop

- The brief contradicts the board, a spec or a current ruling: raise a
  question blocking the affected part; continue the rest.
- A blocker whose clean fix lies outside the item: stop that part and raise
  the root fix as a question that blocks it (global Fix at the root).
- A design gap or contradiction: raise a question that blocks its dependents.
- A refusal by the user or an approval reviewer: record the refusal and its
  revisit condition on the item (global Sandbox and permissions).
- Unavailable evidence: state the unestablished claim and its acceptance
  consequence on the item.
- The retry limit (global Retry limit): follow it; comment attempts, remaining
  failure and root-cause hypothesis on the item.

When a question blocks the whole item, unclaim it (`board unclaim <id>`).

## Exit

The item is handed over, kept open with its remainder, or blocked by a
question, and no longer held by you; remainders are recorded.
