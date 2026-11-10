---
name: question-me
description: >-
  Ask me every open decision now, related board items included.
argument-hint: "[focus and follow-ups]"
disable-model-invocation: true
---

# Question me

Question me now. Under autopilot, first run Return in
`$HOME/.agents/skills/role/protocols/unattended.md`. In a deciding session
(lead or solo), run these steps through the decide protocol's Round in `protocol`
(`$HOME/.agents/skills/role/protocols/decide.md`): resume the open round,
abandon an open release (`protocol abandon`), or
start one with `--discussion` and step 1's decisions as points; add
`--no-board <dir>` when they concern a topic outside this repository's board
or it has none. A list of items handed over runs under
`$HOME/.agents/skills/round-intake/SKILL.md` instead.

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
3. **Ask** the decisions whose premises are settled under asking.md's
   [Question format](../shared/asking.md#question-format).
   Output: the questions; the held decisions, each with what it waits on.
