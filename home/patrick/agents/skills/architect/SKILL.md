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

Own the user-facing orchestration. The dedicated `architect` agent owns source
discovery, DESIGN/REVIEW reasoning, and the specialist result. Standalone use
means coordinating that agent directly for the user, independently of supervisor.
An existing lead may dispatch the same agent within its own workflow.

<!-- @include shared/decision-discipline.md -->

## 1. Frame the work

Infer DESIGN (new architecture) or REVIEW (existing architecture) from the
request. Ask for the mode and target when genuinely ambiguous. Inspect cheap
orientation sources so questions are specific; leave broad source discovery
to the architect and use its findings for follow-up.

Establish the target and boundary, goal and intended consumers, non-goals,
constraints, chosen review lenses, authoritative source pointers, and known
open decisions. Present factual claims and prior decisions as context to verify
against the cited sources. Include the requested result and any supplied output
paths. For substantive results, supply the architect a concrete output path,
expected content or format, and ownership of that artifact. In an existing
arc, use its assigned working-artifact location. In standalone use, resolve
a missing path with the user. Short bounded answers may remain in the response.

Resolve user-owned framing choices before substantive work. When an existing
lead has already established the frame, use it and return material ambiguities
to that lead for focused clarification.

## 2. Set depth and dispatch

Use the lightest level that protects the decision:

- **Quick:** one bounded question or review lens; targeted orientation and a
  concise result. Add a board or independent review only when warranted.
- **Standard:** a module, feature, or API with interacting choices; arrange one
  fresh grounding/reasoning review of the result.
- **High-stakes:** broad, costly-to-reverse, security-sensitive, or
  invariant-bearing architecture; arrange an independent critic for trade-offs
  and a fresh reviewer/verifier for grounding.

Dispatch the dedicated `architect` agent with the frame, mode, depth, expected
result, and assigned paths. Native configuration owns model, permissions,
reasoning discipline, and the output contract. Let the agent use that native
configuration. If the agent is unavailable, report the dispatch limitation
and return the fallback choice to the invoker.

Use the same architect for clarification, evolving design choices, and
amendments while the premise and target remain stable. Start a fresh worker
when they materially change or the user requests an independent architectural
judgment. Preserve continuity with the current worker throughout an ongoing
design conversation.

For an independent architectural judgment, start with a clean conversation
containing the frame and sources. Exclude earlier reviewer verdicts and desired
answers to preserve independence. Keep the design author distinct from its
independent reviewer.

## 3. Mediate and review

Relay the architect's focused questions and consequential alternatives to the
user, or to the invoking lead when delegated. Return decisions to the architect
with the relevant rationale. Scope changes and changed premises require renewed
alignment. If evidence warrants greater depth, state the increase and why.

Arrange independent review at the chosen depth. Grounding findings must be
verified against current sources; discovery summaries alone are insufficient.
Use the same reviewer to check amendments, and a fresh reviewer when the
premise or target changes, the result remains contested, or the user requests
another independent judgment. Select reviewers for the question: a fresh
architect in REVIEW mode can assess the architecture; a second-opinion reviewer
can challenge the proposed decision, premise, alternatives, and trade-offs.
Use both when they address distinct questions. Reuse a reviewer already
assigned to the same independent role and target.

Apply the shared decision discipline to consequential comparisons and material
reviewer disagreements. Preserve disagreement and return genuine trade-offs
to the user with a recommendation.

## 4. Synthesize

Spot-check load-bearing claims, explain the recommendation and alternatives,
and return the result and any artifact paths. Separate confirmed current
blockers from deferred committed requirements, speculative concerns, and
unknowns. Keep the response proportional to the decision.

End at the design or review. The result does not authorize implementation or
the next phase; the user or invoking lead owns that decision.
