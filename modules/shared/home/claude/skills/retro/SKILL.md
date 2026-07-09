---
name: retro
description: >-
  Mine the current session for durable learnings and route each to the right
  config layer (global CLAUDE.md, project CLAUDE.md, a skill, an agent prompt,
  project docs, settings/hooks) — propose-only, the user ratifies every item.
  Best run at the end of a work arc or before compaction, while the friction
  is still in context.
disable-model-invocation: true
---

# Retro — turn session friction into durable rules

## 1. What to mine for

The mining is main-agent work — a fresh subagent cannot see the session's
friction; don't delegate it. Walk the session for friction with a fingerprint:

- corrections the user made twice — propose the rule that would have prevented
  the second;
- structured questions the user answered past the options ("Other",
  counter-proposals) — find the mis-framing behind them;
- rules the user had to state that no config layer carries;
- surprises that cost cycles: tool behavior, environment quirks, assumptions
  that proved wrong;
- rules that fired WRONG — noise, over-asking, a rule the user overrode:
  propose weakening or removal, not only additions;
- cost sinks: work a cheaper role or pattern would have done equally well.

An honest empty is a valid outcome — a session without durable learnings
reports that instead of inventing some.

## 2. Route each learning to ONE layer

Pick the most specific layer that covers all future recurrences — and reuse
before adding: grep the target layer first and strengthen an existing rule
rather than writing a sibling.

- **Global CLAUDE.md** — cross-project behavior of the main agent.
- **Project CLAUDE.md** — this project's conventions.
- **A skill** — a working-style pattern with its own trigger.
- **An agent prompt** (`~/.claude/agents/`) — behavior of one role.
- **Project docs** — domain knowledge and decisions (respect the project's
  existing doc shape).
- **settings/hooks** — anything that must happen mechanically rather than by
  memory.

## 3. Ratification round — propose-only

Present the findings in batched structured questions (3–4 per round), each
item carrying: the learning, the evidence (what actually happened), the
proposed edit verbatim, and the destination layer. Nothing is written until
the user approves that item. Apply ratified items in the same pass and confirm
what landed where. Phrase rules with the why and the boundary cases the user
decided — lean and information-dense, like everything else in the config.
