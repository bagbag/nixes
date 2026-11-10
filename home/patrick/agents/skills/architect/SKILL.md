---
name: architect
description: >-
  Design, or map and assess, an architecture (boundaries, contracts,
  ownership, data flow) with the architect agent. Use when the user explicitly
  asks for an architectural design of a feature, module or API, to map or assess
  an existing architecture, or for the architect skill; not for implementation
  plans, implementation or line-level review.
---

# Architect

- Own user-facing orchestration; the `architect` agent owns discovery,
  DESIGN/REVIEW reasoning and the result. Coordinate it directly in standalone
  use; an invoking session may dispatch it within its workflow.
- Use `explore-options` when uncertainty concerns solution families; reuse its
  result.
- End at design or review; the user or invoking session decides implementation and
  next phases.

## 1. Frame

- Infer DESIGN (new architecture) or REVIEW (existing) from the request; ask for
  mode or target only when genuinely ambiguous.
- Read cheap orientation sources; leave broad discovery to the architect.
- Frame target and boundary, goal and consumers, non-goals, constraints, review
  lenses, source pointers, open decisions, requested result and paths; pass
  factual claims and prior decisions as context to verify.
- Resolve user-owned framing choices first. When delegated, use the invoking
  session's frame and return material ambiguity to it.
- For a substantive result, assign its output path (AGENTS.md Orchestration and
  delegation; ask the user when standalone) and expected content; keep short
  answers in the response.

Output: frame, mode and output path.

## 2. Depth

Use the lightest level that protects the decision:

- **Quick:** one bounded question or lens; concise result. Add independent
  review only when warranted.
- **Standard:** interacting choices across a module, feature or API; one
  independent assessment of reasoning and grounding.
- **High-stakes:** extend that assessment to costly-to-reverse consequences and
  load-bearing uncertainties; add a critic or verifier for a named unanswered
  question needing distinct expertise or evidence.

Apply [Reviewers](#reviewers) for depth, count, reuse, independence and
disagreement.

Output: the level, with any reason for raising it.

## 3. Dispatch and mediate

- Dispatch with frame, mode, depth, expected result and paths.
- Reuse or start a fresh architect under [Reviewers](#reviewers).
- Relay focused questions and consequential alternatives to the user, or the
  invoking session when delegated; return decisions and rationale to the
  architect. Realign on scope or premise changes.

Output: agent, mode and depth dispatched.

## 4. Assess and return

- Arrange independent review at the chosen depth: a fresh architect in REVIEW
  mode assesses the architecture; `second-opinion` challenges decision,
  premise, alternatives and trade-offs. Verify grounding against current
  sources, not summaries alone. Apply the [Decision protocol](#decision-protocol)
  to premises and alternatives.
- Spot-check load-bearing claims. Return the result, artifact paths,
  recommendation and alternatives, with concerns under
  [Concern classes](#concern-classes) and unknowns separate; keep the response
  proportional to the decision.

Output: result, artifact paths and recommendation.

<!-- @include shared/decision-protocol.md -->

<!-- @include shared/reviewers.md -->
