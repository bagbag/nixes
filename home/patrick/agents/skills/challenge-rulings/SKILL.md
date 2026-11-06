---
name: challenge-rulings
description: >-
  Test the rulings made along the way against their strongest alternatives:
  yours, and the user's where the evidence points away. Use before an
  approval request, or when the user asks whether the rulings hold.
argument-hint: "[focus and follow-ups]"
---

# Challenge rulings

<!-- @include shared/rerun.md -->

1. **Inventory.** List your own rulings (asking.md's disclosure kinds:
   entailed decisions, defect-fix behaviors, dropped or narrowed parts, framing
   choices), each choice you left to another role, each strong recommendation,
   and each released ruling a recommendation rests on or Related linked
   (`priorRulings`).
   Output: the list.
2. **Own rulings and left choices.** Check that each is entailed (Decision
   authority in `$HOME/.agents/skills/shared/decision-protocol.md`); name its
   strongest alternative and its footguns. Make each that is not, or that you
   are unsure of, a question with its alternatives.
   Output: per item, the test its alternative fails, or the question.
3. **Strong recommendations.** Check each against the same protocol's
   Recommendation strength and its evidence; make it a lean where a criterion
   fails. For each decisive reason, say why it decides the choice.
   Output: per recommendation, kept strong or made a lean.
4. **Released rulings.** Say why each holds on its merits, or why it fails.
   Where the evidence points away from a user's ruling or a project rule the
   set rests on, bring it as a question with that evidence.
   Output: per ruling, holds or the question.
