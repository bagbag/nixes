---
name: round-intake
description: >-
  Take a list of items I hand over into a question round.
argument-hint: "[items]"
disable-model-invocation: true
---

# Round intake

Take the argument's items into a question round in a deciding session (lead
or solo), through `protocol` under Round in
`$HOME/.agents/skills/role/protocols/decide.md`. Without items, ask for the
list in one message and continue once it arrives. Ground the items inline,
without subagents.

1. **Points.** Make each item one point, worded as written. Read only enough
   to state it: which code, file or rule it names and what it asks. A review
   request ("is X good?") becomes one question, a lean on evidence, which the
   check loop's passes rewrite or split. Stage an item naming a board item on
   that item (`board`: its id); Stage's overlap search covers the rest of the
   board.
   Output: the points.
2. **Start or join.** With a round open, add the items as new questions
   through `protocol edit`, the pasted list as the quote. Otherwise run
   `protocol start round --discussion` with the points; add
   `--no-board <dir>` for a topic outside this repository's board or one
   without a board.
   Output: the round's next step.
3. **Run** the round, following the engine's output.
   Output: that protocol's outputs.
