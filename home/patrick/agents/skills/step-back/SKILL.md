---
name: step-back
description: >-
  Rethink the direction from scratch: the cleanest end state, then gaps,
  over-engineering and magic in the whole. Use before presenting a plan,
  design or approval request, or when the user says "step back".
argument-hint: "[lenses] [focus and follow-ups]"
---

# Step back

Lens names at the start of the argument select lenses (`/step-back root-fix
bloat`); the rest of the argument is the focus. Without lenses, run the base
pass: the stance on the current focus, judged by the default criteria.

## Stance

Judge greenfield: previous rulings, contracts and current usages are no
authority; priorities and deferral rules decide when, not what. Find the
cleanest end state, keeping DX in mind; then judge the whole picture: is the
combined result clean and coherent? Name each known bad practice in the
design, a recommendation or a requested behavior, with its source; push back
and recommend the established practice instead. Think through each changed
recommendation and verify the facts it rests on, as the `ground` skill does;
where none is strong, list the decisive trade-offs.

## Where

Default: the current focus. Each selected lens widens it.

- **goal:** one level up; judge the design against the goal behind it. Dig
  into the real problem behind the ask and whether the design fixes its root
  or works around it (XY problem).
- **decisions:** every decision in the discussion together, not only the
  latest.
- **foundations:** what the design builds on: earlier rulings, conventions and
  contracts; re-judge them too.

## What

Default: consumer, root-fix, bloat and gaps. Selected lenses become the deep
focus; keep the other default criteria to a line each.

- **consumer:** walk each realistic consumer, current callers included,
  through the whole flow end to end (for an API: set up, configure, use,
  handle failure, test), noting what each step needs; judge the options
  against those walks.
- **root-fix:** does it fix the root cause, not a symptom? Trace the cause;
  the root may lie outside this module or repo; recommend the fix there.
- **bloat:** over-engineered? Too much magic?
- **gaps:** under-built: does anything the goal or realistic consumers need
  fall short?
- **clean:** the six cleanliness tests, one by one.
- **overfit:** tailored to this case, or does it hold for the neighbouring
  cases?
- **mechanics:** how each part actually works end to end, and what breaks.
- **options:** find radically different ways to solve the problem: other
  mechanisms, other owners, or removing the need, not variants, plus the
  established practice. Argue each at its strongest; drop one only for a
  stated constraint or sourced fact. Say for each whether it is kept or
  dropped, and why.
