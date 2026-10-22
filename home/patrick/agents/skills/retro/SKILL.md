---
name: retro
description: >-
  Mine the current session for durable learnings and route each to the right
  config layer (global or project agent instructions, a skill, an agent prompt,
  project docs, settings/hooks) — propose-only, the user ratifies every item.
  Best run at the end of a work arc or before compaction.
disable-model-invocation: true
---

# Retro — capture durable learnings

Propose every learning for user ratification. Apply only approved edits.

## Collect evidence

- Review the session in the main conversation for concrete recurring friction
  and durable learnings. Use [Learning signals](#learning-signals).
- If the session yields no durable learning, report an empty result.

## Route each learning

- Assign each learning to one most-specific layer that covers future
  recurrences. Search that layer first and strengthen an existing rule with
  the new evidence before adding one; see [Routing targets](#routing-targets).

## Propose and ratify

- Batch related proposals while keeping each independently reviewable.
- Ask for wanted behavior (trigger, scope, depth, affected modes); infer the
  instruction text from the answers.
- For every item, show the learning, triggering evidence, destination,
  inferred edit, expected observable behavior and validation method; ask one
  go/no-go on behavior and destination. Reuse existing cases.
- Use executable checks for deterministic hooks and generators where
  practical. For judgment-heavy rules, retain scenarios in the existing
  working artifact; distinguish expected behavior, observed results and
  reliability that remains untested.

## Apply and validate

- Pass every edit against the global instructions' Skill instructions rule
  before applying; preserve execution and authority boundaries.
- Edit the canonical source when skills are rendered or store-backed; treat
  installed generated output as immutable.
- Run applicable checks and report results and limits. For rendered or
  store-backed skills, run the owner-provided validation and build.
- Report whether activation remains necessary. Activate only when existing
  authorization covers it.

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
