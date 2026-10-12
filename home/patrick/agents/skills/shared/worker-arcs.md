# Worker arcs

Apply this execution contract in supervisor, autopilot and goal-agent. Mode
skills own authority, horizon, recovery and ceilings; global instructions own
safety, Git, role routing, reconsideration and closure. Apply the
[Decision protocol](#decision-protocol) and [Work tracking](#work-tracking-beads)
references below.

## Frame

Orient from goal owners, root epic and current design before asking. Follow
`$HOME/.agents/skills/shared/project-memory.md`; establish the arc's milestone
contribution:

| Field | Content |
|---|---|
| Identity | Topic and arc slugs. |
| Outcome | Value path and material hypotheses. |
| Contract | Scope, exclusions, done criteria/evidence, constraints, compatibility, user quality criterion. |
| Product path | Product boundary and smallest executable walking skeleton when architecture or flow changes. |
| Open premises | Decisions, unknowns, empirical assumptions. |

- Use `define-goal` when the milestone is unclear, purpose shifts, success is
  contested or scope grows without value-path progress.
- Commission an `architect` before planning when boundaries, public contracts,
  data flow, mechanisms or the clean end state are open, or planning would
  invent architecture. Use ratified design or a strong pattern when it settles
  the work. Plan only after load-bearing architecture is ratified or authorized
  by the active mode. Architect results grant no authority.
- Use `explore-options` for a broader choice set or when options share a
  consequential untested assumption.
- Use `second-opinion` for decision challenges and a fresh architect in REVIEW
  for architecture assessment. Keep authors and reviewers separate. The lead
  owns synthesis and the arc, alone mediates user decisions and authorizes phases.

## Plan

- Split, merge or reorder packages for a cleaner end state or independent work.
  Create coherent, whole-reviewable one-worker issues per wave with
  `bd create --graph`; apply [Package criteria](#package-criteria).
- Use a separate plan for cross-package reasoning, blast-radius integration
  checkpoints and cheap assumption tests that issues cannot hold. Assign `plan`
  for material decomposition or integration uncertainty.
- Distinguish approved checkpoints from later product acceptance using
  `define-goal`'s Challenge acceptance. Name executable results and evidence;
  label infrastructure-only evidence as such.
- Trace shared behavior's input, mapping and execution before dividing ownership.
- Assign one owner per file, shared contract, invariant and cross-document
  concept. Merge, extract or sequence overlaps. Link dependent packages to the
  invariant owner, decisive checks and consumers; owner keeps its statement,
  verification status and evidence gaps. Reassess consumers on changed premises.
- Group shared invariants, mapping paths and file ownership where practical;
  retain one owner across internal steps/tests and review at capability or
  consumer boundaries. Split for parallelism, ownership, risk containment or
  real dependencies.
- Probe novel load-bearing assumptions before dependent work. Develop shared
  behavior tests alongside implementation; plan golden examples and hand-verified
  fixtures for domain-heavy arcs.
- For material decomposition/integration uncertainty, obtain independent plan
  assessment before dispatch: coverage, grounding, dependencies, integration,
  verification, silent failures. Reuse adequate architecture assessment.
  Self-check pattern-determined plans; resolve blockers before dependent work.
  Select gates under [Review policy](#review-policy).

## Brief

- Add authoritative sources/skills, relied-on ruling owner sections, quoted arc
  rules, no-touch zones, assumptions, STOP conditions and checks to the package.
  Grant writing and running tests separately; a running hold does not forbid
  writing. Give root epic and require board/spec contradiction reports. Link a
  file for substantial briefs.
- Reference specs and ruling owners; keep briefs as deltas. Identify override
  decision records; return unmarked conflicts before dependent work.
- Relay project-specific rules, excluding generic role discipline. Add
  anti-regression STOPs for reversed decisions still encoded in old sources.
  Treat legacy FINAL labels as recorded decisions under reconsideration;
  workers report material challenges for lead resolution.
- Assign artifact paths under the arc's `.scratch/` unless another owner is named.
  References grant reading, not writing. Lead prepares directories when worker
  permissions require it.

## Dispatch

- Dispatch packages advancing the approved checkpoint, removing demonstrated
  blockers or serving authorized parallel tracks, within authority and current
  priority. Repairs name the work they unblock; return there at closure. Among
  equally ready packages, prefer needed patterns, then smaller packages.
- Run `bd dep cycles`; dispatch dependency-ready waves with disjoint ownership
  once no cycles remain. Sequence shared contracts. Default to one shared tree;
  use separate worktrees for inseparable zones with justified merge cost. Use
  native liveness, wait and resume. Before large fan-out, run [Reassess](#reassess).
- Give workers issue ids and `--actor <worker>`; they claim, heartbeat, comment
  evidence and hand over only that issue. Read-only roles use `bd --readonly`;
  lead claims/hands over their issues under its actor, naming role and result.
- Lead owns destructive actions: workers inventory/adapt; lead verifies exact
  targets, obtains confirmation and executes deletion, reset or discard. Relay
  authority only when orchestration preserves it as trusted.
- Workers supply rename maps and edit after the move; the lead runs `git mv`
  within its mode's Git authority. Inspect tree/index after waves; attribute
  unexplained out-of-zone changes (possibly the user's) before acting and leave
  them in place.

## Review and accept

- Inspect each result's actual gate output, baseline/regression classification
  and disclosed judgment calls; triage calls under mode authority. Apply
  [Evidence and gates](#evidence-and-gates) and [Review policy](#review-policy).
- Run implementation gates as author; use a fresh assessor for required
  independent judgment. Author repairs; same assessor checks repairs and
  affected invariants. Repair completion reopens no broader review.
- Forbid assessor fixes in the brief while the author is active in the reviewed
  files. Assessors apply small, contained fixes that are the only realistic
  clean option and return larger fixes to the author; inspect each diff.
- Assess current rulings and supersessions; old briefs/verdicts yield. Comment
  verdict, confirmed defects, open questions, executed checks and next action
  on the package.
- Accept under work-tracking's [Acceptance](#acceptance) once findings close and
  agreed gates pass. A failed or unrun required gate keeps the package open.
- Classify scope expansion under [Expansion findings](#expansion-findings).

## Integrate

- Follow implementation with tests → review → focused repair closure → lead
  integration check. Add planning/opinions only for distinct questions.
- Lead runs cross-package checks through intended interfaces. At each integration
  checkpoint, execute the combined consumer path and cross-boundary invariants.
  Apply [Evidence and gates](#evidence-and-gates).
- Out-of-contract work and cleaner out-of-scope repairs stay proposals until
  mode authority covers them.

## Reassess

Before large fan-out, at milestones and after containment, assess the combined
end state: missing general mechanisms, asymmetric cases, duplicate owners,
silent failures, dead weight and doc drift. End rethinking when remaining
unknowns are empirical or further yield is cosmetic.

## Contain

- Count repair attempts per underlying problem across workers and review rounds;
  new failing examples or reassignment do not reset the count.
- At the global retry limit, stop affected repairs and dependent dispatch. Record
  attempts, remaining failure and root-cause hypothesis. Require an evidence-backed
  changed approach and decisive check for the one escalation; continue independent
  work. More edits, passing local tests or closed examples while the same mechanism
  fails are not progress. Round limits never authorize known defects.
- For a reversed decision or accepted work that proves wrong, record the
  ruling, stop consumers, map affected code and docs, reopen owners with warm
  workers, re-verify dependents and record error/containment.
- For claims needing legal, regulatory, medical, scientific or other expert
  validation, create `expert-claim` issues: claim, owner, status, evidence,
  affected behavior. Fail closed only where behavior depends on an unresolved
  load-bearing claim; mode authority determines asking, ratifying or parking.

## Report

- At meaningful updates, report **Accepted** (new results and decisive
  evidence), **Moving** (active work and owners; authoring, review, repair and
  gates separately), **Bottleneck** (constraint and action) and **Next result**
  (next executable outcome and needed decision).
- Report failed and unrun gates; test counts support evidence, not progress.

## Package criteria

- Prefer vertical consumer paths. Foundation-only work names its concrete
  dependency, earliest runnable consumer checkpoint and why validation cannot
  happen there sooner.
- Justify and defer additions under [End-state criteria](#end-state-criteria);
  include additive current-milestone capabilities. Implement together changes
  that would immediately reshape the same public contract; defer orthogonal
  capabilities. Return ceremony and speculative scope for explicit decisions.
- Before freezing a public API, sketch declarations, registration and runtime
  calls against the strongest analogous API. Challenge brittle literals,
  duplicate names and unnecessary wrappers; freeze on coherent representative
  consumer use.

## Review policy

Use one acceptance gate per coherent target, sized to stakes; modes may tighten it.

| Claim | Gate |
|---|---|
| Settled by a cheap check | Lead's inline check. |
| Checkable beyond that; repair closure | `verify`. |
| Consequential contract, design, plan, cross-cutting change | `review`, reproducing decisive checks; add `verify` only for remaining open claims. |

- Reuse planned later review of the same target (staged or integration review)
  where it replaces redundant earlier gates.
- Select and brief reviewers under [Reviewers](#reviewers).

## Evidence and gates

- Accept author gate results with recorded command/output. Require non-author
  reproduction of the decisive check for missing/contradictory output,
  surprising/disputed claims or security, data-integrity or persistence changes.
  Let gates fail; fix causes, not results.
- Comment each gate's command/outcome on its issue; rerun decisive checks after
  relevant changes. Authors run implementation gates; lead runs integration.
- Run targeted gates after isolated waves; whole-repository gates after
  cross-cutting changes, at agreed milestones and final acceptance. Modes may
  tighten this. With a red baseline, target touched surfaces the broken gate
  would cover.

## Expansion findings

Classify each under [Concern classes](#concern-classes). When reviews keep
adding structure without runnable progress, pause affected fan-out, re-derive
the premise with an architect, test a smaller coherent option against the
earliest runnable checkpoint and bring the options to the decider.

<!-- @include shared/decision-protocol.md -->

<!-- @include shared/reviewers.md -->

<!-- @include shared/work-tracking.md -->
