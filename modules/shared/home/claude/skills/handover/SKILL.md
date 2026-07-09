---
name: handover
description: >-
  Write or consume a session handover note so work continues losslessly in a
  fresh session. Use when the user says "/handover", "write a handover",
  "continue this in a new session", before compaction with meaningful state —
  and at session start when a handover note exists in the project scratch dir.
---

# Handover — lossless session continuity

Two modes: **WRITE** (ending a stretch of work) and **ORIENT** (starting from
a note).

## Where notes live

`handover.md` in the project's scratch dir (its existing convention —
`short-term-context/` or equivalent; if none exists, create one and gitignore
it). One file, kept current: a handover is transient state, not an audit
trail — decisions and history belong to the project's durable records, and the
note points at them instead of re-typing them.

## WRITE mode

First bring reality in sync: docs, decision log, TODO — nothing of value may
exist only in the session (same rule as pre-compaction). Then write the note,
self-contained for a reader with zero session context:

- **Anchor** — branch, HEAD commit, and write date/time; ORIENT's mismatch
  check compares against exactly this.
- **State** — done and verified (with actual gate numbers) vs. in progress
  vs. not started; what was taken on a worker's word.
- **Decisions** — pointers to the durable record. A decision that exists only
  in the note is a sync gap to fix first, not a note feature.
- **Next actions**, priority-ordered, each with enough context to start cold.
- **Open questions / parked decisions**, each with your recommendation.
- **Gotchas** — environment quirks, traps discovered, things that look wrong
  but are intentional.
- **How to verify current state** — the gate commands and expected results, so
  the next session can check the ground it stands on.

Don't include: agent IDs or session references (they die with the session), or
anything the durable docs already say (point instead).

## ORIENT mode

When a handover note exists at session start: read it, then verify before
trusting — run its verification commands and compare the tree state against
its anchor. A mismatch is the first finding, not something to silently absorb
(the user may have worked since). Confirm the priority order with the user
(when unattended, proceed on the note's order without asking), then mark the
note consumed (date + session).
