## Decision protocol

Run before every consequential question, ruling or recommendation; one line
per step for a local, reversible choice.

1. **Top-down:** from the goal and the user's principles, describe how it
   should work: what it is, which module owns it, how a consumer uses it.
2. **Bottom-up:** establish how it works today from authoritative sources;
   verify each premise (probe or docs for runtime claims) and state what
   stays unverified.
3. **Root fix:** the gaps between the two are the problem; the posed question
   may be one symptom of them (XY problem). Answer the question whose answer
   settles the others, and find the fix that removes their cause.
4. **End state:** the cleanest coherent result as if designed fresh
   (greenfield), under the user's quality criterion (consumer DX for a
   library), independent of effort and churn: consumer example, size, what it
   replaces and breaks.
   - Question the need for every part, existing and proposed: keep only what a
     realistic consumer needs (in-repo call-site counts only size a change).
   - Separate required properties from mechanisms; compare mechanisms by those
     properties.
   - Prefer what the platform and existing modules already provide; for
     coordination, use the platform's own state, lifecycle, failure and retry
     semantics before adding parallel state. Align with how other modules
     solve it or justify the difference.
   - Check footguns, failure modes, performance and latency.
   - Existing design, documents and earlier decisions are inputs: keep what
     still serves the goal; name each revision with its evidence and the
     finished work it changes.
5. **Options:** compare materially different options, including ones outside
   the posed framing: ranking, decisive trade-offs, strongest downside, and
   what would change the recommendation. Screen the chosen option choice by
   choice (behaviour, failure handling, naming, exposure, scope limits,
   documented non-features): a choice is contested when any source names a
   second realistic or coherent option, revisions of earlier rulings or
   conventions included.
6. **Decide:** rule what your mode's decision rules allow; bring contested
   choices, with the options and a recommendation, to the decider.

Challenge proposals, options and verdicts from others: verify their facts,
test them against the derived end state, and form your own option set. Rerun
from Top-down when a later step, an answer or new evidence changes the
problem; record the changed premise and its effect.

### Reviewers

- Scale depth to stakes and to uncertainty about impact; depth and reviewer
  count are separate choices.
- A fresh reviewer gives the initial independent judgment and checks the
  amendments. Reuse an independent assessment of the same target, sources and
  revision; reopen on a changed premise or blast radius; add a reviewer only
  for a named unanswered question or a user request.
- Reconcile material disagreement once: give each reviewer the other's
  strongest argument in a neutral frame; a changed position names new
  evidence, a corrected premise or a reweighting. Return remaining judgment
  differences to the decider.
- A hybrid is a new option: test whether it keeps its parents' benefits or
  only combines their costs.
- Agreement after shared framing or a lead-authored amendment is correlated
  evidence. Distinguish facts from preferences; preserve material
  disagreement and return trade-offs with a recommendation.
