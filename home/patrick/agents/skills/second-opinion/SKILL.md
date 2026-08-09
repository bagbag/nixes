---
name: second-opinion
description: >-
  Obtain a fresh independent Sol second opinion on a consequential decision,
  architecture, plan, blocker, or proposed solution. Use when the user says
  “ask fresh Sol,” “get a second/2nd opinion,” “explore other options,”
  “recommend refinements,” or requests fresh sign-off. Frame the question
  neutrally, dispatch the dedicated source-grounded reviewer without inherited
  conversational conclusions, and return its recommendation and disagreements
  for user decision rather than automatically adopting the verdict.
---

# Second Opinion

Own the user-facing orchestration. The dedicated `second-opinion` agent owns the
independent judgment and report.

## 1. Frame neutrally

Inspect the cheapest relevant orientation sources first. Give the reviewer:

- the exact decision, proposal, or claim;
- the committed goal, product boundary, constraints, and non-goals;
- authoritative repository sources and current empirical facts; and
- whether the user wants an independent opinion or strict sign-off.

Omit the lead's recommendation, desired answer, and earlier reviewer verdicts.
When reviewing a concrete proposal, include it as the object of review without
endorsing it. Put a long brief in the active arc's `.scratch/` directory; never
create a durable document merely to dispatch the review.

## 2. Dispatch fresh

Start a new `second-opinion` agent with no inherited conversation turns. Never
reuse a warm worker for the initial opinion. The native agent definition owns
its model, sandbox, reasoning discipline, and output contract; do not duplicate
them in the brief.

Give the agent repository access and source pointers, while requiring it to
inspect current sources independently rather than trust the brief's factual
claims. If the user says to let it expand, permit broader exploration while
keeping the requested decision and product boundary explicit.

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
