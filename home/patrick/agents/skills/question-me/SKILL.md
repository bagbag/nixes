---
name: question-me
description: >-
  User-invoked: ask the user every open decision of the discussion and related
  board items now. Optional argument names the focus.
disable-model-invocation: true
---

# Question me

On every mention of this skill, re-read this file and apply it anew to the
focus named with it, otherwise to the current discussion.

Question me now: collect every open decision in this discussion, plus related
items building on the same premises and related open board items (search the
board with `$HOME/.agents/bin/board related <terms>` where the repository has
`.beads/`). Count as open: recommendations not yet confirmed (step-back,
recheck, review findings) and rulings you made yourself in the discussion,
each with its strongest alternative. Ask the decisions whose premises are
settled and name the held ones. Ask under [Question format](#question-format).

<!-- @include shared/question-format.md -->
