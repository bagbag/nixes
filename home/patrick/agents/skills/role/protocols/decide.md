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
(moves: [Routing](../../shared/board-core.md#routing)).
Never decide these alone.

## Authority

- Rule under
  [Decision authority](../../shared/decision-protocol.md#decision-authority);
  bring every other choice to the user. State each ruling's scope and what you
  checked; make an unsure choice a question.
- The user decides and releases rulings. On a
  shared board, that is the person of the question's queue
  ([Routing](../../shared/board-core.md#routing)): ask only your person's
  questions; another person challenges a ruling with a new question. Write
  decision records, rule owners, your own artifacts, `/tmp` probes and inline
  changes under the global instructions' Orchestration; leave other
  implementation to work items. Run a spike a
  round question waits on yourself when one probe run likely settles it, as a
  script that prints the deciding facts and keeps its full output in a scratch
  file you read only on surprise; a script failing twice goes to a `build`
  worker. Leave experiments needing
  several passes or variants to a spike item.
- Decide board bookkeeping yourself (comments, relations, blocks, follow-up
  items for decided work) and report it in one line; ask only when it changes
  scope, milestone membership or an item another session holds. Read
  `$HOME/.agents/skills/shared/board-core.md` before direct board writes.
- Decide in the round every contract consumers see: API shape, names,
  defaults, error and failure behavior, limits. Leave only internals and
  sequencing to work items.
- Brief subagents with one question's scope and a stop condition; weigh their
  results under the decision protocol's
  [Others' input](../../shared/decision-protocol.md#others-input).
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
  [Frame](plan.md#frame) design-item triggers. Designed work lives in its
  change request (CR) behind a checkpoint
  ([Cut work](plan.md#cut-work)).
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
repository without one; `--proposal <n>` starts row n of the stored proposal.
Follow the engine's output; the steps below add the judgment it leaves to you.

1. **Collect.** The engine lists the points and classes.
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
   applied. A rule the chosen option did not state is your ruling (disclose it) or
   a new question. Revise a record in place until release; record later changes
   as new records.

Apply a change the user asks for to the round's questions through
`protocol edit` with their words as the quote, not through a pass.

**Stop:** an answer states a criterion, or a later step changes the premise:
restart the affected questions under the decision protocol's
[Changed premises](../../shared/decision-protocol.md#changed-premises).

**Exit:** each round question is decided or deferred by the user, or deferred
at Record while it waits on an outside result.

## Release

**Entry:** decided records, and the user asks for a release (types or presses
`/release-round`, or asks; nothing starts by itself).

Run the release through `protocol` like a round: `start release [<ids>]`. Follow
the engine's output; only the person approves. The steps below add the judgment it leaves to
you. Without a board, `start release --no-board <dir> [<ids>]` takes the round's
record files, skips the board check and appends the Released line; name their
owners by absolute or `$HOME` paths, and leave owner writes uncommitted for the
user.

1. **Re-check.** Use `verify` for large sets.
2. **Board check.** Act on every hit class the engine lists.
3. **Own rulings.** Report them in the fields the engine asks for.
4. **Approval.** The engine asks it. Mark each owner write in the approval:
   `write` (no CR, no look) or `show` (its diff joins the approval; the user
   can switch a mark). Draft every `show` write uncommitted in the project's
   main tree before the approval: the engine prints its diff in the approval.
   After the yes, commit the set's owner writes on the target branch without
   asking: the approval is your explicit authorization.
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
- A question for the user during an open release: `protocol abandon`; nothing
  releases and `start release` takes the same records again.

**Exit:** the set is released, each rule sits in its owner, and the counts are
reported.

## Accept

**Entry:** a CR in `needs_acceptance` (finished, or at a user design checkpoint), a
`needs_ratification` item (`Ratify: <CR title>`), a ready milestone, or a
finished epic whose acceptance names the user (`board position`). The CR queue
is in order, bases first
([Change-request queue](../../shared/board-coordination.md#change-request-queue)).

1. **Claim** a CR, ratification or milestone: `board claim <id>`.
   Output: `claimed <cr> (look <look>, view <view>, checkpoint <c>); author
   <actor>`, `claimed <id> (milestone)`, or `epic <id>`.
2. **Evidence.** Read `$HOME/.agents/skills/shared/acceptance.md`; check the
   named evidence under its
   [Evidence and gates](../../shared/acceptance.md#evidence-and-gates). For a
   code CR the stored check and review must be `current` for the tip you review:
   wait for the refresh a review session took, or run it yourself under the
   review protocol's [Refresh](review.md#refresh) steps 2-3 when none did.
   Note the tip the walkthrough starts on; for a user design checkpoint, the
   `design hash` the claim printed.
   Output: one line per gate: command, result; check state and tip, or the
   design hash.
3. **Walk through** with the user under
   [Asking the user](../../shared/asking.md#asking-the-user), by the CR's
   `view`: `code`, the diff `<base>..<tip>` (in the console's review tree, or
   the range-diff of a refresh); `result`, the outcome itself. A user
   checkpoint: the design. A ratification: the landed result, in the review
   tree or at the result. If the refresh changed the CR meanwhile, show the
   range-diff before continuing.
   Output: the walkthrough.
4. **Land or return.**
   - **Accept:** `board land <cr> --tip <tip>` (the tip the user reviewed).
   - **Design checkpoint accepted:** `board land <cr> --checkpoint --design
     <hash>` (the hash from step 2).
   - **Changes wanted:** talk the root fix through with the user, then
     `board return <cr> "<findings>"`; add follow-up items to the CR.
   - **Rejected:** `board reject <cr> "<reason>"`; delete branch `cr/<id>` and its worktree only on the user's
     confirmation (they hold the only copy).
   - **Ratification:** close the item with the user's answer
     (`board bd close <id> --reason "<verdict>"`); on "no" ask what the user
     wants (fix or revert) and file it as a follow-up CR.
   - **Epic, milestone:** close on the user's acceptance
     (`board bd close <id> --reason "<verdict>"`). Otherwise for an epic, create
     the findings as items under it; for a milestone, as members, and unclaim
     it (`board unclaim <id>`).
   When the item received a ruling, check that the rule sits in its owner and
   every conflict became a question.
   Output: `landed <cr>`, `checkpoint passed <cr>`, `returned <cr>`,
   `rejected <cr>`, `closed <id>` or `findings <ids>`.

**Stop:** the user rejects the CR or result: return it, reject it, file the
findings under the epic, or add them to the milestone. A required gate cannot
run: return it naming the unestablished claim. `land` refuses: report the
refusal, then refresh or wait.

**Exit:** the item is closed, landed or returned, or the milestone has new
members.
