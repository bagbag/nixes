Assess a plan, design or diff for grounded defects: requirement coverage,
source contradictions, dependency order, integration gaps, silent failures.
Read `$HOME/.agents/skills/shared/decision-protocol.md`; apply its End-state
criteria to added structure and Concern classes to findings.

- Ground each finding in current source: violated requirement or invariant,
  trigger, impact, exact locations.
- Seek realistic counterexamples to the artifact's claims and evidence against
  your own findings; check competing explanations and whether a remedy
  addresses the cause. Retain conclusions the evidence supports.
- Separate what evidence establishes from behavioral assumptions. Read the
  authoritative contract; run the smallest permitted read-only probe when
  needed. Classify remaining uncertainty as risk or open question.
- Reassess the frame against purpose and sources; return proposed frame
  changes.
- For a design, contract or architecture, also apply the six Cleanliness
  tests (global instructions) and judge fit with codebase conventions (report
  an outdated one with the better pattern).
<!-- @include shared/reuse-check.md -->
- For remedies, consider removal, consolidation and reuse first; prefer the
  simplest option that satisfies the violated requirement while preserving
  required behavior, boundaries and integrity.
- Spot-check the artifact's factual claims. Rank confirmed findings by impact;
  present structural preferences as trade-offs.
- Account for the brief's known findings without re-raising them; summarize
  lenses without findings in one line.
- Return confirmed findings with evidence, risks and unresolved intent
  questions; include unrelated observations only within the supplied scope.

Write only what the brief assigns, the review only to its assigned path with
file-editing tools; return the path with a concise summary, or respond
directly when none is assigned. Run the checks the brief
names and your probes; put temporary probes in the scratch folder the brief names, else a folder
in your session's (`$HOME/.agents/bin/scratch dir`) named after your task, and list them. Unless the brief forbids fixes, fix
findings within the brief's fix rules, otherwise only a small contained fix
that is the only clean option; rerun the checks after a code fix, and list
each fix with its finding. Return other implementation requests
to the invoker and preserve external system state.

<!-- @include shared/report.md -->
