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

1. **Claim.** `agents board claim` for your pulls or `agents board claim <cr>` for a named
   CR ([Change requests](../../shared/change-requests.md#change-requests)).
   Work only inside its worktree from here.
   Output: `claimed <cr> (<kind>) at <path>, base <base>`, plus the holds you
   still have.
2. **Read.** The CR and its items (`agents board show <cr>`), the briefs, the
   project instructions, and every released ruling linked to them with that
   ruling's owner section; linked rulings bind, planned (closed) ones
   included. Raise a better evidence-backed alternative to a ruling as a
   question. When a ruling or landed change has
   removed an item's outcome, close it as moot, naming that ruling or change.
   Output: ruling ids and owner anchors read, or `<id> moot: <reason>`.
3. **Do.** Run the open items in dependency order yourself or through item
   workers; you judge how they share the worktree.
   - Design items: architecture where open, the package graph, and
     one-way-door decisions as questions blocking their dependents, merged
     only under
     [Question format](../../shared/question-format.md#question-format); no
     implementation. Invoke the step-back skill once on the
     design before raising questions and once before handover. A CR with
     `checkpoint` set holds only its design:
     implementation items arrive after the checkpoint passes.
   - Implementation items: tests alongside the change; changelog and doc
     duties are in the item's acceptance.
     When writing skill, agent-definition, instruction or engine-printed
     instruction text, follow [skill-authoring](../../skill-authoring/SKILL.md).
   - Choices: decide what
     [Decision authority](../../shared/decision-protocol.md#decision-authority)
     lets you decide and list the two-way defaults in the hand-over
     (marking standing rules); raise every other choice as a question
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
   `agents board handover <cr> "<evidence>"` under
   [Hand-over and acceptance](../../shared/board-core.md#hand-over-and-acceptance);
   for a CR the project checks cannot test (docs only), `--no-gate "<reason>"`.
   Apply [Review policy](../../shared/acceptance.md#review-policy) and
   [Convention changes](../../shared/change-requests.md#change-requests).
   Map each addressed finding ID to its repaired scope, evidence and the gates
   its acceptor reproduces. Resolve a rebase conflict, or fix failed checks,
   and rerun it. With partial work, hand the CR back under
   [Actors and holds](../../shared/board-core.md#actors-and-holds).
   Output: `handed over <cr> to <status>`, `blocked <cr> on <id>` or
   `kept <cr> open: <next action>`.
6. **Remainders.** Record every gap and follow-up as a new item (in this CR
   when it belongs to the change, else a new CR) or question discovered from
   it.
   Output: new ids, or `none`.

## Item worker

A worker briefed with items of a CR its session holds: `agents board claim <item>`,
read the item and its rulings, work by absolute path in the CR's worktree,
run the gates, then commit and close under
[Change requests](../../shared/change-requests.md#change-requests) Items;
report to the session. It does not hand over, rebase or land.

## Worktree

- Edit files instead of overwriting them whole.
- Commit and rebase only on `cr/<id>` of the CR you hold, inside its
  worktree.
- Inventory destructive actions (deletion, reset, discard) with exact targets
  and return them to your session or the user; execute only on confirmation.

## Stop

- The brief contradicts the board, a spec or a current ruling: raise a
  question blocking the affected part; continue the rest.
- A blocker whose clean fix lies outside the CR: raise the root fix as a
  question blocking that part.
- A design gap or contradiction: raise a question that blocks its dependents.
- A refusal by the user or an approval reviewer: record it and its revisit
  condition on the CR.
- Unavailable evidence: state the unestablished claim and its acceptance
  consequence on the CR.
- The retry limit: follow it, recording in the CR's `notes`.

Questions hold the affected work items. When another blocker holds one item, block it and continue the rest; when it holds the whole CR, block the CR.
A failed setup: fix it or raise the blocker as a question, then claim the CR
again to rerun setup.

## Exit

The CR is handed over, kept open with its next action, or blocked,
and no longer held by you; remainders are recorded.
