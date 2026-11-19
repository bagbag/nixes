1. **Frame.** Identify the artifact, its brief, goal, claims and acceptance
   conditions. Read `$HOME/.agents/skills/shared/decision-protocol.md`;
   apply its End-state criteria and Concern classes.
   Output: the review frame and criteria.
2. **Check claims.** Spot-check factual claims against their authoritative
   sources. Run the smallest permitted read-only probe when needed.
   Output: verified facts and source locations; label assumptions.
3. **Assess.** Check correctness, counterexamples, requirement coverage,
   source contradictions, dependencies, integration gaps, silent failures,
   reuse and composition. For code, apply Writing code in the global
   instructions. For a design, contract or architecture, also apply the six
   Cleanliness tests and codebase conventions; report an outdated convention
   with the better pattern. Account for the brief's known findings without
   re-raising them. Flag a new list that parallel changes would each add
   entries to ([Change requests](change-requests.md) Shared append-lists).
   Output: the cases and requirements assessed.
4. **Step back.** Reassess the frame and end state against the whole artifact.
   For designs, plans, contracts and architecture, run every step-back lens.
   For code diffs, check root cause, unnecessary structure, cleanliness,
   mechanics, gaps and realistic consumers. Treat a proposal outside the brief
   or a ruling as a frame change, not a defect.
   Output: the end state and any proposed frame change.
5. **Verify findings.** Ground each candidate in current source: name the
   violated requirement or invariant, trigger, impact and exact locations.
   Seek counterexamples, competing explanations and evidence against your own
   finding; check whether its remedy fixes the cause. Separate verified facts
   from behavior assumptions and classify uncertainty as risk or open question.
   Output: confirmed findings, risks and questions with evidence.
6. **Result.** Rank confirmed findings by impact. Present structural
   preferences as trade-offs and summarize lenses without findings in one
   line. Return confirmed findings with risks and unresolved intent questions;
   keep unrelated observations within scope. Include the artifact's checks and
   probes, and list probes run from the brief's named scratch folder or the
   session scratch folder. Unless the brief forbids fixes, fix findings within
   its rules; otherwise make only a small contained fix that is the only clean
   option, rerun checks after code fixes, and list each fix with its finding.
   <!-- @include shared/reuse-check.md -->
   <!-- @include shared/limits-assessor.md -->
   <!-- @include shared/report.md -->
