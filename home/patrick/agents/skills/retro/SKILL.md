---
name: retro
description: >-
  Turn this session's lessons into proposed rule changes for me to ratify.
argument-hint: "[focus]"
disable-model-invocation: true
---

# Retro — capture durable learnings

Propose every learning for user ratification. Apply only approved edits.

## Steps

1. **Collect.** Review the whole session for concrete recurring friction and
   durable learnings. After a compaction, read the session transcript file,
   not only the summary. Use [Learning signals](#learning-signals).
   Output: each learning with its triggering evidence, or an empty result.
2. **Route.** Assign each learning to one most-specific layer that covers
   future recurrences. Search that layer first and strengthen an existing rule
   with the new evidence before adding one; see
   [Routing targets](#routing-targets).
   Output: per learning, its destination and the rule it strengthens or adds.
3. **Propose.** Batch related proposals while keeping each independently
   reviewable. Ask under [Question format](#question-format), covering trigger,
   scope, depth and affected modes; infer the instruction text from the
   answers. For every item, show the learning, triggering evidence,
   destination, inferred edit, expected observable behavior and validation
   method; ask one go/no-go on behavior and destination. Reuse existing cases.
   Output: the user's go/no-go per item.
4. **Apply.** Pass every approved edit against the `skill-authoring` skill;
   preserve execution and authority boundaries. Edit the canonical source when
   skills are rendered or store-backed; treat installed generated output as
   immutable.
   Output: the applied edits.
5. **Validate.** Use executable checks for deterministic hooks and generators
   where practical. For judgment-heavy rules, retain scenarios in the existing
   working artifact; distinguish expected behavior, observed results and
   reliability that remains untested. For rendered or store-backed skills, run
   the owner-provided validation and build. Activate only when existing
   authorization covers it.
   Output: check results and limits; whether activation remains necessary.

## Learning signals

- A correction made twice: propose the rule that would have prevented the
  second correction.
- A structured question answered beyond its options (such as "Other" or a
  counterproposal): identify the framing that missed the user's choice.
- A rule the user had to state that no configuration layer carries.
- A surprise that cost cycles: tool behavior, environment quirks or an
  assumption that proved wrong.
- A rule that fired wrong through noise, over-asking or a user override:
  propose narrowing or removing it.
- Work a cheaper role or pattern could have done equally well.

## Routing targets

| Layer | Use for |
|---|---|
| Global agent instructions | Main-agent behavior across projects |
| Project agent instructions | This project's conventions |
| Skill | A working-style pattern with its own trigger |
| Custom-agent definition | Behavior of one role |
| Project docs | Domain knowledge and decisions, in the existing document shape |
| Settings or hooks | Behavior that must happen mechanically rather than by memory |

<!-- @include shared/question-format.md -->
