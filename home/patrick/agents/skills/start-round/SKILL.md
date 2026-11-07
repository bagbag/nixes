---
name: start-round
description: >-
  Start a proposed question round.
argument-hint: "[row number]"
disable-model-invocation: true
---

# Start round

Start the stored proposal's row: the argument's number, else row 1. Start
without asking.

1. Run `protocol start round --proposal <row>`. On a refusal, report its reason
   in one line and stop.
   Output: the round's Collect step, or the refusal.
2. Run the round under Round in `$HOME/.agents/skills/role/protocols/decide.md`,
   following the engine's output.
   Output: that protocol's outputs.
