---
name: step-back
description: >-
  Rethink the direction from scratch: derive the cleanest end state and test it
  against the whole design. Use before presenting a plan or design, or when
  the user says "step back".
argument-hint: "[lenses] [focus and follow-ups]"
---

# Step back

Lens names at the start of the argument select lenses (`/step-back root-fix
bloat`); the rest of the argument is the focus. Without lens names, assess all
11 lenses deeply. A named lens set gets deep treatment; give every other lens
one line. Keep the greenfield stance: prior rulings, contracts and current
usages do not define the end state, though priorities and deferral rules decide
when to do the work. Judge the cleanest end state with DX in mind. Name known
bad practice in the design, recommendation or requested behavior with its
source; push back and recommend the established practice.

## Protocol

Run all 11 lenses deeply by default. If the argument names lenses, give those
deep treatment and one line to each other lens. For every lens, report its
finding or `nothing: checked <what>`. For plans, designs and diffs, check
requirement coverage, source contradictions, dependencies, integration gaps
and silent failures. Ground findings in current source with the violated
requirement or invariant, trigger, impact and exact locations. Seek
counterexamples and competing explanations; separate verified evidence from
behavioral assumptions and classify remaining uncertainty as a risk or open
question. Apply `decision-protocol.md` End-state criteria and Concern classes.

1. **Frame.** Name the focus, current recommendation, artifact or outcome, and
   the goal one level up.
   Output: the focus and goal being judged.
2. **Premises.** List every fact the recommendation and options rely on:
   current behavior, consumers, constraints, and what other owners already do.
   Confirm or refute each from current source or a run and cite it; name any
   premise you cannot verify.
   Output: verified and unverified premises with sources.
3. **Goal.** Judge against the goal behind the request; identify the real
   problem and whether the design fixes its root or works around it.
   Output: the goal finding or `nothing: checked <what>`.
4. **Decisions.** Assess every decision in the discussion together.
   Output: the decisions finding or `nothing: checked <what>`.
5. **Foundations.** Reassess earlier rulings, conventions and contracts the
   design builds on.
   Output: the foundations finding or `nothing: checked <what>`.
6. **Consumer.** Walk each realistic current consumer through the whole flow,
   including setup, use, failure handling and testing where relevant.
   Output: the consumer finding or `nothing: checked <what>`.
7. **Root fix.** Trace the cause and recommend its fix, even when it lies
   outside the module or repository.
   Output: the root-fix finding or `nothing: checked <what>`.
8. **Bloat.** Find over-engineering and unnecessary magic.
   Output: the bloat finding or `nothing: checked <what>`.
9. **Gaps.** Find what the next run or a realistic consumer still needs.
   Output: the gaps finding or `nothing: checked <what>`.
10. **Clean.** Apply each of the six cleanliness tests one by one.
    Output: one finding or `nothing: checked <what>` for each test.
11. **Overfit.** Test the design against neighboring cases.
    Output: the overfit finding or `nothing: checked <what>`.
12. **Mechanics.** Trace each part end to end and identify what breaks.
    Output: the mechanics finding or `nothing: checked <what>`.
13. **Options.** Find materially different mechanisms, owners, or ways to
    remove the need. Argue each at its strongest and drop it only for a stated
    constraint or sourced fact. Reassess the frame and return proposed changes
    to it.
    Output: alternatives, trade-offs and any frame proposal.
14. **Converge.** If any earlier step changes anything, restart at step 1 and
    run every lens again. Carry a premise check forward only while its source
    is unchanged. Stop after a run that changes nothing. If a run returns to an
    earlier recommendation, stop and list the decisive trade-offs. Do not
    reread earlier run logs.
    Output: the unchanged run, or the cycle and its decisive trade-offs.
15. **Result.** State the end state, dropped options and why, and what remains
    unverified.
    Output: the recommendation and unresolved risks or questions.

Write the run log to `step-back-<focus>.md` in the task's scratch folder, with a
section for each run and step. In chat, give the result and one line per run
stating what changed. Do not invoke the ground skill; premise verification and
convergence belong to this protocol.

<!-- @include shared/reuse-check.md -->
<!-- @include shared/limits-assessor.md -->
<!-- @include shared/report.md -->
