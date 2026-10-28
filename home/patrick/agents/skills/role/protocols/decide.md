# Decide protocol

Deciding with the user: rounds of questions, release of rulings, and
acceptance of designs and user-judged outcomes. Read
`$HOME/.agents/skills/shared/decision-protocol.md`,
`$HOME/.agents/skills/shared/asking.md`,
`$HOME/.agents/skills/shared/reviewers.md`,
`$HOME/.agents/skills/shared/work-tracking.md`,
`$HOME/.agents/skills/shared/project-memory.md` and
`$HOME/.agents/skills/role/protocols/review.md` before the first round.

Give each step's output as one line when it passes; add detail only for
findings or stops.

## Authority

- Rule under
  [Decision authority](../../shared/decision-protocol.md#decision-authority);
  bring every other choice to the user. State each ruling's scope and what you
  checked; make an unsure choice a question.
- The user decides and releases rulings and owns staging and commits. Write
  decision records, rule owners, your own artifacts, `/tmp` probes and inline
  changes under the global instructions' Orchestration; leave other
  implementation to work items.
- Decide in the round every contract consumers see: API shape, names,
  defaults, error and failure behavior, limits. Leave only internals and
  sequencing to work items.
- Brief subagents with one question's scope and a stop condition. Re-derive
  every choice yourself and treat their results as evidence, not conclusions.
- When the user keeps a choice you challenged, follow it and record the
  concern beside it. Reconsider pushback on its merits. Own an error and
  correct your framing with the user.
- When a stricter protocol arrives mid-session, list earlier unilateral calls
  for ratification.
- Codify new user conventions in the most specific durable layer; record
  retrofits as items.
- Draft and advance contracts with the user through `define-goal`; release a
  contract revision like any ruling.
- Create a `design` item blocking a slice's items at the user's request;
  propose one for a slice meeting the plan protocol's
  [Frame](plan.md#frame) design-item triggers.
- Use `staged-review` when the user asks for an implementation review; turn
  the decisions it raises into questions.
- While the user is away, raise blocked choices as unassigned questions and
  list them in the return round.
- On context warnings, identify bloat, bring the board and, when you plan,
  the checkpoint file up to date, and recommend compaction at a cheap-loss
  point; the user decides.
- End replies that touch rulings with counts from
  `board health` run in that turn: open questions, decided
  records awaiting release, released rulings awaiting planning.

## Round

**Entry:** open questions, a pasted list or consumer report, or the user asks
for open items.

1. **Collect.** List open items (`board health --items decided,questions,ratification,review,user`). Account for every point of a pasted list or report and check it against the
   current tree. Classify each as already ruled (cite its owner), the planning
   session's call, your ruling or user decision. For open items, list decided
   records awaiting release first, then open questions, then
   `needs_ratification` records, then `in_review` designs, ready milestones
   and finished epics whose acceptance names the user (`board position`).
   Output: one row per point: id, class.
2. **Select.** Choose one round under
   [Asking the user](../../shared/asking.md#asking-the-user); decide
   prerequisites before their dependents (`board bd dep tree <id> --direction=up`).
   Claim the round: `board claim <ids>`.
   Output: round ids.
3. **Related.** Run `board related <terms>` per question, for its own terms
   and for the modules and APIs its options build on.
   Extend an open item on the same decision instead of adding one. Comment
   on or hand off overlaps with items other sessions hold.
   Output: board check table: question, related hits, action.
4. **Ground.** Run the decision protocol from Top-down through Premises
   read-only across the round. Ground questions headed into a detailed
   walkthrough yourself. Treat item and doc text as claims and re-verify them
   in current source. Use `explore-options` or `second-opinion` when warranted
   or requested; propose the reviewer setup under
   [Reviewers](../../shared/reviewers.md#reviewers) first and spot-check
   decisive claims.
   Output: one line per question: premises with their evidence, premises
   still to ask.
5. **Walk through and ask** under
   [Asking the user](../../shared/asking.md#asking-the-user), from its Check
   step.
   Output: the walkthrough and the questions.
6. **Record.** Record each decision when made under
   [Questions and rulings](../../shared/work-tracking.md#questions-and-rulings)
   and set status `decided`; when the user asks for the overall picture first,
   record the round after the walkthrough. Record user-stated constraints and
   principles as rulings, and in the Decision any review the user wants of
   the planning result before it is applied. Check each record against the wording of the chosen
   option; a rule the option did not state is your ruling (disclose it) or a
   new question. Revise a record in place until release; record later
   changes as new records. Close ratified `needs_ratification` records under
   the same reference.
   Output: `decided <ids>`.

**Stop:** an answer states a criterion, or a later step changes the premise:
restart the affected questions under the decision protocol's
[Changed premises](../../shared/decision-protocol.md#changed-premises).

**Exit:** each round question is decided, re-asked in the next round, or
deferred by the user.

## Release

**Entry:** decided records without open blockers, and the user asks for a
release.

1. **Re-check.** Compare each record with current items and source and with
   the set's other records for coherence; verify citations and counts
   (`verify` for large sets). Where something changed since the decision,
   run the Check step of [Asking the user](../../shared/asking.md#asking-the-user)
   on the changed part.
   Output: one line per record: unchanged, or the change.
2. **Board check.** Run `board related <terms>` across the
   set, closed items and canonical docs included (`--docs <doc paths>`), and
   act on every hit class:

   | Hit | Action |
   |---|---|
   | Earlier ruling it revises or contradicts, closed included | Name it under Prior rulings; supersede it in step 6. |
   | Open question it duplicates or answers | Merge, or answer and close. |
   | Open question its own premise rests on | Hold the record; it blocks release. |
   | Open item assuming the old state | Block it on the record (`board bd dep add <item> <record>`); comment the revised clause. |
   | Deferred item assuming the old state, or one it unblocks | Relate it; comment the revised clause. |
   | Item another session holds on the same concepts | Comment or hand off. |
   | Doc, README or skill stating the old rule | Owner write in step 5, or a task. |

   Output: board check table: record, one row per hit class (`none` allowed),
   action.
3. **Own rulings.** List every ruling you made in the set.
   Output: own-rulings table with the disclosure fields of
   [Asking the user](../../shared/asking.md#asking-the-user).
4. **Approval.** Offer each set for release separately. Conditional approval
   covers only that round's items, once steps 1-3 hold.
   Output: the user's approval, quoted.
5. **Owner writes.** Write each rule into its one owner, replacing the text it
   supersedes (old text to `history/` under project-memory), and name path and
   anchor in the record's `## Rule owner`. For a convention, add an enforcing
   check where realistic. Withdraw a wrong premise explicitly.
   Output: one line per rule: owner path and anchor.
6. **Release.** `board release <ids>`, then per revised
   record `board supersede <old> --with <new>`, with
   `--partial` when one rule of it changes.
   Output: released and superseded ids.
7. **Next.** List waiting questions, `in_review` designs, ready milestones,
   finished epics whose acceptance names the user and what waits on the user
   (`board health --items user`);
   recommend one next step by priority and what it unblocks; wait for the
   user.
   Output: the list and the recommendation.

**Stop:** a re-check or board check changes a ruling: return it to the round.
`board release` refuses a record (failing `board bd lint`): fix its
text, rerun step 6.

**Exit:** the set is released, each rule sits in its owner, and the counts are
reported.

## Accept

**Entry:** an `in_review` design item, a ready milestone, or a finished epic
whose acceptance names the user (`board position`).

1. **Claim** a design item or milestone: `board claim <id>`.
   Output: `claimed <id>; author <actor>`, `claimed <id> (milestone)`, or
   `epic <id>`.
2. **Evidence.** Check the named evidence under the review protocol's
   [Evidence and gates](review.md#evidence-and-gates).
   Output: one line per gate: command, result.
3. **Walk through** the design or outcome result with the user under
   [Asking the user](../../shared/asking.md#asking-the-user).
   Output: the walkthrough.
4. **Close or return.** Close on the user's acceptance
   (`board bd close <id> --reason "<verdict>"`). Otherwise return a design
   with the findings (`board return <id> "<findings>"`); for an epic, create
   the findings as items under it; for a milestone, create them as members
   and unclaim it (`board unclaim <id>`). When the item received a ruling, check
   that the rule sits in its owner and every conflict became a question.
   Output: `closed <id>`, `returned <id>` or `findings <ids>`.

**Stop:** the user rejects the design or result: return the design, file the
findings under the epic, or add them to the milestone. A required gate cannot
run: return it naming the unestablished claim.

**Exit:** the item is closed or returned, or the milestone has new members.
