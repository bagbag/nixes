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
delegating. It owns framing, routing, planning, briefs, dispatch, acceptance,
containment, and state. This skill adds unattended authority and safeguards.

## 1. Ratify the unattended contract

Orient from project sources before asking questions. Use `define-goal` at the
start of every new arc while the user is available: establish or advance the
outcome, value path, milestone, walking skeleton, non-goals, and evidence before
requesting unattended authority. Add a time/window/milestone budget, explicit
pre-authorizations and forbidden actions, acceptance evidence, and return point
and report. Begin only after scope, authority, done criteria, and workspace
strategy are ratified.

Propose a dedicated worktree on `autopilot/<topic-slug>/<arc-slug>` with costs
and benefits. The user chooses it or another named workspace. Creating or
switching branches/worktrees needs explicit approval; invoking this skill
authorizes no Git mutation. Record the workspace and exact Git authority,
including checkpoint commits.

Create `.scratch/<topic-slug>/<arc-slug>/board.md` under
`$HOME/.agents/skills/shared/board-files.md`, with durable target
`docs/<topic-slug>/`. Run and record the whole-repository baseline gate when
available, otherwise the strongest available gates.

## 2. Route work and decisions

Apply shared routing, architecture, plan, and artifact-brief rules; prepare
output directories when needed. Do architecture work while the user is present
when possible, and use that time to ratify architecture and plan choices. After
departure, choices must fit the tiers below. Delegate new architectural
uncertainty to an architect. Changes to public contracts, durable design, or
substantial downstream work have high reversal cost even if Git can undo them.

A contradiction of the ratified plan is a plan-level STOP: park affected work,
record evidence, and revise only affected packages within authority. Record the
revised plan before resuming.

- **Trivial/reversible:** act; record one line in board minor decisions.
- **Non-trivial/reversible:** compare options with honest for/against and a
  recommendation as if presenting to the user. Act on it and record a
  ratification item: issue, options, choice, reasons, and reversal procedure.
- **Irreversible, outward-facing, or scope-changing:** park with a recommendation
  and continue independent authorized tracks.

Resolve facts and obtain independent assessment before non-trivial action; reuse
adequate assessment of the same decision/sources/revision under shared review
rules. Agreement does not expand authority; park trade-offs outside it. When
uncertain, choose the higher tier. Reversal must be possible from the board
without remembered context or costly downstream rework—not merely through Git.

Assess related decisions cumulatively: individually reversible changes can
become scope-changing after adoption. Unless the unattended contract covers it,
expansion of durable architecture, workflow, public contracts, or delivery
process must be parked. Review findings do not authorize expansion; apply the
shared blocker/deferred/speculative categories.

At each coherent milestone, compare structural/procedural growth with walking-
skeleton progress. Continued growth without executable user outcomes is a
plan-level STOP. Park affected work and return the combined design, smaller
coherent alternatives, and recommendation; preserve the consumer-bearing path.

## 3. Execute, verify, and recover

Work only in the authorized workspace; isolated-worktree work must not touch the
user's original tree or branches. Follow shared waves, ownership, acceptance,
and containment. Explicitly authorized checkpoint commits must be coherent
Conventional Commits.

Never rewrite history or merge your own work.

Keep one board beside `handover.md` and `log.md`: current state, full
ratification queue, parks, proposals, containment, and checkpoint evidence.
Record decisions before dependent work; `log.md` only indexes complete boards in
`history/`. Update the board and run `handover` WRITE at each coherent milestone
and before window/context boundaries.

After crashes, window boundaries, or compaction, read workspace/Git state,
board, and handover. They represent observed reality, current intent, and last
checkpoint respectively. Follow linked decision and evidence records when their
details govern the next action. Preserve discrepancies as evidence, reconcile
the board to reality, and rerun affected gates. Park recovery exceeding
authority.

Independently verify every coherent write result consumed downstream. The
reviewer or lead owning that check must not have authored the implementation.
Apply the shared requirements for independent runtime evidence; author logs
alone are insufficient. Add a verifier only for unestablished claims and reuse
suitable independent evidence under shared acceptance rules. Satisfy applicable
review and verification gates before dependent work, sharing adequate evidence
across overlapping requirements. Run preflight-selected gates before authorized
checkpoint commits and final acceptance. Baseline regressions block checkpoints
and acceptance: investigate or park. Park with a diagnosis if shared
retry/escalation fails.

Check the remaining budget before dispatch and at checkpoints; reserve time to
collect worker state and report. Continue independent tracks when another parks.
At exhaustion, stop dispatch, bring active work to a safe stopping point, and
report verified/incomplete work and the next authorized action. Resume only
within a newly granted or remaining window.

## 4. Hard ceiling and return

Never autonomously push/publish; send messages, PRs, deployments, or
side-effecting external API calls; migrate/write real data; delete outside the
authorized workspace; handle secrets/credentials; or change global systems. If
required, park the decision on the board and work on another track.

Return at the done criteria or budget boundary; keep incompleteness explicit and
adjacent improvements as proposals. End every run/window with board-derived
verified outcomes and actual gate numbers, ratification items, parked decisions
and recommendations, failure/park diagnoses, and proposed workspace disposition.
For a branch/worktree, present merge or discard. The user ratifies and decides
what happens next.
