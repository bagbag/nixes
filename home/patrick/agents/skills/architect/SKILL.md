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
means coordinating that agent directly for the user, independently of
supervisor. An existing lead may dispatch the same agent within its own
workflow. Use `explore-options` when the uncertainty is which solution families
deserve consideration. Reuse its result for architecture work; exploration adds
no automatic architecture or review round and preserves applicable review gates.

<!-- @include shared/decision-discipline.md -->

## 1. Frame the work

Infer DESIGN (new architecture) or REVIEW (existing architecture) from the
request. Ask for the mode and target when genuinely ambiguous. Inspect cheap
orientation sources so questions are specific; leave broad source discovery to
the architect and use its findings for follow-up.

Establish the target and boundary, goal and intended consumers, non-goals,
constraints, chosen review lenses, authoritative source pointers, and known open
decisions. Present factual claims and prior decisions as context to verify
against the cited sources. Include the requested result and any supplied output
paths. For substantive results, supply the architect a concrete output path,
expected content or format, and ownership of that artifact. In an existing arc,
use its assigned working-artifact location. In standalone use, resolve a missing
path with the user. Short bounded answers may remain in the response.

Resolve user-owned framing choices before substantive work. When an existing
lead has already established the frame, use it and return material ambiguities
to that lead for focused clarification.

## 2. Set depth and dispatch

Use the lightest level that protects the decision:

- **Quick:** one bounded question or review lens; targeted orientation and a
  concise result. Add a board or independent review only when warranted.
- **Standard:** a module, feature, or API with interacting choices; obtain one
  independent assessment covering reasoning and grounding.
- **High-stakes:** expand the same assessment around concrete costly-to-reverse
  consequences and load-bearing uncertainties. Add a critic or verifier when a
  named unanswered question needs distinct expertise or independent evidence.

Examine consequences for security, authority, isolation, concurrency,
irreversible effects, and uncertain contract boundaries. Increase depth when the
decision warrants it or when the scope of impact cannot be established; finding
a defect first is not required. State the uncertainty and extra investigation.
Investigation depth and reviewer count are separate choices; these risks do not
automatically require additional agents. Reuse an independent assessment that
covers the same target, sources, and current revision across overlapping review
requirements.

Dispatch the dedicated `architect` agent with the frame, mode, depth, expected
result, and assigned paths. Native configuration owns model, permissions,
reasoning discipline, and the output contract. Let the agent use that native
configuration. If the agent is unavailable, report the dispatch limitation and
return the fallback choice to the invoker.

Use the same architect for clarification, evolving design choices, and
amendments while the premise and target remain stable. Start a fresh worker when
they materially change or the user requests an independent architectural
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
Use a fresh reviewer for the initial independent judgment, then retain it for
focused amendment checks. Close the review when findings are resolved and agreed
checks pass; reopen broader review on evidence of a materially changed premise
or blast radius. A fresh architect in REVIEW mode can assess the architecture; a
second-opinion reviewer can challenge the proposed decision, premise,
alternatives, and trade-offs. Add another independent role only for a named
unanswered question or explicit user request.

Apply the shared decision discipline to consequential comparisons and material
reviewer disagreements. Preserve disagreement and return genuine trade-offs to
the user with a recommendation.

## 4. Synthesize

Spot-check load-bearing claims, explain the recommendation and alternatives, and
return the result and any artifact paths. Separate confirmed current blockers
from deferred committed requirements, speculative concerns, and unknowns. Keep
the response proportional to the decision.

End at the design or review. The result does not authorize implementation or the
next phase; the user or invoking lead owns that decision.
