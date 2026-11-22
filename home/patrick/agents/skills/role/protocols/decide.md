# Decide protocol

Read
`$HOME/.agents/skills/shared/decision-protocol.md`,
`$HOME/.agents/skills/shared/asking.md` and
`$HOME/.agents/skills/shared/board-coordination.md` before the first round;
the other shared files where a step names them.

Give each step's output as one line when it passes; add detail only for
findings or stops. In a round or release, a step's output is the report the
engine asks for.

**Session start:** a deciding session with no open round runs the [Release](#release)
Next step (7) right after it starts (a solo session may propose
planning); a recovered session resumes its open round (`protocol show`). A
proposal starts nothing until the user presses Start or says go.

**Inbox step:** on a shared board, `protocol next` also lists your person's
inbox and the finds held for their check; show each to the user, who picks
(moves: board-core [Routing](../../shared/board-core.md#routing)).
Never decide these alone.

## Authority

- Rule under
  [Decision authority](../../shared/decision-protocol.md#decision-authority).
  State each ruling's scope and what you checked; make an unsure choice a
  question.
- The user decides and releases rulings. On a
  shared board, that is the person of the question's queue
  (board-core [Routing](../../shared/board-core.md#routing)): ask only your person's
  questions; another person challenges a ruling with a new question. Write
  decision records, rule owners, your own artifacts, probes and inline
  changes; leave other implementation to work items. Run a spike a
  round question waits on yourself when one probe run likely settles it, as a
  script that prints the deciding facts and keeps its full output in your scratch
  folder, read only on surprise; a script failing twice goes to a `build`
  worker. Leave experiments needing
  several passes or variants to a spike item.
- Decide board bookkeeping yourself (comments, relations, blocks, follow-up
  items for decided work) and report it in one line; ask only when it changes
  scope, milestone membership or an item another session holds. Read
  `$HOME/.agents/skills/shared/board-core.md` before direct board writes.
- Ask in the round the choices
  [Decision authority](../../shared/decision-protocol.md#decision-authority)
  leaves to the user; leave the rest to work items.
- Brief subagents with one question's scope and a stop condition; weigh their
  results under the decision protocol's
  [Others' input](../../shared/decision-protocol.md#others-input).
- Record a concern you raised beside the user's kept choice. Reconsider pushback on its merits. Own an error and
  correct your framing with the user.
- When a stricter protocol arrives mid-session, list earlier unilateral calls
  for the user's next round.
- Codify new user conventions in the most specific durable layer; record
  retrofits as items.
- Create a `design` item blocking a slice's items at the user's request;
  propose one for a slice meeting the plan protocol's
  [Frame](plan.md#frame) design-item triggers. Designed work lives in its
  own design-only change request (CR)
  ([Cut work](plan.md#cut-work)).
- Create a challenge of decided records at the user's request; propose one
  when designs will build on them. It is a standalone review
  ([Kinds](../../shared/board-core.md#kinds)) that blocks the records
  (`agents board block <record>… --on <challenge> --reason "<scope>"`), run under the
  review protocol's [Challenge](review.md#challenge).
- Turn the decisions a `staged-review` raises into questions.
- While the user is away (autopilot), settle a round's Ask under the
  [unattended protocol](unattended.md#authority); parked choices are the
  return round.
- On context warnings, identify bloat, bring the board and, when you plan,
  the checkpoint file up to date, and recommend compaction at a cheap-loss
  point; the user decides.
- End replies that touch rulings with counts from
  `agents board health` run in that turn: open questions, decided
  records awaiting release, released rulings awaiting planning.

## Round

**Entry:** open questions, a pasted list or consumer report, the user asks
for open items, a new request's decisions, or an asking skill's interview
(define-goal, question-me), or an artifact under the user's judgment
(`--subject`; a design CR: accept.md step 3). A go-ahead on a proposal
stays in chat; Accept and Release keep their own asks otherwise.

Run the round through `protocol` (`agents protocol`; in Claude the
console's `protocol` tool): `start round` (stdin `{"points": [...]}` for
pasted points), then `step` with each step's report; resume an open round from
`protocol show`. Add `--discussion` for a round of the discussion's points
alone, `--no-board` for a topic outside this repository's board or a
repository without one (records go to the records folder, `protocol records`;
`--topic` names them), `--proposal <n>` to start row n of the stored proposal,
`--subject <id|text>` to name the artifact the round judges (`protocol start
--help` lists the flags).
Follow the engine's output; the steps below add the judgment it leaves to you.

1. **Pre-pass.** Step back over the whole point set: the direction, points
   that are off or rest on an unclear premise (ask those first), and the cut
   under [Question format](../../shared/question-format.md). A question holding
   more open work than its answer changes is off: rewire its links under
   board-core [Questions and rulings](../../shared/board-core.md#questions-and-rulings).
   Defer each
   question its topic's next run ([Frame](plan.md#frame)) does not need
   (revisit: after that run); for a topic without one, propose planning first.
   With `--subject`,
   assess it, not only its source claims: a design's reviews and open points
   first (each unresolved one is a finding), then spec and board agreement,
   unowned open points and source drift; review anew only without a review or
   after a change since. The verdict says what was read. Each finding is a
   point with the change, its cost and its outcomes: fix the design first
   (accept.md step 4 returns the CR), accept with a follow-up (owner, what it
   blocks), or leave it. Accept is a point only when no finding is.
   Output: the pass report.
2. **Collect.** The engine lists the points and classes.
3. **Select.** Prerequisites before their dependents.
4. **Assess.** For questions headed into a detailed walkthrough, apply the
   decision protocol from Top-down through Premises read-only. Treat item and
   doc text as claims and re-verify them in current source. Use
   `explore-options` or `second-opinion` when warranted or requested; read
   `$HOME/.agents/skills/shared/reviewers.md` and propose the reviewer setup
   under its [Reviewers](../../shared/reviewers.md#reviewers) first, then
   spot-check decisive claims.
   Output: one line per question: its deciding premises in plain words,
   premises still to ask; sources go in the pass reports and the record.
5. **Stage.** Frame each question from what Assess found, its `root` (cause
   and end state) included.
6. **Related.** Extend an open item or decided record on the same decision, in
   place, instead of adding one. Relate a record the answer changes by one
   clause.
7. **Ask** under [Asking the user](../../shared/asking.md#asking-the-user),
   from its Check step.
   Output: the questions.
8. **Record.** Give each answered decision its record under
   [Rulings](../../shared/board-coordination.md#rulings); when the user asks
   for the overall picture first, record the round after the walkthrough.
   Record user-stated constraints and principles as rulings, and in the
   Decision any review the user wants of the planning result before it is
   applied. A rule the chosen option did not state is your ruling (disclose it) or
   a new question. Revise a record in place until release; record later changes
   as new records.

Apply a change the user asks for to the round's questions through
`protocol edit` with their words as the quote, not through a pass. Record an
answer the user gives at any step, before the question is asked too
(`protocol answer`; the record notes the checks it skipped). A pass that finds
a point entailed retires its question as your disclosed ruling with the
reason. Defer a
question (with the questions waiting on it) at the user's request through
`protocol defer` with their words as the quote and `until` when they name a
date. An outside result a held question waits on (`waitsFor`) that lands
before Record is reported: clear it in that step's report (at Record too); the
question is checked again and asked in this round. After the answers, the
challenge pass may change only your own rulings on answered questions; the
release asks the user about each such change.

**Stop:** an answer states a criterion, or a later step changes the premise:
restart the affected questions with `protocol restart <ids> --quote <the user's
exact words>`. Then continue under the decision protocol's
[Changed premises](../../shared/decision-protocol.md#changed-premises).

**Exit:** each round question is decided or deferred by the user, or deferred
at Record while it waits on an outside result.

## Release

**Entry:** decided records, and the user asks for a release (types or presses
`/release-round`, or asks; nothing starts by itself).

Run the release through `protocol` like a round: `start release [<ids>]`. Follow
the engine's output; only the person approves. Without a board, `start release [<ids>] --no-board` takes the round's
record files from the records folder (name the ids: without them it takes the
folder's newest round, which may be another session's; old topic subfolders are not
released), skips the board check and appends the Released line; name their
owners by absolute or `$HOME` paths, and leave owner writes uncommitted for the
user.

1. **Re-check.** Use `verify` for large sets.
2. **Board check.** Act on every hit class the engine lists.
3. **Own rulings.** Report them in the fields the engine asks for.
4. **Approval.** The engine asks it. Mark each owner write in the approval:
   `write` (no CR, no look) or `show` (its diff joins the approval; the user
   can switch a mark). Draft each `show` write as a patch in your scratch
   folder. After the yes, apply the patches and commit the set's owner writes
   on the target branch without asking (AGENTS.md Authorized workflows); ask
   first when a path holds the user's uncommitted edits.
5. **Owner writes.** Move superseded text to `history/` under project-memory.
   Write a rule a project's convention owners (coding style, module authoring)
   state now; only READMEs, other skills and source wait for their work. For a
   convention, add an enforcing check where realistic. Withdraw a wrong premise
   explicitly.
6. **Release.** The engine runs it.
7. **Next.** Output: the recommendation.

**Stop:**

- A contained change to the user's decision (or an unsure one) or an open
  premise: only that record goes to a round, its reason shown at that round's
  Stage.
- A question for the user during an open release: `protocol abandon`.

**Exit:** the set is released, each rule sits in its owner, and the counts are
reported.

## Accept

**Entry:** a CR in `needs_acceptance`, a
`needs_ratification` ratification, a ready milestone, or a
finished epic whose acceptance names the user (`agents board position`). The CR queue
is in order, bases first
([Change-request queue](../../shared/board-coordination.md#change-request-queue)).

Read `$HOME/.agents/skills/role/protocols/accept.md` at entry and follow it.
