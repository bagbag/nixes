1. **Frame.** Identify the artifact, its brief, goal, claims and acceptance
   conditions. Read `$HOME/.agents/skills/shared/decision-protocol.md`;
   apply its End-state criteria and Concern classes.
   Output: the review frame and criteria.
2. **Check claims.** Spot-check factual claims against their authoritative
   sources. Run the smallest permitted read-only probe when needed, in the
   scratch folder the brief names, else one named after your task in your
   session's (`$HOME/.agents/bin/scratch dir`).
   Output: verified facts and source locations, the probes run; label
   assumptions.
3. **Assess.** Check correctness, counterexamples, requirement coverage,
   source contradictions and shared append-lists
   ([Change requests](change-requests.md) Shared append-lists). For code,
   apply Writing code in the global instructions; judge fit with codebase
   conventions and report an outdated one with the better pattern. Merge
   near-copies while keeping each copy's validation and error handling; split
   by job, never by line count. Account for the brief's known findings without
   re-raising them. For skill, agent-definition, instruction and engine-printed
   instruction text, apply [skill-authoring](../skill-authoring/SKILL.md).
   Output: the cases and requirements assessed.
4. **Step back.** Invoke `step-back` on the whole artifact: all lenses for
   designs, plans, contracts and architecture; `mechanics consumer root-fix
   gaps bloat clean` for code diffs. Treat a proposal outside the brief or a
   ruling as a frame change, not a defect.
   Output: the end state and any proposed frame change.
5. **Verify findings.** Ground each candidate in current source: name the
   violated requirement or invariant, trigger, impact and exact locations.
   Seek counterexamples, competing explanations and evidence against your own
   finding; check whether its remedy fixes the cause. Separate verified facts
   from behavior assumptions and classify uncertainty as risk or open question.
   Consider removal, consolidation and reuse before proposing a remedy; prefer
   the simplest remedy that meets the requirement and preserves behavior,
   boundaries and integrity.
   Output: confirmed findings, risks and questions with evidence.
6. **Checks and fixes.** Run the brief's checks. Unless the brief forbids
   fixes, fix findings within its fix rules; without fix rules, make only a
   small contained fix that is the only clean option. Rerun the checks after a
   code fix.
   Output: the checks run; each fix with its finding.
7. **Result.** Rank confirmed findings by impact. Present structural
   preferences as trade-offs and summarize lenses without findings in one
   line. Report a verdict and one line for each applicable Cleanliness test.
   Return confirmed findings with risks and unresolved intent questions;
   report unrelated observations only within the brief's scope.
   Output: verdict; cleanliness lines; findings, risks and open questions.

<!-- @include shared/reuse-check.md -->
<!-- @include shared/limits-assessor.md -->

<!-- @include shared/report.md -->
