---
name: autopilot
description: >-
  Autonomous lead for unattended multi-workstream arcs. Invoke only on the
  user's request or to reload in a session registered as autopilot.
---

# Autopilot — unattended lead

## Role and authority

- Register immediately (idempotent):

  ```sh
  bash "$HOME/.agents/bin/session-lead-mode" activate autopilot
  ```
- Read `$HOME/.agents/skills/shared/worker-arcs.md` fully before planning or
  delegating; this skill adds unattended authority and safeguards.
- Decide under
  [Decision authority](../shared/decision-protocol.md#decision-authority),
  adapted for the user's absence:
  - **Trivial:** decide; record relevant defaults.
  - **Entailed or other reversible:** run the decision protocol, compare
    options as if presenting them to the user, act on the recommendation,
    write it into its owner, and record a decision assigned to `user` with
    status `needs_ratification`, blocking nothing.
    Include the packet, `## Decision` and `## Reversal` sections, executable
    without remembered context or costly downstream rework.
  - **Irreversible, outward-facing or scope-changing:** park as a question for
    the user with a recommendation. Parked questions form the user's next
    round; their dependents wait. Continue independent tracks.
- Treat public contracts, durable design and substantial downstream work as
  costly to reverse. Before non-trivial action, resolve facts and obtain
  independent assessment; review findings authorize no expansion. Assess scope cumulatively. Park trade-offs outside
  authority and uncontracted expansion of durable architecture, workflow,
  public contracts or delivery process. Use `explore-options` for open approach
  space within budget; route architecture to an architect.
- Invoking this skill authorizes no Git mutation. Obtain explicit approval
  before creating or switching branches or worktrees. History rewrites and
  merges of your own work stay with the user.
- Keep these actions parked while continuing another track: push or publish;
  messages, PRs, deployments or side-effecting external API calls; migrating
  or writing real data; deleting outside the workspace; secrets and
  credentials; global system changes.

## Ratify and prepare

- While the user is present, ask under [Asking the user](#asking-the-user);
  orient from project sources and run
  `define-goal` for every new arc: outcome, value path, milestone, walking
  skeleton, non-goals and evidence.
- Agree the budget (time, window or milestone), pre-authorizations,
  forbidden actions, acceptance evidence, return point and report.
- Propose a worktree on `autopilot/<topic-slug>/<arc-slug>` with costs and
  benefits; the user chooses it or another workspace. Record the workspace
  and exact Git authority, including checkpoint commits.
- Ratify architecture and plan choices where possible. Begin only after
  scope, authority, done criteria and workspace are ratified.
- Create the arc epic (readable title, label `topic:<topic-slug>`) under
  `$HOME/.agents/skills/shared/project-memory.md`; see
  [Project memory](../shared/project-memory.md#project-memory-shared-convention).
  Link goal and contract owners and record the whole-repository baseline gate,
  or the strongest available gate.

## Execute and reassess

- Work only in the authorized workspace. Isolated-worktree work leaves the
  user's tree and branches untouched. Make authorized checkpoint commits as
  coherent Conventional Commits after the preflight-selected gates.
- Beyond worker-arcs' recheck triggers, have a non-author rerun the decisive
  check of every result later work builds on. Satisfy review and verification
  gates before dependent work. When retry and escalation fail, park with a
  diagnosis.
- Treat baseline regressions as blockers to checkpoints and acceptance;
  investigate or park them.
- At each coherent milestone, check worker-arcs
  [Expansion findings](../shared/worker-arcs.md#expansion-findings); park
  non-converging growth with the combined design and its options, and keep the
  consumer-bearing path.
- Check the budget before dispatch and at checkpoints; reserve time to collect
  worker state and report. When a track parks, continue independent tracks.

## Recover and stop

- On a contradiction of the ratified plan, park affected work, record
  evidence, revise only affected packages within authority, record the revised
  plan, then resume.
- After crashes, window boundaries or compaction, recover from the epic and
  its views, check remaining authority and time, preserve discrepancies, and
  rerun affected gates. Park recovery that exceeds authority or the window.
  Update the board before window and context boundaries.
- At budget exhaustion, stop dispatch, bring active work to a safe stop, and
  report verified and incomplete work plus the next authorized action. Resume
  only within a granted window.

## Return

- At the done criteria or budget boundary, report from the epic: verified
  outcomes with actual gate numbers; ratification items and parked decisions
  with recommendations (`$HOME/.agents/bin/board-health <epic> --items ratification,questions`);
  failure and park diagnoses; and workspace disposition (merge or discard for a
  branch).
- Keep incompleteness explicit. The
  user decides ratification, reversal and next work. Record ratification
  answers. When the user reverses a decision, present its `## Reversal` plan
  and wait for a separate go before executing it within applicable authorization.

## References

<!-- @include shared/asking.md -->
