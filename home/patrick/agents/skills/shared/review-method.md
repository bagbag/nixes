Assess a plan, design or diff for grounded defects: requirement coverage,
source contradictions, dependency order, integration gaps, silent failures.
Read `$HOME/.agents/skills/shared/decision-protocol.md`; apply its End-state
criteria to added structure and Concern classes to findings.

- Ground each finding in current source: violated requirement or invariant,
  trigger, impact, exact locations.
- Seek realistic counterexamples to the artifact's claims and evidence against
  your own findings; check competing explanations and whether a remedy
  addresses the cause; keep the findings the evidence supports.
- Separate what evidence establishes from behavioral assumptions. Read the
  authoritative contract; run the smallest permitted read-only probe when
  needed. Classify remaining uncertainty as risk or open question.
- Reassess the frame against purpose and sources; return proposed frame
  changes.
- For a design, contract or architecture, also apply the six Cleanliness
  tests (global instructions) and judge fit with codebase conventions (report
  an outdated one with the better pattern). Flag a new list that parallel
  changes would each add entries to
  ([Change requests](change-requests.md) Shared append-lists).
<!-- @include shared/reuse-check.md -->
- Judge added and changed code against Writing code in the global
  instructions. Merge near-copies into one,
  keeping each copy's validation and error handling; split a function by job,
  never by line count.
- For remedies, consider removal, consolidation and reuse first; prefer the
  simplest option that meets the violated requirement and preserves behavior,
  boundaries and integrity.
- Spot-check the artifact's factual claims. Rank confirmed findings by impact;
  present structural preferences as trade-offs.
- Account for the brief's known findings without re-raising them; summarize
  lenses without findings in one line.
- Return confirmed findings with evidence, risks and unresolved intent
  questions; include unrelated observations only within the supplied scope.

<!-- @include shared/limits-assessor.md -->
Run the brief's checks and your probes. Put probes in the scratch folder the brief names, else one named after your task in your session's (`$HOME/.agents/bin/scratch dir`), and list them. Unless the brief forbids fixes,
fix findings within the brief's fix rules, otherwise only a small contained fix
that is the only clean option; rerun the checks after a code fix and list each
fix with its finding.

<!-- @include shared/report.md -->
