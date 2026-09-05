# Worker arcs (shared convention)

Supervisor and autopilot are alternative user-facing leads. Both use this
contract to frame goals, route specialist work, plan, dispatch, integrate, and
verify multi-worker arcs. Their skills define decision authority, isolation,
checkpoints, context handling, and mode-specific safety ceilings.

The global agent instructions remain active and own universal safety, git,
review, role-routing, documentation, and closure discipline. Keep briefs and
mode skills focused on their task-specific requirements. Read this file fully
before planning or delegating the first worker.

<!-- @include shared/decision-discipline.md -->

## 1. Frame the goal and route specialists

Before decomposition, establish one goal contract:

- one user-assigned topic, its stable topic slug, and an arc slug for the
  current execution arc;
- desired outcome and why it matters;
- scope explicitly in and out;
- done criteria and verification evidence;
- constraints and compatibility requirements;
- the user's quality criterion for the end-state;
- the product's defining user outcome and, where material, the mechanism or
  hypothesis through which it intends to deliver that outcome;
- the committed product boundary and smallest executable walking skeleton when
  the arc affects architecture or product flow;
- known decisions, unknowns, and empirical assumptions.

Orient from project sources and existing handover, board, or design records
before asking questions. The active mode decides how unresolved choices reach
the user or become ratification/parking items.

Use the `define-goal` skill when this contract is absent, the next milestone is
unclear, the product purpose has shifted, reviews disagree about what success
means, or scope grows without advancing the defining value path. Use that
skill as the owner of goal framing.

The plan must identify the earliest executable checkpoint that exercises and
evaluates the defining value path and apply the `define-goal` skill's milestone
challenge. Keep product acceptance tied to the defining value path and
label infrastructure-only evidence for what it establishes.

Resolve factual uncertainty through the global routing rules before asking the
user to decide it. Before implementation planning, delegate to the `architect`
agent when module boundaries, public contracts, data flow, mechanisms, or the
desired clean end-state remain open; when existing architecture needs
assessment; or when a plan would otherwise invent architecture.

Give the architect the ratified frame and expected result. It returns design
options, recommendations, evidence, and unresolved decisions to the lead; it
does not authorize implementation or expand scope. If the frame is
insufficient, it returns focused questions rather than guessing. Skip this
stage when a ratified design or strong existing pattern already determines the
work. Start implementation planning only after load-bearing architecture is
ratified or authorized under the active mode's decision protocol.

For an independent assessment, use `second-opinion` to challenge a proposed
decision, including an architectural decision, or a fresh `architect` in
REVIEW mode to assess the architecture itself. Use both when they address
distinct questions. The lead commissions specialist follow-up for concrete
unresolved questions and keeps each author separate from its independent
reviewer. Select depth through the chosen skill and adjust it as evidence
warrants.

Specialist output always returns to the lead for synthesis. The lead remains
accountable for the whole arc and is the only component that mediates user
decisions or authorizes the next phase.

## 2. Plan gate

For a multi-worker implementation arc, have a `plan` worker produce one written
plan containing:

- the goal contract and authoritative design sources;
- packages sized for one worker;
- exclusive file zones, including created and modified files;
- dependency order and dispatch waves;
- per-package verification commands and permitted side effects;
- empirical assumptions with cheap early tests;
- integration checkpoints chosen by blast radius;
- open questions and decision points for the lead to resolve.

Prefer consumer-bearing vertical packages. Separating foundational layers is
appropriate when a concrete dependency requires it, but the plan must identify
the earliest runnable composition checkpoint and explain why preceding work
cannot be validated through a consumer sooner. Do not schedule successive
foundation-only waves merely because their concepts can be designed
independently.

Every substantial addition must name its current or committed consumer and the
required behavior, realistic failure, or enduring contract instability it
addresses. Include capabilities needed for the current milestone even when
their implementation is additive. Defer later capabilities when they can be
added without replacing required contracts or compromising current integrity;
record their activation conditions with the plan's deferrals.

A current consumer may justify current implementation. A later committed
consumer normally justifies preserving a clean additive path, not implementing
its supporting structure now. Move that structure onto the current path only
when deferral would replace a semantic identity or boundary already required by
current behavior, or would leave a plausible supported-workload integrity
failure.

Before freezing a public API, sketch representative declaration, registration,
and runtime call sites and inspect the strongest analogous API in the
repository. Challenge refactoring-hostile literals, duplicated names, and
unnecessary wrappers. Internal correctness does not pass the public-surface
gate until consumer usage is coherent.

Compare unreleased abstractions with the clean intended end-state. Implement
together anything whose deferral would immediately reshape the same public
contracts; defer orthogonal capabilities. Extra structure may earn its place
through cleaner contracts, protected invariants, proven variation, or credible
extensibility. Ceremony and speculative scope require an explicit decision.

Derive zones from dependencies and concept ownership. Give every shared
contract, invariant, and cross-document concept one canonical owner. If two
packages need the same file or concept, merge them, extract a single-owner
package, or sequence them.

Test novel load-bearing assumptions before downstream work. On domain-heavy
arcs, plan golden examples and hand-verified fixtures early.

Have a fresh `review` worker challenge the plan's requirements coverage, source
grounding, dependencies, integration seams, verification, and silent-failure
paths. Fold substantive results into the plan and rerun the affected review.
Do not launch implementation workers from an unreviewed plan. A critic is
separate: use one only when a difficult premise or trade-off needs reasoning
pressure beyond source grounding. Return unresolved decisions or a
non-converging review loop to the active mode.

Use a fresh worker for the independent initial judgment. Use
the same reviewer to verify that its findings were addressed. Start another
fresh review only when the premise or target materially changes, the result is
genuinely contested, or the user explicitly requests another independent
opinion. The review role owns independent frame reassessment.

A plan review must challenge cumulative scope as well as requirements coverage.
Classify scope-expanding recommendations as **current blockers**, **deferred
committed requirements**, or **speculative concerns**. A current blocker
violates committed behavior, an enduring current contract, or realistic
integrity under supported workloads. A deferred committed requirement belongs
to later committed behavior and can be added without replacing the current
architecture; record its activation condition and keep it out of the current
package graph. A speculative concern lacks a committed consumer or plausible
supported-workload failure; keep it as a labeled observation until evidence
justifies action. When a review round only adds structure,
require it to test a smaller clean, coherent option and its effect on the
earliest runnable composition checkpoint. Return a non-converging scope-growth
loop to the lead with the alternatives and supporting evidence.

## 3. Worker brief contract

Choose roles through the global routing rules. Every brief names:

1. One task and its expected result: a response or explicitly named artifact
   files, with the required content or format.
2. Authoritative sources and required skills or project instructions.
3. One exclusive file zone and explicit no-touch zones.
4. Current ratified decisions, their rationale, and material assumptions.
5. Task-specific STOP conditions.
6. Concrete verification commands and permitted side effects.
7. The living board path, with an instruction to flag board/spec
   contradictions.

For substantive specialist artifacts, the lead supplies concrete
output file paths in the brief, normally under the active arc's `.scratch/`
directory. Assign those files to the specialist's write zone and identify
existing artifacts to update. Short factual answers may remain in the response.
References to boards or source files grant reading; specify any write ownership
separately. Prepare required directories in the lead when the worker's command
permissions cannot create them.
Instruct each specialist to write its assigned files directly and return their
paths with a concise summary. Grant the permissions needed for those writes
within the assigned file zone.
Scout and explore return discovery results in their responses and remain
read-only; assign artifact-producing work to a role that can write it.

Use spec-as-source and brief-as-delta. Point to ratified sources instead of
copying shared decisions. An override must name the section and decision that
authorized it; return an unmarked conflict to the lead before dependent work.
Treat legacy FINAL labels as current authorization subject to the global
reconsideration rule. Workers actively report material reasons to revisit a
decision; the lead resolves revisions under the active mode's authority.
Relay project-specific rules, not generic role discipline. Add an anti-regression
STOP when older sources may still encode a reversed decision.

## 4. Dispatch and integration

Launch dependency-ready packages in waves. Run only disjoint file zones and
concept ownership concurrently; sequence shared files and contracts under one
owner. Among equally ready, safely isolated packages, the lead may prioritize
work that establishes a pattern needed by later packages.

Destructive actions whose safety depends on user authorization remain owned by
the user-facing lead. A worker may inventory targets, map impact, and perform
subsequent adaptations, but the lead resolves the exact targets, obtains
confirmation, and executes the approved deletion, reset, or discard. Do not
relay destructive authorization through a worker brief unless the orchestration
environment explicitly preserves it as trusted authority.

The lead also owns Git index/history mutations and tracked-file moves. Workers
provide exact rename mappings and perform associated content edits after the
lead executes the approved `git mv` operation.

Treat unexplained out-of-zone changes as potentially belonging to the user.
Attribute them before acting and never revert them. Inspect the working tree,
index, and package boundaries after each wave.

Use the orchestrator's tracked liveness and wait/resume mechanisms first.
Resume related work with the warm worker and tell it what exists, what remains,
and what changed. A new task gets a fresh worker.

The lead owns integration seams and verifies that the packages compose
through their intended interfaces before accepting integration. New work
discovered outside the goal contract remains a proposal until the active mode
authorizes a scope change.

Before large fan-out, at milestones, and after reversals or containment, step
back from the local diff. Recheck the work against the desired end-state:
whether exceptions reveal a missing general mechanism, symmetric cases were
missed, concepts have multiple owners, failures can stay silent, or dead weight
and documentation drift remain. A cleaner root repair outside the ratified
scope stays a proposal until the active mode authorizes it. Stop rethinking
when remaining unknowns are empirical or further yield is cosmetic.

## 5. Acceptance

Review every worker result before acceptance:

- require actual gate output and distinguish baseline failures from
  regressions;
- treat reported test results as claims until independently rerun;
- use `verify` for load-bearing claims or full conformance when error cost is
  high; otherwise spot-check the decisive claim;
- triage disclosed judgment calls instead of silently accepting them;
- allow acceptance gates to fail—never bend implementation or evidence to
  force green.

Report defects only as confirmed findings grounded in current source with a
violated requirement or invariant and concrete impact. Keep unresolved risks
and intent questions separate; a structural preference is not a defect.

Choose integration gates by blast radius. Use targeted checks after isolated
waves; run the whole-repository gate after cross-cutting changes, at agreed
milestones, and before final acceptance when such a gate exists. An active mode
may tighten these checkpoints. When the baseline is already red, add targeted
checks over touched surfaces for what the broken gate would otherwise cover.

## 6. Retry and containment

Use the global retry and escalation rule. If escalation still fails, invoke
the active mode's user-decision or parking protocol.

When accepted output later proves wrong, stop downstream consumers, map the
blast radius, reopen the owning zone with its warm worker when viable, re-verify
dependents, and disclose the error and containment in the current record.

## 7. Evidence and state

Maintain one living board under
`$HOME/.agents/skills/shared/board-files.md`. Record the goal contract, worker
state, decisions, verification status, scope proposals, containment, and next
action as reality changes.

For a consequential claim that requires a legal, regulatory, medical,
scientific, or other external expert, record an external-validation item on the
board: claim, owner, status, evidence, and affected behavior. Keep behavior
fail-closed only where it depends on an unresolved load-bearing claim. The
active mode decides whether to ask, ratify, or park.

Promote conclusions that must outlive the arc under
`$HOME/.agents/skills/shared/durable-docs.md`; keep transient coordination and
grounding notes under `.scratch/<topic-slug>/<arc-slug>/`.
