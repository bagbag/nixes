---
name: architect
description: >-
  Coordinate architecture design and review with the dedicated architect
  agent. Use when the user explicitly wants an
  architectural design for a feature, module, or API; an assessment of an
  existing architecture; or the architect skill itself. Not for implementation
  planning, implementation, or line-level code review.
---

# Architect

- Own user-facing orchestration; the `architect` agent owns discovery,
  DESIGN/REVIEW reasoning and the result. Coordinate it directly in standalone
  use; a lead may dispatch it within its workflow.
- Use `explore-options` when uncertainty concerns solution families; reuse its
  result.
- End at design or review; the user or invoking lead decides implementation and
  next phases.

## Frame

- Infer DESIGN (new architecture) or REVIEW (existing) from the request; ask for
  mode or target only when genuinely ambiguous.
- Read cheap orientation sources; leave broad discovery to the architect.
- Frame target and boundary, goal and consumers, non-goals, constraints, review
  lenses, source pointers, open decisions, requested result and paths; pass
  factual claims and prior decisions as context to verify.
- Resolve user-owned framing choices first. Under a lead, use its frame and
  return material ambiguity to it.
- For substantive results, assign an output path in the arc (ask the user when
  standalone), expected content and artifact ownership; keep short answers in
  the response.

## Depth

Use the lightest level that protects the decision:

- **Quick:** one bounded question or lens; concise result. Add a board or
  independent review only when warranted.
- **Standard:** interacting choices across a module, feature or API; one
  independent assessment of reasoning and grounding.
- **High-stakes:** extend that assessment to costly-to-reverse consequences and
  load-bearing uncertainties; add a critic or verifier for a named unanswered
  question needing distinct expertise or evidence.

Apply [Reviewers](#reviewers) for depth, count, reuse, independence and
disagreement. Explain any evidence-based increase in depth.

## Dispatch and mediate

- Dispatch with frame, mode, depth, expected result and paths; native
  configuration owns model, permissions and output contract. When the agent is
  unavailable, report it and return the fallback choice to the invoker.
- Reuse the architect while premise and target stay stable; start fresh after
  material change or for independent judgment ([Reviewers](#reviewers)).
- Relay focused questions and consequential alternatives to the user, or the
  invoking lead when delegated; return decisions and rationale to the
  architect. Realign on scope or premise changes.

## Assess and return

- Arrange independent review at the chosen depth: a fresh architect in REVIEW
  mode assesses the architecture; `second-opinion` challenges decision,
  premise, alternatives and trade-offs. Verify grounding against current
  sources, not summaries alone. Apply the [Decision protocol](#decision-protocol)
  to premises and alternatives; reassess when evidence changes the problem.
- Spot-check load-bearing claims. Return the result, artifact paths,
  recommendation and alternatives, with concerns under
  [Concern classes](#concern-classes) and unknowns separate; keep the response
  proportional to the decision.

<!-- @include shared/decision-protocol.md -->

<!-- @include shared/reviewers.md -->
