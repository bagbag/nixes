# Worker arcs (shared convention)

Supervisor and autopilot both use this contract for planning, briefing,
dispatch, and acceptance. Their own skills define who decides, isolation,
checkpoints, context handling, and mode-specific safety ceilings.

Read this file fully before planning or delegating the first worker.

## Plan gate

For a multi-worker arc, have a `plan` worker produce one written plan containing:

- scope explicitly in and out;
- packages sized for one worker;
- exclusive file zones, including files created and existing files modified;
- dependency order and dispatch waves;
- per-package verification commands and side-effect cautions;
- empirical assumptions with cheap early tests;
- open questions and decision points, never silently resolved.

Derive zones from the decomposition. Pull shared cross-cutting files into a
dedicated consolidation package with one owner. If two packages need the same
file, merge them, extract the shared package, or sequence them. Assign each
cross-document invariant or contract one canonical owner.

On domain-heavy work, plan golden examples and hand-verified fixtures early.
Test novel load-bearing assumptions before building downstream mechanisms.
Declare each wave's scope boundary in the plan and every brief.

Have a fresh `review` worker challenge requirements coverage, source grounding,
dependency soundness, integration seams, verification gaps, and silent-failure
paths. Fold substantive findings into the plan, then review again. No
implementation worker launches on an unreviewed plan. A non-converging loop or
unresolved decision returns to the active mode's decision protocol.

The source-grounding reviewer and a reasoning critic have different jobs. The
reviewer checks the plan against sources; a critic challenges premises and
trade-offs when the reasoning is genuinely hard. One worker may cover both only
when separate fresh contexts are unavailable.

## Worker brief contract

Choose the role using the global agent instructions.

Every brief names:

1. One task and its expected result.
2. Authoritative sources and required skills or project instructions.
3. One exclusive file zone and explicit no-touch zones.
4. Ratified decisions marked FINAL.
5. Task-specific STOP conditions.
6. Concrete verification commands and permitted side effects.
7. The living board path, with an instruction to flag board/spec
   contradictions.

Use spec-as-source and brief-as-delta. Point workers to one ratified source
instead of copying shared decisions. An override must name the section it
overrides and the decision that authorized it; an unmarked conflict is a STOP.

Do not repeat generic discipline already present in the role prompt. Do relay
every project-specific convention and every rule adopted during the arc.
Pre-classify known decision points as FINAL or explicit STOPs. Include an
anti-regression STOP when touching a reversed decision because older documents
may still state it.

Acceptance gates must be allowed to fail. Never bend a fixture, production code,
or expected count merely to force green.

## Dispatch and acceptance

Run only disjoint zones concurrently. Sequence shared files and shared concepts
under one owner. Launch dependency-ready packages in waves so landed work can be
reviewed before downstream workers consume it.

Every result receives review before acceptance:

- require actual gate counts and separate pre-existing failures from
  regressions;
- use `verify` for load-bearing claims or full brief conformance when being
  wrong is expensive;
- below that threshold, spot-check the decisive claim;
- treat a reported gate result as a claim until independently rerun;
- ground suspected defects in current source before reporting or acting;
- triage disclosed judgment calls rather than silently accepting them.

When the baseline is already red, compensate with targeted checks over touched
files for violations the broken gate would otherwise detect. Run the
whole-repository integration gate at the checkpoint defined by the active mode.

Related follow-up or incomplete output returns to the warm worker. An unrelated
task gets a fresh worker. Follow the global escalation rule; if escalation
fails, invoke the active mode's blocker or parking protocol.

When accepted output later proves wrong, stop downstream consumers, map the
blast radius, reopen the owning zone, re-verify every dependent, and record and
disclose the containment. Never silently patch an accepted error.
