# Review protocol

Independent assessment and acceptance of handed-over work. Read
`$HOME/.agents/skills/shared/board-core.md`,
`$HOME/.agents/skills/shared/acceptance.md`,
`$HOME/.agents/skills/shared/decision-protocol.md` and
`$HOME/.agents/skills/shared/reviewers.md` before step 1.

## Entry

One of: an `in_review` task, bug or spike, standalone reviews included, is
ready for your session's `review` pull; a dispatch brief names an item id and
this protocol. Deciding sessions accept design items and user-judged epics
under the decide protocol.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops. A challenge follows [Challenge](#challenge) in place of
steps 3-7.

1. **Claim.** `board claim` for your pull or
   `board claim <id>` for a named item; it prints the author
   doer. You are independent when you are not that doer; a fresh-context
   worker of the same session suffices. `author unknown (<holder>)` names a
   hand-over by a retired role holder (e.g. goal-agent): you are independent.
   An item no one ever held is a standalone review
   ([Kinds](../../shared/board-core.md#kinds)): it has no author and needs
   no independence check.
   Output: `claimed <id>; author <actor>; independent`, or
   `claimed <id>; standalone review`.
2. **Read.** The item's acceptance, its brief, the released rulings it links
   and their owners, the author's evidence comments, and the changes in its
   zone. Current rulings and supersessions win over older briefs and verdicts.
   Output: ids and owners read.
3. **Gate.** Select the gate under [Review policy](../../shared/acceptance.md#review-policy).
   Output: gate and reason.
4. **Evidence.** Apply [Evidence and gates](../../shared/acceptance.md#evidence-and-gates) to every
   required gate.
   Output: one line per gate: command, result, accepted or reproduced.
5. **Assess.** Check correctness, the global Cleanliness tests and the
   decision protocol's
   [End-state criteria](../../shared/decision-protocol.md#end-state-criteria);
   triage the author's disclosed judgment calls; classify scope growth under
   [Expansion findings](#expansion-findings).
   Output: verdict; then each confirmed defect, risk and open question.
6. **Fix.** Apply a small, contained fix that is the only realistic clean
   option, unless the brief forbids assessor fixes; return larger fixes to the
   author.
   Output: each fix with its diff location, or `no fixes`.
7. **Close or return.** Close only when certain everything is clean and every
   required gate passed: `board bd close <id> --reason "<verdict>"`. Otherwise
   return it with verdict, confirmed defects, open questions, executed checks
   and next action: `board return <id> "<findings>"`.
   Raise a choice that needs a decision as a question blocking the item. For a
   standalone review, record each finding as a new item discovered from it
   (`--deps discovered-from:<id>`), then close it with the verdict.
   Output: `closed <id>`, `returned <id>` or `question <id>`, plus
   the new item ids for a standalone review.

## Stop

- You are the author doer: `board unclaim <id>`, report it, stop.
- A required gate cannot run: return the item naming the unestablished claim
  and its acceptance consequence.
- Repairs on the same problem reach the retry limit (global Retry limit):
  follow it; comment attempts, remaining failure and root-cause hypothesis on
  the item.

## Exit

The item is closed, returned to the queue or blocked by a question, and the
output lines above are posted.

## Challenge

A standalone review of decided records or a contract draft, before release.

1. **Assess.** Invoke `step-back` on the records and the owners and items
   they rest on, then `challenge-rulings` on the records' rulings; check contradictions with each other
   and with released rulings, integrity and security holes, and gaps a
   realistic consumer hits.
   Output: verdict; each finding with its evidence.
2. **Close.** Create each finding as a question discovered from the
   challenge (`--deps discovered-from:<id>`) and block the record it concerns
   on it (`board block <record> --on <question> --reason "<finding>"`), then
   close the challenge with the verdict.
   Output: `closed <id>`, plus the question ids.

## Assessor conduct

- The author repairs; the same assessor checks repairs and the affected
  invariants. Repair completion reopens no broader review.
- Independence: [Reviewers](../../shared/reviewers.md#reviewers).

## Expansion findings

Classify each under
[Concern classes](../../shared/decision-protocol.md#concern-classes). When
reviews keep adding structure without runnable progress, pause affected
fan-out, re-derive the premise with an architect, test a smaller coherent
option against the earliest runnable checkpoint and bring the options to the
decider.
