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

For a substantive report, assign a concrete output path and instruct the
reviewer to write it directly. Include the expected content or format and write
ownership; use the active arc's working-artifact location when available. Short
bounded opinions may remain in the response.

## 2. Dispatch fresh

Start the initial opinion with a new `second-opinion` agent and a clean
conversation containing only the neutral brief. The native agent definition owns
its model, sandbox, reasoning discipline, and output contract. An explicit
request for a new second opinion or fresh sign-off always starts a new
independent reviewer. Reusing an earlier assessment for another workflow gate
does not fulfill that request; clarifications and repairs stay with the
reviewer.

The reviewer may challenge architectural decisions as part of its assessment.
The lead owns specialist follow-up: commission an architect when a concrete
architectural question warrants that expertise. Give each reviewer a distinct
question and keep the design author separate from its independent reviewer.

Give the agent repository access and source pointers, while requiring it to
verify the brief's factual claims independently against current sources. If the
user says to let it expand, permit broader exploration while keeping the
requested decision and product boundary explicit.

Preserve the requested review depth in the brief:

- **Quick:** inspect only decisive authority and source seams; return the
  recommendation or verdict, material disagreement, and at most the few
  findings that could change the decision.
- **Standard:** inspect the relevant option space, sources, trade-offs, and
  refinements.
- **Thorough:** expand across adjacent consequences, alternatives, and
  cumulative architecture when the decision warrants it.

Depth is an initial budget, not a hard ceiling. Test whether the decision is as
bounded as framed. Examine consequences for security, authority, isolation,
concurrency, irreversible effects, and uncertain contract boundaries. Increase
depth when the decision warrants it or when the scope of impact cannot be
established; finding a defect first is not required. State the uncertainty and
extra investigation. Investigation depth and reviewer count are separate
choices; these risks do not automatically require additional agents. Keep the
report focused on the material decision.

## 3. Synthesize

Spot-check load-bearing evidence. Compare the independent opinion with the
current direction, preserve meaningful disagreements, and explain what changed
or stayed persuasive. The opinion is not authorization: return the options, the
lead's recommendation after considering them, and the remaining decisions to the
user before proceeding.

Use the same reviewer for focused clarification or amendment checks; close the
review when findings are resolved and agreed checks pass. Reuse adequate
assessment of the same target, sources, and revision across review requirements.
Reopen broader review on evidence of a materially changed premise or blast
radius. An additional fresh opinion needs a stated distinct purpose or explicit
user request.

### Reconcile material reviewer disagreement

Apply the shared discipline only when disagreement could materially change the
decision or downstream work. Give each warm reviewer the other's strongest
argument and request a focused keep, amend, or withdraw reassessment. Reuse warm
reviewers for one focused reconciliation while the premise and target remain
stable. After resolving factual disputes, return remaining judgment differences
to the user with options and a recommendation. Further neutral adjudication is
optional for a named unanswered question or user request.
