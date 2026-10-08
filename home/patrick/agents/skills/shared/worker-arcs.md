# Worker arcs

Shared contract of supervisor, autopilot and goal-agent for framing, planning,
review, dispatch and containment. Mode skills own authority, horizon,
recovery and ceilings; global instructions own safety, Git, role routing,
reconsideration and closure.

<!-- @include shared/decision-discipline.md -->

<!-- @include shared/work-tracking.md -->

## 1. Frame

Orient from the task's goal owners, the arc epic and current design
(`$HOME/.agents/skills/shared/project-memory.md`) before asking. Establish the
arc's contribution to the canonical milestone:

- topic and arc slugs;
- outcome, value path, material hypotheses;
- scope and exclusions, done criteria and evidence, constraints,
  compatibility, the user's quality criterion;
- product boundary and smallest executable walking skeleton when architecture
  or product flow changes;
- decisions, unknowns, empirical assumptions.

- `define-goal` owns framing when the milestone is unclear, purpose shifts,
  success is contested, or scope grows without value-path progress.
- Use an `architect` before planning when boundaries, public contracts, data
  flow, mechanisms or the clean end state are open, or planning would invent
  architecture; skip it when ratified design or a strong pattern decides the
  work. It returns options and questions, not authority. Plan only after
  load-bearing architecture is ratified or authorized under the active mode.
- Use `second-opinion` to challenge decisions and a fresh architect in REVIEW
  mode to assess architecture; keep authors and reviewers separate. The lead
  synthesizes, owns the arc, alone mediates user decisions and authorizes
  phases.

## 2. Plan

- Treat the package path as a guide: split, merge or reorder packages when
  that reaches the end state more cleanly or unblocks independent work.
- Packages are issues (work-tracking): coherent units for one worker,
  reviewable as a whole, created per wave with `bd create --graph`.
- Write a separate plan only for what issues cannot hold: cross-package
  reasoning, integration checkpoints by blast radius, cheap assumption tests.
  Use a `plan` worker for material decomposition or integration uncertainty.
- Distinguish the approved checkpoint from later product acceptance
  (`define-goal` milestone challenge); name its executable result and
  evidence, and label infrastructure-only evidence as such. Dispatch a packet
  when it advances that checkpoint, removes a demonstrated blocker, or serves
  an authorized parallel track, within existing authority and by current
  priority. A repair names the work it unblocks; return there when it closes.
  Among equally ready packages, prefer a pattern later packages need, then the
  smaller package.
- Prefer vertical packages through a consumer path. Foundation-only work names
  its concrete dependency, its earliest runnable consumer checkpoint and why
  validation cannot happen there sooner.
- Each substantial addition names its current or committed consumer and the
  required behavior, realistic failure or contract instability it answers. A
  current consumer may justify implementation now; include current milestone
  capabilities even when additive. Later consumers justify an additive path:
  defer with activation conditions unless deferral replaces a required
  semantic identity or boundary, or leaves plausible integrity failures.
  Implement together changes that would otherwise immediately reshape the same
  public contract; defer orthogonal capabilities. Cleaner contracts,
  integrity, proven variation or credible extensibility justify structure;
  ceremony and speculative scope need explicit decisions.
- Before freezing a public API, sketch declarations, registration and runtime
  calls against the strongest analogous API; challenge brittle literals,
  duplicate names and unnecessary wrappers. Freeze when representative
  consumer usage is coherent.
- For shared behavior changes, trace input, mapping and execution before
  dividing ownership.
- One owner per file, shared contract, invariant and cross-document concept;
  merge, extract or sequence overlapping zones. Link packages that rely on a
  consequential invariant to its owner, decisive checks and consumers; the
  owner keeps the statement, verification status and evidence gaps; reassess
  consumers when premises change.
- Group shared invariants, mapping paths and file ownership into one package
  where practical; keep one owner across internal steps and tests and review
  at a capability or consumer boundary. Split for parallelism, ownership, risk
  containment or real dependencies.
- Probe novel load-bearing assumptions before dependent work; develop
  representative tests of shared behavior alongside implementation; plan
  golden examples and hand-verified fixtures in domain-heavy arcs.
- Plans with material decomposition or integration uncertainty get an
  independent assessment (coverage, grounding, dependencies, integration,
  verification, silent failures) before dispatch; an adequate architecture
  assessment can cover it. A pattern-determined plan gets the lead's
  self-check. Resolve blockers before dependent work.

## 3. Review and acceptance

One acceptance gate per coherent target, sized to its stakes; modes may
tighten this.

| Claim | Gate |
|---|---|
| Settled by a cheap check | lead's inline check |
| Checkable beyond that; repair closure | `verify` |
| Consequential contract, design, plan, cross-cutting change | `review`; it reproduces decisive checks; add `verify` only for claims it leaves open |

- **Coverage:** a planned later review of the same target (the user's staged
  review, an integration review) replaces earlier gates it makes redundant.
  Reuse assessment of the same decision, sources and revision; add reviewers
  only for a named open question or a user request.
- **Independence** is relative to authorship, the lead's own results
  included; a role name or a passing self-check is not independent.
- **Round:** a fresh assessor judges, the author repairs, the same assessor
  checks repairs and affected invariants. Assessors apply fixes that are the
  only realistic clean option in the reviewed files while the author is
  inactive there; the lead inspects each diff. A changed premise or blast
  radius reopens broader review; repair completion does not.
- **Verdict:** assessors work from current rulings and supersessions (old
  briefs and verdicts yield) and comment on the package: verdict, confirmed
  defects, open questions, checks run, next action.
- **Accept** (work-tracking) when findings close and agreed gates pass; a
  failing or unrun required gate keeps the package open.
- **Sequence:** implementation with tests → review → focused repair closure →
  lead integration check; extra planning or opinions answer distinct
  questions.
- **Expansion findings:** current blocker (violates committed behavior, an
  enduring contract or supported-workload integrity) · deferred committed
  requirement (additive later; defer with activation condition) · speculative
  (no committed consumer; labelled observation). When reviews only add
  structure, test a smaller coherent option against the earliest runnable
  checkpoint; return non-converging growth to the lead with alternatives and
  evidence.

## 4. Brief and dispatch

- A brief adds to the package issue: authoritative sources and skills, the
  owner sections of rulings it relies on, the arc rules that apply (quoted),
  no-touch zones, material assumptions, STOP conditions, checks to run,
  permission to write tests and permission to run them (a hold on running does
  not forbid writing), and the arc epic with an instruction to flag board/spec
  contradictions. A substantial brief goes in a linked file.
- Workers get their issue id and `--actor <worker>`; they claim, heartbeat,
  comment evidence and hand over only that issue. Read-only roles run
  `bd --readonly`; the lead claims and hands over their issues under its own
  actor, naming the role and its result.
- Artifacts go under the arc's `.scratch/` unless the brief names another
  owner. References grant reading, not writing. The lead prepares directories
  when worker permissions require it.
- Spec as source, brief as delta: reference rulings by owner; overrides name
  their decision record; return unmarked conflicts before dependent work. Relay
  project-specific rules, not generic role discipline; add anti-regression
  STOPs where old sources encode reversed decisions. Treat legacy FINAL labels
  as recorded decisions under reconsideration. Workers report material
  challenges; the lead resolves them.
- Dispatch dependency-ready waves with disjoint ownership after
  `bd swarm validate <epic>` passes; sequence shared contracts. Default to one
  shared tree; use separate worktrees for inseparable zones with justified
  merge cost. Use native liveness, wait and resume.
- The lead owns destructive actions: workers inventory and adapt; the lead
  verifies exact targets, obtains confirmation and executes deletion, reset or
  discard, relaying that authority only where orchestration preserves it as
  trusted. The lead owns the Git index, history and tracked moves; workers
  supply rename maps and edit content after an approved `git mv`. Inspect tree
  and index after waves; treat unexplained out-of-zone changes as possibly the
  user's, attribute them before acting, and leave them in place.
- Verify integration through intended interfaces: at each integration
  checkpoint, exercise the combined consumer path and its cross-boundary
  invariants. Out-of-contract work and cleaner out-of-scope repairs stay
  proposals until the mode authorizes them. Before large fan-out, at milestones
  and after containment, assess the combined end state: missing general
  mechanisms, asymmetric cases, duplicate owners, silent failures, dead weight,
  doc drift. Stop rethinking when unknowns are empirical or further yield is
  cosmetic.

## 5. Contain

- Inspect each result: actual gate output, baseline versus regression,
  disclosed judgment calls (triaged under the mode's decision rules).
- Accept author gate results from their recorded command and output. A
  non-author reruns the decisive check when output is missing or contradicts
  the diff, the claim is surprising or disputed, or the change touches
  security, data integrity or persistence. Let gates fail; fix causes, not
  results.
- Authors run implementation gates; the lead runs cross-package integration
  checks. Comment each gate result (command, outcome) on its issue; rerun
  decisive checks after relevant changes.
- Gates by blast radius: targeted after isolated waves, whole-repository after
  cross-cutting changes, at agreed milestones and final acceptance; modes may
  tighten this. With a red baseline, target touched surfaces the broken gate
  would cover.
- Count repair attempts per underlying problem across workers and review
  rounds; a new failing example or reassignment does not reset the count.
- At the global retry limit, stop affected repairs and dependent dispatch.
  More edits, passing local tests or closed examples while the same mechanism
  keeps failing are not progress. Record what was tried, what remains broken
  and the root-cause hypothesis; the one escalation needs an evidence-backed
  change of approach and a decisive check. Continue independent work. Round
  limits never authorize known defects.
- Accepted work that proves wrong: stop its consumers, map impact, reopen it
  with a warm worker, re-verify dependents, record error and containment.
- Claims needing legal, regulatory, medical, scientific or other expert
  validation: an issue labelled `expert-claim` (claim, owner, status,
  evidence, affected behavior); keep behavior fail-closed only where it
  depends on an unresolved load-bearing claim; the mode decides asking,
  ratifying or parking.
