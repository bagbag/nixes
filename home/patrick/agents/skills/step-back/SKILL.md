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
lenses deeply. A named lens set gets deep treatment; give every other lens
one line. Keep the greenfield stance: prior rulings, contracts and current
usages do not define the end state, though priorities and deferral rules decide
when to do the work. Judge the cleanest end state with DX in mind. Name known
bad practice in the design, recommendation or requested behavior with its
source; push back and recommend the established practice.

## Protocol

Steps 3–13 are the lenses; each outputs its findings, or
`nothing: checked <what>`.

1. **Frame.** Name the focus, current recommendation, artifact or outcome, and
   the goal one level up.
   Output: the focus and goal being judged.
2. **Premises.** List every fact the recommendation and options rely on:
   current behavior, consumers, constraints, and what other owners already do.
   Confirm or refute each from current source or a run and cite it; name any
   premise you cannot verify.
   Output: verified and unverified premises with sources.
3. **Goal (`goal`).** Judge against the goal behind the request and the real
   problem behind the ask.
4. **Decisions (`decisions`).** Assess every decision in the discussion together.
5. **Foundations (`foundations`).** Reassess earlier rulings, conventions and
   contracts the design builds on.
6. **Mechanics (`mechanics`).** Trace each part end to end and identify what
   breaks.
7. **Options (`options`).** Find materially different mechanisms, owners, or
   ways to remove the need. Argue each at its strongest and drop it only for a
   stated constraint or sourced fact. Reassess the frame and return proposed
   changes to it.
8. **Consumer (`consumer`).** Walk each realistic consumer through the whole
   flow, noting what each step needs: current callers and, for a library,
   external consumers without in-repo call sites; for an API: set up,
   configure, use, handle failure, test. Judge the options against those walks.
9. **Root fix (`root-fix`).** Trace the cause and recommend its fix, even when
   it lies outside the module or repository.
10. **Gaps (`gaps`).** Find what the next run or a realistic consumer still
    needs; record a later need as a deferred follow-up.
11. **Bloat (`bloat`).** Find over-engineering and unnecessary magic.
12. **Overfit (`overfit`).** Test the design against neighboring cases.
13. **Clean (`clean`).** Apply each of the six cleanliness tests one by one.
14. **Converge.** If any earlier step changes anything, restart at step 1 and
    run every lens again. Carry a premise check forward only while its source
    is unchanged. Stop after a run that changes nothing. If a run returns to an
    earlier recommendation, stop and list the decisive trade-offs.
    Output: the unchanged run, or the cycle and its decisive trade-offs.
15. **Result.** State the end state, dropped options and why, and what remains
    unverified.
    Output: the recommendation and unresolved risks or questions.

Write the run log to `step-back-<focus>.md` in the task's scratch folder, with a
section for each run and step. In chat, give the result and one line per run
stating what changed.
