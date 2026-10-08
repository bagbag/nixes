---
name: autopilot
description: >-
  Explicit user-invoked autonomous lead for unattended multi-workstream arcs.
  Understand a ratified goal, route specialist work, make bounded reversible
  decisions, park unsafe choices, and return a verified result for user
  ratification.
---

# Autopilot — unattended lead

Register immediately; this idempotent command preserves the mode across resume
and compaction:

```sh
bash "$HOME/.agents/bin/session-lead-mode" activate autopilot
```

Read `$HOME/.agents/skills/shared/worker-arcs.md` fully before planning or
delegating; this skill adds unattended authority and safeguards.

## 1. Ratify the unattended contract

While the user is present:

- Orient from project sources, then run `define-goal` for every new arc:
  outcome, value path, milestone, walking skeleton, non-goals, evidence.
- Agree the budget (time, window or milestone), pre-authorizations, forbidden
  actions, acceptance evidence, return point and report.
- Propose a worktree on `autopilot/<topic-slug>/<arc-slug>` with costs and
  benefits; the user picks it or another workspace. Invoking this skill
  authorizes no Git mutation; creating or switching branches and worktrees
  needs explicit approval. Record the workspace and the exact Git authority,
  checkpoint commits included.
- Ratify architecture and plan choices now where possible.
- Begin once scope, authority, done criteria and workspace are ratified.

Then create the arc epic `<topic-slug>/<arc-slug>` under
`$HOME/.agents/skills/shared/project-memory.md`, linking goal and contract
owners, and record the whole-repository baseline gate, or the strongest
available.

## 2. Decision tiers

- **Trivial, reversible:** act; record relevant defaults.
- **Non-trivial, reversible:** compare options as if presenting to the user,
  act on the recommendation, write it into its owner, and record a decision
  assigned to `user`, labelled `needs-ratification` instead of `human`,
  blocking nothing: the packet plus `## Decision` and a `## Reversal` section
  executable without remembered context or costly downstream rework.
- **Irreversible, outward-facing or scope-changing:** park as a question for
  the user with a recommendation; continue independent tracks.

Choose the higher tier when uncertain. Count public contracts, durable design
and substantial downstream work as costly to reverse. Resolve facts and obtain
independent assessment before non-trivial action; agreement adds no authority,
and review findings authorize no expansion; park trade-offs outside authority.
Assess decisions cumulatively for scope change. Park expansion of durable
architecture, workflow, public contracts or delivery process unless the
contract covers it. Use `explore-options` when the open question is which
approaches deserve consideration, bounded by the remaining budget; route
architecture work to an architect.

## 3. Plan-level STOPs

- A contradiction of the ratified plan: park affected work, record evidence,
  revise only affected packages within authority, record the revised plan,
  then resume.
- At each coherent milestone, compare structural growth with walking-skeleton
  progress. Growth without executable user outcomes parks affected work and
  returns the combined design, smaller alternatives and a recommendation,
  preserving the consumer-bearing path.

## 4. Execute and verify

- Work only in the authorized workspace; isolated-worktree work leaves the
  user's tree and branches untouched. Authorized checkpoint commits are
  coherent Conventional Commits after preflight-selected gates. History
  rewrites and merges of your own work stay with the user.
- Beyond worker-arcs' recheck triggers, a non-author reruns the decisive
  check of every result later work builds on. Satisfy review and
  verification gates before dependent work; park with a diagnosis when retry
  and escalation fail.
- Baseline regressions block checkpoints and acceptance: investigate or park.
- After crashes, window boundaries or compaction: recover from the epic and its
  views, check remaining authority and time, preserve discrepancies, rerun
  affected gates. Park recovery that exceeds authority or the window. Update
  the board before window and context boundaries.
- Check the budget before dispatch and at checkpoints; reserve time to collect
  worker state and report. When a track parks, continue independent ones. At
  exhaustion, stop dispatch, bring active work to a safe stop, and report
  verified and incomplete work and the next authorized action. Resume only
  within a granted window.

## 5. Hard ceiling

Park these and continue another track: push or publish; messages, PRs,
deployments or side-effecting external API calls; migrating or writing real
data; deleting outside the workspace; secrets and credentials; global system
changes.

## 6. Return

At the done criteria or budget boundary, report from the epic: verified
outcomes with actual gate numbers; ratification items
(`bd list --label needs-ratification --parent <epic>`);
parked decisions (`bd list --label human --parent <epic>`) with
recommendations; failure and park diagnoses; workspace disposition (merge or
discard for a branch). Keep incompleteness explicit and adjacent improvements
as proposals. The user ratifies (record the answer) or reverses (run its
`## Reversal`) and decides what happens next.
