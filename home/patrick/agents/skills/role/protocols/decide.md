# Decide protocol

Read
`$HOME/.agents/skills/shared/decision-protocol.md`,
`$HOME/.agents/skills/shared/asking.md` and
`$HOME/.agents/skills/shared/board-coordination.md` before the first round;
the other shared files where a step names them.

Give each step's output as one line when it passes; add detail only for
findings or stops. In a round or release, a step's output is the report the
engine asks for.

**Session start:** a deciding session with no open round runs Release 7's
[Next](#release) step right after it starts (a solo session may propose
planning); a recovered session resumes its open round (`protocol show`). A
proposal starts nothing until the user presses Start or says go.

## Authority

- Rule under
  [Decision authority](../../shared/decision-protocol.md#decision-authority);
  bring every other choice to the user. State each ruling's scope and what you
  checked; make an unsure choice a question.
- The user decides and releases rulings and owns staging and commits. Write
  decision records, rule owners, your own artifacts, `/tmp` probes and inline
  changes under the global instructions' Orchestration; leave other
  implementation to work items. Run a spike a round question waits on
  yourself when one probe run likely settles it; leave experiments needing
  several passes or variants to a spike item.
- Decide board bookkeeping yourself (comments, relations, blocks, follow-up
  items for decided work) and report it in one line; ask only when it changes
  scope, milestone membership or an item another session holds. Read
  `$HOME/.agents/skills/shared/board-core.md` before direct board writes.
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
- Create a challenge of decided records at the user's request; propose one
  when designs will build on them. It is a standalone review
  ([Kinds](../../shared/board-core.md#kinds)) that blocks the records
  (`board block <record>… --on <challenge> --reason "<scope>"`), run under the
  review protocol's [Challenge](review.md#challenge).
- Use `staged-review` when the user asks for an implementation review; turn
  the decisions it raises into questions.
- While the user is away (autopilot), settle a round's Ask under the
  [unattended protocol](unattended.md#authority); parked choices are the
  return round.
- On context warnings, identify bloat, bring the board and, when you plan,
  the checkpoint file up to date, and recommend compaction at a cheap-loss
  point; the user decides.
- End replies that touch rulings with counts from
  `board health` run in that turn: open questions, decided
  records awaiting release, released rulings awaiting planning.

## Round

**Entry:** open questions, a pasted list or consumer report, the user asks
for open items, a new request's decisions, or an asking skill's interview
(define-goal, question-me). A go-ahead on a proposal stays in chat; Accept and
Release keep their own asks.

Run the round through `protocol` (`$HOME/.agents/bin/protocol`; in Claude the
console's `protocol` tool): `start round` (stdin `{"points": [...]}` for
pasted points), then `step` with each step's report; resume an open round from
`protocol show`. Add `--discussion` for a round of the discussion's points
alone and `--no-board <dir>` for a topic outside this repository's board, or a
repository without one. Follow the engine's output; the steps below add the
judgment it leaves to you.

1. **Collect.** Check each point against the current tree before classifying
   it.
2. **Select.** Prerequisites before their dependents.
3. **Related.** Extend an open item or decided record on the same decision, in
   place, instead of adding one. Relate a record the answer changes by one
   clause; the release's Re-check corrects it.
4. **Ground.** Run the decision protocol from Top-down through Premises
   read-only across the round. Ground questions headed into a detailed
   walkthrough yourself. Treat item and doc text as claims and re-verify them
   in current source. Use `explore-options` or `second-opinion` when warranted
   or requested; read `$HOME/.agents/skills/shared/reviewers.md` and propose
   the reviewer setup under its [Reviewers](../../shared/reviewers.md#reviewers)
   first, then spot-check decisive claims.
   Output: one line per question: its deciding premises in plain words,
   premises still to ask; sources go in the pass reports and the record.
5. **Ask** under [Asking the user](../../shared/asking.md#asking-the-user),
   from its Check step.
   Output: the questions.
6. **Record.** Give each answered decision its record under
   [Rulings](../../shared/board-coordination.md#rulings); when the user asks
   for the overall picture first, record the round after the walkthrough.
   Record user-stated constraints and principles as rulings, and in the
   Decision any review the user wants of the planning result before it is
   applied. Check each record against the wording of the chosen option; a rule
   the option did not state is your ruling (disclose it) or a new question.
   Revise a record in place until release; record later changes as new
   records. Close ratified `needs_ratification` records under the same
   reference.

Apply a change the user asks for to staged questions through `protocol edit`
with their words as the quote, not through a pass.

**Stop:** an answer states a criterion, or a later step changes the premise:
restart the affected questions under the decision protocol's
[Changed premises](../../shared/decision-protocol.md#changed-premises).

**Exit:** each round question is decided or deferred by the user.

## Release

**Entry:** decided records, and the user asks for a release (types or presses
`/release-round`, or asks; nothing starts by itself).

Run the release through `protocol` like a round: `start release [<ids>]`. Follow
the engine's output; only the person approves. The steps below add the judgment it leaves to
you.

1. **Re-check.** Use `verify` for large sets. A correction that follows a later
   decision of the user's in the set counts as own; name that decision, and the
   approval shows the record as revised.
2. **Board check.** Act on every hit class the engine lists.
3. **Own rulings.** Report them in the fields the engine asks for.
4. **Approval.** The engine asks it.
5. **Owner writes.** Write each rule into its one owner, replacing the text it
   supersedes (old text to `history/` under project-memory). Write a rule a
   topic's design-target doc, `coding-style.md` or `module-authoring.md` states
   now; only READMEs, other skills and source wait for their work. Name
   repository paths from the board root and installed files by their installed
   path, as rendered. For a convention, add an enforcing check where realistic.
   Withdraw a wrong premise explicitly.
6. **Release.** Fix what a board refusal names (a record failing
   `board bd lint`: its text), then rerun the step with `step {}`.
7. **Next.** Run `protocol next` and follow its output; wait for the user.
   Output: the recommendation.

**Stop:**

- A spreading change, or every record leaving the set: nothing releases and the
  records stay decided and held; run the round the engine names on them (its
  check loop opens with step-back).
- A hold at approval: nothing releases; ask what it was held for and run a round
  on those records, on the set when the reason spreads. The rest stay decided
  and a later `start release` takes them.
- A question for the user during an open release: `protocol abandon`; nothing
  releases and `start release` takes the same records again.
- A contained change to the user's decision (or an unsure one) or an open
  premise: only that record goes to a round, its reason shown at that round's
  Stage.
- A contained change of your own parts: the record stays, revised; a scoped
  pass that finds the decision touched drops it.

**Exit:** the set is released, each rule sits in its owner, and the counts are
reported.

## Accept

**Entry:** an `in_review` design item, a ready milestone, or a finished epic
whose acceptance names the user (`board position`).

1. **Claim** a design item or milestone: `board claim <id>`.
   Output: `claimed <id>; author <actor>`, `claimed <id> (milestone)`, or
   `epic <id>`.
2. **Evidence.** Read `$HOME/.agents/skills/shared/acceptance.md`; check the
   named evidence under its
   [Evidence and gates](../../shared/acceptance.md#evidence-and-gates).
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
