# Worker arcs

Supervisor and autopilot share this contract for framing, routing, planning,
dispatch, integration, verification, and state. Mode skills own authority,
isolation, checkpoints, recovery, and safety ceilings; global instructions own
universal safety, Git, review, role routing, documentation, and closure. Read
this file fully before the first delegation; keep mode rules and briefs focused
on their distinct requirements.

<!-- @include shared/decision-discipline.md -->

## 1. Frame and route

Identify the current task from user direction, then orient from its applicable
project/topic goal owners and current handover/board/design before questions.
Follow `$HOME/.agents/skills/shared/project-memory.md` for ownership.
Before decomposition, establish
the arc's contribution to the canonical milestone, covering:

- the user-assigned topic, stable topic slug, and arc slug;
- outcome, purpose, defining value path, and any material hypothesis;
- scope and exclusions, done criteria and evidence, constraints, compatibility,
  and the user's quality criterion;
- the committed product boundary and smallest executable walking skeleton when
  the arc affects architecture or product flow;
- decisions, unknowns, and empirical assumptions.

The active mode routes unresolved choices to decision or parking.

Use `define-goal` as the owner of goal framing when the contract or next
milestone is unclear, purpose shifts, success is contested, or scope grows
without value-path progress.

Resolve factual uncertainty through global routing before asking the user to
decide. Use an `architect` before implementation planning when module
boundaries, public contracts, data flow, mechanisms, or the clean end-state
remain open, existing architecture needs assessment, or planning would invent
architecture. Skip it when ratified design or a strong pattern determines the
work. Give the frame and expected result; the architect returns grounded options
and unresolved questions, not authority to expand scope or implement. An
insufficient frame calls for focused questions rather than guesses. Plan only
after load-bearing architecture is ratified or authorized under the active mode.

Use `second-opinion` for independent decision challenge or a fresh architect in
REVIEW mode for architecture assessment. Use both for distinct questions, keep
authors separate from reviewers, and select depth through the relevant skill.
The lead commissions follow-ups, synthesizes results, owns the whole arc, and
alone mediates user decisions and authorizes phases.

## 2. Plan and review

For a multi-worker implementation arc, keep one written execution plan. The lead
may write it or continuation deltas when approved architecture and established
patterns determine ownership, dependencies, and checks; use a `plan` worker for
material decomposition/integration uncertainty. Include the goal and design
sources, coherent packages practical for one worker and reviewable as a whole,
exclusive created/modified file zones, dependency waves, per-package checks and
permitted effects, cheap tests of assumptions, integration checkpoints by blast
radius, and decisions.

Every plan distinguishes the current approved checkpoint from later product
acceptance, using the `define-goal` milestone challenge. Name its executable
result and evidence; label infrastructure-only evidence accurately.
Before dispatch, identify why this packet belongs now: it advances that
checkpoint, removes a demonstrated blocker, or serves an explicitly authorized
parallel track. Keep the packet within existing execution authority and allocate
workers by current priority. For a repair, name the work it unblocks and return
there when the repair closes. Apply this check within existing planning.

Prefer vertical packages that exercise a consumer path across required
boundaries. Foundation-only work needs a concrete dependency, the earliest
runnable consumer checkpoint, and an explanation why validation cannot happen
there sooner. Independent designability alone does not justify successive
foundation waves.

Each substantial addition names its current/committed consumer and required
behavior, realistic failure, or current contract instability. A current consumer
may justify current implementation. Include current milestone capabilities even
when additive. Later consumers normally justify an additive path, not
implementation now; defer with activation conditions unless deferral replaces a
required semantic identity/boundary or leaves plausible supported-workload
integrity failures. Compare unreleased abstractions to the clean end-state:
implement together changes that otherwise immediately reshape the same public
contract; defer orthogonal capabilities. Cleaner contracts, integrity, proven
variation, or credible extensibility can justify structure; ceremony and
speculative scope require explicit decisions.

Before freezing public APIs, sketch declarations, registration, and runtime
calls; inspect the strongest analogous repository API. Challenge brittle
literals, duplicate names, and unnecessary wrappers. Freeze a public API only
when representative consumer usage is coherent; internal correctness alone is
insufficient.

For changes to shared behavior, trace input, mapping, and execution before
dividing ownership. Use that understanding to identify affected paths and
invariants; this investigation needs no separate report.

Assign each file, shared contract, invariant, and cross-document concept one
owner. For consequential invariants and assumptions, link affected packages to
the contract/decision owner, decisive checks and consumers. Keep statements,
assumption verification status and evidence gaps with that owner; reassess
consumers when premises change.
Merge, extract, or sequence overlapping zones. Group shared invariants,
mapping paths, and file ownership into one package where practical; keep one
owner across internal steps/tests and review at a capability/consumer boundary.
Split for useful parallelism, ownership, risk containment, or real dependencies.
Probe novel load-bearing assumptions before dependent work; develop
representative tests of shared behavior alongside implementation and
integration. Plan early golden examples and hand-verified fixtures in
domain-heavy arcs.

Independently assess plans with material decomposition or integration
uncertainty for coverage, grounding, dependencies, integration, verification,
and silent failures before dispatch; an adequate architecture assessment can
cover them. The lead may check its own pattern-determined dispatch plan; this is
a local self-check, not independent review. Incorporate findings and resolve
blockers before dependent work.

### Review ownership and closure

Assign one independent reviewer per coherent target. Independence is relative to
authorship: a substantive implementation result needs a reviewer who did not
author it, including when the lead wrote the implementation. A role name or
passing self-check does not make an assessment independent. Reuse assessment
covering the same decision, sources, and current revision across skill
requirements; combine architecture/plan review where useful. Additional
reviewers or critics need a named unanswered question or explicit user request.
A critic supplies reasoning pressure on difficult premises or trade-offs beyond
source grounding.

A fresh reviewer makes the initial judgment; the author repairs findings and the
same reviewer checks repairs and affected invariants. Accept when findings close
and agreed gates pass. Evidence of a materially changed premise/blast radius
reopens broader review; repair completion alone does not. Additional fresh
opinions need a distinct purpose or user request. Reviewers reassess the frame
independently; the active mode handles unresolved choices/non-convergence.

Default sequence: coherent implementation/tests → independent review → focused
repair closure → lead integration verification. Extra planning/opinions answer
distinct questions rather than adding automatic stages.

Review cumulative scope as well as coverage. Classify expansion recommendations:

- **Current blocker:** violates committed behavior, an enduring current
  contract, or realistic supported-workload integrity.
- **Deferred committed requirement:** needed later and additive without replacing
  current architecture; record activation, keep outside the current package graph.
- **Speculative concern:** no committed consumer or plausible supported-workload
  failure; retain as a labeled observation pending evidence.

When reviews only add structure, test a smaller coherent option against the
earliest runnable checkpoint. Return non-converging growth to the lead with
alternatives and evidence.

## 3. Brief and dispatch

Each brief follows global role routing and names: one task/result, authoritative
sources/skills, exclusive write and no-touch zones, ratified decisions/rationale
and material assumptions, STOP conditions, verification commands/effects, and
the living board with an instruction to flag board/spec contradictions.

Assign substantive artifacts concrete output paths and content/format, usually
under the active `.scratch/` arc; identify existing files to update. Workers
write assigned artifacts directly with required permissions and return paths
plus a concise summary. The lead prepares directories when worker permissions
cannot. References grant reading, not writing. Short factual answers can remain
in responses; scout/explore are response-only, read-only roles.

Use spec-as-source and brief-as-delta: reference decisions instead of repeating
them. Overrides name the authorizing section/decision; return unmarked conflicts
before dependent work. Treat legacy FINAL labels as recorded decisions,
reconciled with current sources and global reconsideration. Execute work within
the current task and granted authority. Workers report material challenges; the lead
resolves them. Relay project-specific rules, not generic role discipline; add
anti-regression STOPs where old sources may encode reversed decisions.

Dispatch dependency-ready waves with disjoint file/concept ownership; sequence
shared contracts. Among equally ready packages, the lead may prioritize a
pattern needed by later packages. Use native liveness/wait/resume; resume
related work with its warm worker, stating existing work, remaining work, and
changes. New tasks get fresh workers.

The lead owns destructive actions requiring user authority: workers may
inventory and adapt, but the lead verifies exact targets, obtains confirmation,
and executes deletion/reset/discard. Relay that authority only if orchestration
preserves it as trusted authority. The lead also owns Git index/history and
tracked moves; workers supply rename maps and edit content after approved
`git mv`. Inspect tree/index/package boundaries after waves. Treat unexplained
out-of-zone changes as potentially belonging to the user. Attribute them before
acting and never revert them.

The lead verifies integration through intended interfaces. Out-of-contract work
remains a proposal until the mode authorizes expansion. Before large fan-out, at
milestones, and after reversal/containment, assess the combined end-state:
missing general mechanisms, asymmetric cases, duplicate owners, silent failures,
dead weight, and doc drift. Cleaner out-of-scope repairs remain proposals. Stop
rethinking when unknowns are empirical or further yield is cosmetic.

## 4. Accept and contain

Inspect every result: actual gate output, baseline versus regression, and
disclosed judgment calls. Triage those calls under the active mode's decision
rules rather than silently accepting them.

Load-bearing runtime claims require independent reproduction of decisive checks
by a reviewer, verifier, or lead who did not author the implementation, unless
suitable independent evidence already covers the same relevant code and
environment. Author test output alone does not satisfy this requirement. That
independent execution can satisfy the gate for everyone; a second verifier or
lead rerun is not automatic. Attribute reused evidence and rerun when changes
invalidate it or a new failure warrants investigation. For lower-risk claims,
inspect output and spot-check the decisive claim. Use a separate verifier for
claims not yet established. Let gates fail; never change implementation or
evidence merely to force green.

Report only source-confirmed defects with violated requirement/invariant and
impact; separate risks, intent questions, and structural preferences. Authors
run implementation gates; the lead runs cross-package integration checks.
Record what checks prove and what invalidates them in existing briefs/reports.
Beside results, identify claim-relevant environment dependencies outside the Git
fingerprint: toolchain/service versions, database/fixture state or non-secret
ignored-config identities. Mark unknowns; recheck claims when dependencies change.
Keep supporting evidence and logs in the arc's existing artifacts.

Choose gates by blast radius: targeted after isolated waves, whole-repository
after cross-cutting changes, at agreed milestones, and final acceptance when
available. Modes may tighten this. For red baselines, target touched surfaces
that the broken gate would cover.

Apply global retry/escalation to the underlying problem across workers and
review rounds; a new failing example or reassignment does not reset the count.
After two repair attempts without material progress toward the original
acceptance condition, stop affected repairs and dependent dispatch. More edits,
passing local tests, or closing examples while the same mechanism keeps failing
do not establish progress. Record what was tried, what remains broken, and
whether evidence supports a different root-cause hypothesis or approach.

Reassess the premise, seek an independent challenge when available, and allow
one escalation only with an evidence-backed change of approach and a decisive
check. If that fails, park the problem and bring the blocker, options, and
recommendation to the user before another repair attempt. Continue independent
authorized work. Round limits never authorize known defects. If accepted work
proves wrong, stop its consumers, map impact, reopen its owner with a warm worker
where viable, re-verify dependents, and record the error and containment.

## 5. Record evidence and state

Maintain the board under `project-memory.md`. For consequential claims needing
legal/regulatory/medical/scientific or other expert validation, record claim,
owner, status, evidence, and affected behavior. Keep
behavior fail-closed only where it depends on an unresolved load-bearing claim;
the mode decides asking, ratifying, or parking.

Promote enduring conclusions under `project-memory.md`; keep working
coordination/evidence in `.scratch/<topic-slug>/<arc-slug>/`.
