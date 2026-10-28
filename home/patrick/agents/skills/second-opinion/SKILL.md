---
name: second-opinion
description: >-
  Get an independent verdict from a fresh reviewer on a consequential
  decision, architecture, plan, blocker or proposed solution. Use when the
  user asks for a second or 2nd opinion, a fresh reviewer, fresh eyes,
  independent reassessment or sign-off; the verdict returns to the user. Not
  for widening the options (explore-options).
---

# Second Opinion

Own user-facing orchestration; the `second-opinion` agent owns the judgment and
report. Use `explore-options` for a broader solution space; treat its result as
context, not independent review. Apply [Reviewers](#reviewers) throughout.

## Frame

- Inspect the cheapest orientation sources. Brief neutrally: the exact
  decision, proposal or claim; committed goal, product boundary, constraints
  and non-goals; authoritative sources and current empirical facts; opinion or
  strict sign-off.
- Write long briefs to a file. For a substantive assessment, assign a path,
  expected content and exclusive write ownership; keep short opinions in the
  response.

## Dispatch

- Start each requested opinion with a new `second-opinion` agent and only the
  neutral brief; native configuration owns model, sandbox and output contract.
- Give repository access and source pointers; require verification of the
  brief's factual claims. On the user's request, permit broader exploration
  while keeping the decision and product boundary explicit.
- The reviewer may challenge architectural decisions; you own specialist
  follow-up. Commission an architect when a concrete architectural question
  warrants it; give each reviewer a distinct question.
- Preserve the requested depth in the brief. Depth is an initial budget; the
  reviewer tests whether the decision is as bounded as framed and keeps the
  report on the material decision:
  - **Quick:** decisive authority and source seams; verdict, material
    disagreement, decision-changing findings.
  - **Standard:** relevant option space, sources, trade-offs, refinements.
  - **Thorough:** adjacent consequences, alternatives, cumulative architecture.

## Return

- Spot-check load-bearing evidence; apply the [Decision protocol](#decision-protocol)
  to premises and alternatives.
- Return the options, your recommendation after considering them, preserved
  disagreements with what changed or stayed persuasive, and remaining decisions
  for the user. The opinion authorizes nothing.

<!-- @include shared/decision-protocol.md -->

<!-- @include shared/reviewers.md -->
