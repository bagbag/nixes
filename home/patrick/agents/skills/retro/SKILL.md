---
name: retro
description: >-
  Mine the current session for durable learnings and route each to the right
  config layer (global or project agent instructions, a skill, an agent prompt,
  project docs, settings/hooks) — propose-only, the user ratifies every item.
  Best run at the end of a work arc or before compaction, while the friction
  is still in context.
---

# Retro — turn session friction into durable rules

## 1. What to mine for

Review the session in the main conversation, where the corrections and their
context are available. Look for concrete recurring friction:

- corrections the user made twice — propose the rule that would have prevented
  the second;
- structured questions the user answered past the options ("Other",
  counter-proposals) — find the mis-framing behind them;
- rules the user had to state that no config layer carries;
- surprises that cost cycles: tool behavior, environment quirks, assumptions
  that proved wrong;
- rules that fired WRONG — noise, over-asking, a rule the user overrode:
  propose narrowing or removing the rule;
- cost sinks: work a cheaper role or pattern would have done equally well.

An honest empty is a valid outcome — a session without durable learnings
reports that instead of inventing some.

## 2. Route each learning to ONE layer

Pick the most specific layer that covers all future recurrences — and reuse
before adding: grep the target layer first and strengthen an existing rule
with the new evidence.

- **Global agent instructions** — cross-project behavior of the main agent.
- **Project agent instructions** — this project's conventions.
- **A skill** — a working-style pattern with its own trigger.
- **A custom-agent definition** — behavior of one role.
- **Project docs** — domain knowledge and decisions (respect the project's
  existing doc shape).
- **settings/hooks** — anything that must happen mechanically rather than by
  memory.

## 3. Ratification round — propose-only

Batch related proposals; keep each independently reviewable. Include:

- learning, triggering evidence, exact edit and destination;
- expected observable behavior and validation method, reusing existing cases.

Use executable checks for deterministic hooks/generators where practical.
For judgment-heavy rules, retain scenarios in the existing working artifact;
distinguish expected behavior, observed results and reliability still untested.
Phrase guidance as positive actions; preserve execution and authority boundaries.

Apply approved items, run applicable checks, and report results and limits.

When skills are rendered or store-backed, edit their canonical template source,
then run the owner-provided validation and build. Report whether activation
is still needed, and perform it only within existing authorization. Treat
installed generated output as immutable.
