# Unattended protocol

Autopilot: solo while the user is away. Adds unattended authority and
safeguards to the decide and plan protocols.

## Entry

`/role autopilot` registered solo for setup (step 1); the decide, plan and
unattended protocols are loaded. Read
`$HOME/.agents/skills/role/protocols/review.md` too. After a compaction during
setup, run `/role autopilot` again.

## Authority

- Decide under
  [Decision authority](../../shared/decision-protocol.md#decision-authority),
  adapted for the user's absence. Run every ruling that would become
  `needs_ratification` through a decide round, grouped by shared premise; skip
  it for a trivial default. In its Ask, report `act` or `park` by these classes.
  - **Trivial:** decide; record relevant defaults.
  - **Entailed or other reversible:** `act`, a lean recommendation included.
    Compare options as if presenting them to the user and write the
    recommendation into its owner. Make its reversal executable without
    remembered context or costly downstream rework. For a revision, run
    `board supersede` when recording it; its reversal runs
    `board bd reopen <old>` and `board bd dep remove <old> <new>`.
  - **Irreversible, outward-facing or scope-changing:** `park` as an unassigned
    question for the user with a recommendation (`board unclaim <id>` when you
    hold it outside a round). Parked questions form the user's next round;
    their dependents wait. Continue independent tracks.
- Accept in the user's place `in_review` design items and finished epics
  whose acceptance names the user: the decide protocol's Accept with the
  walkthrough as a written assessment, recorded as a `needs_ratification`
  decision with its `## Reversal`.
- Treat public contracts, durable design and substantial downstream work as
  costly to reverse. Before non-trivial action, resolve facts and obtain
  independent assessment; review findings authorize no expansion. Assess scope
  cumulatively. Park trade-offs outside authority and uncontracted expansion of durable architecture, workflow,
  public contracts or delivery process. Use `explore-options` for open approach
  space within budget; route architecture to an architect.
- Entering the autopilot role authorizes no Git mutation. Obtain explicit
  approval before creating or switching branches or worktrees. History rewrites and
  merges of your own work stay with the user.
- Keep these actions parked while continuing another track: push or publish;
  messages, PRs, deployments or side-effecting external API calls; migrating
  or writing real data; deleting outside the workspace; secrets and
  credentials; global system changes.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops.

1. **Ratify and prepare** as solo, while the user is present:
   - Ask under
     [Asking the user](../../shared/asking.md#asking-the-user); orient from
     project sources and run `define-goal` for every new arc: outcome, value
     path, milestone, walking skeleton, non-goals and evidence.
   - Agree the budget (time, window or milestone), pre-authorizations,
     forbidden actions, acceptance evidence, return point and report.
   - Propose a worktree on `autopilot/<topic-slug>/<arc-slug>` with costs and
     benefits; the user chooses it or another workspace. Record the workspace
     and exact Git authority, including checkpoint commits.
   - Ratify architecture and plan choices where possible. Begin only after
     scope, authority, done criteria and workspace are ratified.
   - Frame the outcome epic under the plan protocol's
     [Frame](plan.md#frame). Link goal and contract owners and record the
     whole-repository baseline gate, or the strongest available gate, in the
     checkpoint file.
   - Ask last whether to start now, first naming a round or release still open
     (`protocol status --line`) for the user to answer or abandon. On the user's
     go run `bash $HOME/.agents/bin/session-lead-mode activate autopilot`. When
     the user returns and leaves again, confirm only the budget and the go.
   Output: ratified budget, authority, workspace and baseline, one line each;
   `registered autopilot`.
2. **Execute and reassess:**
   - Work only in the authorized workspace. Isolated-worktree work leaves the
     user's tree and branches untouched. Make authorized checkpoint commits as
     coherent commits in the convention of the global Git rule, once the
     baseline gate shows no regression and the result's review and
     verification gates pass.
   - Beyond the recheck triggers in
     [Evidence and gates](../../shared/acceptance.md#evidence-and-gates), have a non-author
     rerun the decisive check of every result later work builds on. Satisfy
     review and verification gates before dependent work. When retry and
     escalation fail, park with a diagnosis.
   - Treat baseline regressions as blockers to checkpoints and acceptance;
     investigate or park them.
   - At each coherent milestone, check
     [Expansion findings](review.md#expansion-findings); park non-converging
     growth with the combined design and its options, and keep the
     consumer-bearing path.
   - Check the budget before dispatch and at checkpoints; reserve time to
     collect worker state and report. When a track parks, continue independent
     tracks.
   Output: per checkpoint: gates, commits, parked items, remaining budget.
3. **Recover** after crashes, window boundaries or compaction under
   project-memory
   [Recovery](../../shared/project-memory.md#recovery);
   check remaining authority and time, preserve discrepancies, and rerun
   affected gates. Park recovery that exceeds authority or the window. Update
   the board before window and context boundaries.
   Output: recovered position and remaining authority.
4. **Return** at the done criteria or budget boundary, when the user says they
   are back, or when the user asks for a round: report verified
   outcomes with actual gate numbers; ratification items and parked decisions
   with recommendations
   (`board health --root <epic> --items ratification,questions`);
   failure and park diagnoses; and workspace
   disposition (merge or discard for a branch). Keep incompleteness explicit.
   Then run `bash $HOME/.agents/bin/session-lead-mode activate solo`. Stay on
   autopilot through a passing message that does not end the run.
   Output: the return report; `registered solo`.

## Stop

- On a contradiction of the ratified plan, park affected work, record
  evidence, revise only affected items within authority, record the revised
  plan, then resume.
- At budget exhaustion, stop dispatch, bring active work to a safe stop, and
  report verified and incomplete work plus the next authorized action. Resume
  only within a granted window.

## Exit

The user decides ratification, reversal and next work. Record ratification
answers. When the user reverses a decision, present its `## Reversal` plan and
wait for a separate go before executing it within applicable authorization.
