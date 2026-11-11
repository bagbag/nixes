# Work protocol

Read
`$HOME/.agents/skills/shared/board-core.md`,
`$HOME/.agents/skills/shared/change-requests.md`,
`$HOME/.agents/skills/shared/decision-protocol.md` and
`$HOME/.agents/skills/shared/acceptance.md` before
step 1.

## Entry

One of: an `open` change request (CR) is ready for your session's `design` or
`implement` pull; a dispatch brief names a CR and this protocol; a brief names
items of a CR your session holds (then [Item worker](#item-worker)).

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops.

1. **Claim.** `board claim` for your pulls or `board claim <cr>` for a named
   CR ([Change requests](../../shared/change-requests.md#change-requests)).
   Work only inside its worktree from here.
   Output: `claimed <cr> (<kind>) at <path>, base <base>`, plus the holds you
   still have.
2. **Read.** The CR and its items (`board show <cr>`), the briefs, the
   project instructions, and every released ruling linked to them with that
   ruling's owner section; linked rulings bind, planned (closed) ones
   included. Bring a better evidence-backed alternative to a ruling as a
   question (global Challenge on receipt). When a ruling or landed change has
   removed an item's outcome, close it as moot, naming that ruling or change.
   Output: ruling ids and owner anchors read, or `<id> moot: <reason>`.
3. **Do.** Run the open items in dependency order yourself or through item
   workers; you judge how they share the worktree.
   - Design items: architecture where open, the package graph, and needed
     decisions as questions blocking their dependents, merged only under
     [Question format](../../shared/question-format.md#question-format); no
     implementation. Before raising the questions and again before handing
     over, invoke `step-back`, then `ground`, on the design; repeat until a
     pass changes nothing. A CR with `checkpoint` set holds only its design:
     implementation items arrive after the checkpoint passes.
   - Implementation items: tests alongside the change; changelog and doc
     duties are in the item's acceptance.
   - Choices: rule those that stay inside the CR's files and are cheap to
     change under
     [Decision authority](../../shared/decision-protocol.md#decision-authority)
     and list them in the hand-over; raise every other choice as a question
     blocking the affected part, and continue unaffected parts.
   - After each pass: run the item's gates, then commit and close its items
     under [Change requests](../../shared/change-requests.md#change-requests)
     Items.
   Output: per pass: items, commit sha, gate lines; for a design, what each
   pass changed.
4. **Evidence.** Run the CR's gates under Acceptance
   [Evidence and gates](../../shared/acceptance.md#evidence-and-gates); keep
   each command and outcome for the hand-over comment.
   Output: one line per gate: command, exit code, and passed/failed/skipped
   counts for tests.
5. **Hand over.** With every item closed and complete evidence,
   `board handover <cr> "<evidence>"` under
   [Hand-over and acceptance](../../shared/board-core.md#hand-over-and-acceptance).
   Map each addressed finding ID to its repaired scope, evidence and the gates
   its acceptor reproduces. Resolve a rebase conflict, or fix failed checks,
   and rerun it. With partial work, `board unclaim <cr>` with the remainder in
   `notes`.
   Output: `handed over <cr> to <status>` or `kept <cr> open: <remainder>`.
6. **Remainders.** Record every gap and follow-up as a new item (in this CR
   when it belongs to the change, else a new CR) or question discovered from
   it; planning sessions (plan protocol Entry) place them under
   [Milestones](../../shared/board-coordination.md#milestones).
   Output: new ids, or `none`.

## Item worker

A worker briefed with items of a CR its session holds: `board claim <item>`,
read the item and its rulings, work by absolute path in the CR's worktree,
run the gates, then commit and close under
[Change requests](../../shared/change-requests.md#change-requests) Items;
report to the session. It does not hand over, rebase or land.

## Worktree

- Edit files instead of overwriting them whole.
- Commit and rebase only on `cr/<id>` of the CR you hold, inside its
  worktree; other Git: the global Git rule.
- Inventory destructive actions (deletion, reset, discard) with exact targets
  and return them to your session or the user; execute only on confirmation.

## Stop

- The brief contradicts the board, a spec or a current ruling: raise a
  question blocking the affected part; continue the rest.
- A blocker whose clean fix lies outside the CR: stop that part and raise
  the root fix as a question that blocks it (global Fix at the root).
- A design gap or contradiction: raise a question that blocks its dependents.
- A refusal by the user or an approval reviewer: record the refusal and its
  revisit condition on the CR (global Sandbox and permissions).
- Unavailable evidence: state the unestablished claim and its acceptance
  consequence on the CR.
- The retry limit (global Retry limit): follow it, recording in the CR's
  `notes`.

When a blocker holds one item, block the item on it and continue the rest; planning moves a waiting part to
another CR. When it holds the whole CR, block the CR and `board unclaim` it.
A failed setup: fix it or raise the blocker as a question, then claim the CR
again to rerun setup.

## Exit

The CR is handed over, kept open with its remainder, or blocked by a question,
and no longer held by you; remainders are recorded.
