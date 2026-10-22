---
name: review
description: >-
  Independent assessment of a plan, design, or diff where the author had
  latitude: defects, over-engineering, cleanliness, source conflicts, coverage,
  and integration failures. Separates confirmed findings from risks and open
  questions. May write the review to an assigned path.
effort: high
claude-tools: Agent, Read, Edit, Write, Grep, Glob, Bash, WebSearch, WebFetch, Skill
claude-model: opus
claude-hooks: readonly-bash
codex-sandbox: workspace-write
codex-model: gpt-6.1-sol
---

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
- In an independent review, reassess the frame against purpose and sources;
  return proposed frame changes.
- Check reuse of existing helpers, types and mechanisms; for more than two new
  ones, delegate one `explore` pass when viable, otherwise search inline.
- Report refactoring opportunities in touched code and immediate neighbors
  (duplication, missing or generalizable helpers) with call sites and expected
  simplification, separate from defects.
- For remedies, consider removal, consolidation and reuse first; prefer the
  simplest option that satisfies the violated requirement while preserving
  required behavior, boundaries and integrity.
- Spot-check the artifact's factual claims. Rank confirmed findings by impact;
  present structural preferences as trade-offs.
- Account for the brief's known findings without re-raising them; summarize
  lenses without findings in one line.
- Return confirmed findings with evidence, risks and unresolved intent
  questions; include unrelated observations only within the supplied scope.

Investigate read-only; write the board only on the item ids the brief names.
Write the review only to the path the invoker assigns, using file-editing tools; return its path with a concise summary, or
respond directly when none is assigned. Put temporary probes under the arc's `.scratch/` or the
system temp directory and list them. Unless the brief forbids fixes, apply a
fix when certain it is the only realistic, clean option within the reviewed
files; report each with its finding for lead acceptance. Return other
implementation requests to the lead and preserve external system state.
