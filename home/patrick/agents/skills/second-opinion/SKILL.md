---
name: second-opinion
description: >-
  Obtain a fresh independent second opinion on a consequential decision,
  architecture, plan, blocker, or proposed solution. Use when the user says
  “ask a fresh reviewer,” “get a second/2nd opinion,” “explore other options,”
  “recommend refinements,” or requests fresh sign-off. Frame the question
  neutrally, dispatch the dedicated source-grounded reviewer without inherited
  conversational conclusions, and return its recommendation and disagreements
  for user decision rather than automatically adopting the verdict.
---

# Second Opinion

Own the user-facing orchestration. The dedicated `second-opinion` agent owns the
independent judgment and report.

<!-- @include shared/decision-discipline.md -->

## 1. Frame neutrally

Inspect the cheapest relevant orientation sources first. Give the reviewer:

- the exact decision, proposal, or claim;
- the committed goal, product boundary, constraints, and non-goals;
- authoritative repository sources and current empirical facts; and
- whether the user wants an independent opinion or strict sign-off.

Omit the lead's recommendation, desired answer, and earlier reviewer verdicts.
When reviewing a concrete proposal, include it as the object of review without
endorsing it. Keep long dispatch briefs in the active arc's `.scratch/`
directory.

For a substantive report, assign a concrete output path and instruct the reviewer
to write it directly. Include the expected content or format and write ownership;
use the active arc's working-artifact location when available. Short bounded
opinions may remain in the response.

## 2. Dispatch fresh

Start the initial opinion with a new `second-opinion` agent and a clean
conversation containing only the neutral brief. The native agent definition
owns its model, sandbox, reasoning discipline, and output contract.

The reviewer may challenge architectural decisions as part of its assessment.
The lead owns specialist follow-up: commission an architect when a concrete
architectural question warrants that expertise. Give each reviewer a distinct
question and keep the design author separate from its independent reviewer.

Give the agent repository access and source pointers, while requiring it to
verify the brief's factual claims independently against current sources. If
the user says to let it expand, permit broader exploration while
keeping the requested decision and product boundary explicit.

Preserve the requested review depth in the brief:

- **Quick:** inspect only decisive authority and source seams; return the
  recommendation or verdict, material disagreement, and at most the few
  findings that could change the decision.
- **Standard:** inspect the relevant option space, sources, trade-offs, and
  refinements.
- **Thorough:** expand across adjacent consequences, alternatives, and
  cumulative architecture when the decision warrants it.

Depth is an initial budget, not a hard ceiling. Begin by testing whether the
decision is actually as bounded as framed. Escalate Quick to Standard when its
effects may reach the defining outcome, enduring contracts, domain or authority
semantics, security, concurrency, cross-package ownership, or costly downstream
work, or when the quick pass cannot establish that those surfaces are
unaffected. Escalate Standard to Thorough when the governing premise or product
boundary may be wrong, consequences are systemic or hard to reverse, or source
evidence and independent judgments do not converge.

State that depth increased and why. Keep the report concise around the material
decision even after deeper work. Expand when further investigation could
materially change the judgment.

## 3. Synthesize

Spot-check load-bearing evidence. Compare the independent opinion with the
current direction, preserve meaningful disagreements, and explain what changed
or stayed persuasive. The opinion is not authorization: return the options,
the lead's recommendation after considering them, and the remaining decisions
to the user before proceeding.

Use the same reviewer for a focused clarification or amendment check. Start a
new fresh reviewer when the premise or target materially changes, the result is
genuinely contested, or the user explicitly requests another independent
opinion.

### Reconcile material reviewer disagreement

Apply the shared discipline only when disagreement could materially change the
decision or downstream work. Give each warm reviewer the other's strongest
argument and request a focused keep, amend, or withdraw reassessment. Reuse
warm reviewers while the premise and target remain stable; use fresh neutral
adjudication after factual closure when consequential disagreement remains.
Return residual disagreement to the user.
