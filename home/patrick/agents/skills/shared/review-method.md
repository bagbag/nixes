1. **Frame.** Identify the artifact, its brief, goal, claims and acceptance
   conditions. Read `$HOME/.agents/skills/shared/decision-protocol.md`;
   apply its End-state criteria and Concern classes.
   Output: the review frame and criteria.
2. **Check claims.** Spot-check factual claims against their authoritative
   sources. Run the smallest permitted read-only probe when needed.
   Output: verified facts and source locations; label assumptions.
3. **Assess.** Check correctness, counterexamples, requirement coverage,
   source contradictions, known findings and shared append-lists
   ([Change requests](change-requests.md) Shared append-lists). Merge
   near-copies while keeping each copy's validation and error handling; split
   by job, never by line count. Account for the brief's known findings without
   re-raising them.
   Output: the cases and requirements assessed.
   <!-- @include shared/reuse-check.md -->
4. **Step back.** Reassess the frame and end state against the whole artifact.
   Invoke `step-back` on it. Use all lenses for designs, plans, contracts and
   architecture; use `root-fix bloat clean mechanics gaps consumer` for code
   diffs. Treat a proposal outside the brief or a ruling as a frame change,
   not a defect.
   Output: the end state and any proposed frame change.
5. **Verify findings.** Ground each candidate in current source: name the
   violated requirement or invariant, trigger, impact and exact locations.
   Seek counterexamples, competing explanations and evidence against your own
   finding; check whether its remedy fixes the cause. Separate verified facts
   from behavior assumptions and classify uncertainty as risk or open question.
   Consider removal, consolidation and reuse before proposing a remedy.
   Output: confirmed findings, risks and questions with evidence.
6. **Result.** Rank confirmed findings by impact. Present structural
   preferences as trade-offs and summarize lenses without findings in one
   line. Report a verdict and one line for each applicable Cleanliness test.
   Return confirmed findings with risks and unresolved intent questions;
   keep unrelated observations within scope. Run the brief's checks and your
   probes; list probes run from the brief's named scratch folder or the session
   scratch folder. Unless the brief forbids fixes, fix findings within
   its rules; otherwise make only a small contained fix that is the only clean
   option, rerun checks after code fixes, and list each fix with its finding.
   <!-- @include shared/limits-assessor.md -->
   <!-- @include shared/report.md -->
   Output: verdict; cleanliness lines; findings, risks and open questions.
