---
name: question-me
description: >-
  Ask me every open decision now, related board items included.
argument-hint: "[focus and follow-ups]"
disable-model-invocation: true
---

# Question me

<!-- @include shared/rerun.md -->

Question me now:

1. **Collect** every open decision in this discussion, plus related items
   building on the same premises and related open board items (search the
   board with `$HOME/.agents/bin/board related <terms>` where the repository
   has `.beads/`). Count as open: recommendations not yet confirmed
   (step-back, challenge-rulings, ground, ask-advisor, review findings) and
   rulings you made yourself in the discussion, each with its strongest
   alternative.
   Output: the open decisions.
2. **Check** the open decisions under the Check step of
   [Asking the user](../shared/asking.md#asking-the-user)
   (`$HOME/.agents/skills/shared/asking.md`).
   Output: each invocation and what it changed.
3. **Ask** the decisions whose premises are settled under
   [Question format](#question-format).
   Output: the questions; the held decisions, each with what it waits on.

<!-- @include shared/question-format.md -->
