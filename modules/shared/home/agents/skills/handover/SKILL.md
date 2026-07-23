---
name: handover
description: >-
  Write or consume a session handover note so work continues losslessly in a
  fresh session. Use when the user invokes the handover skill, says "write a handover",
  "continue this in a new session", before compaction with meaningful state —
  and at session start when a handover note exists in the project scratch dir.
---

# Handover — lossless session continuity

Two modes: **WRITE** (ending a stretch of work) and **ORIENT** (starting from
a note).

## Where notes live

`handover.md` in the project's existing scratch dir (`short-term-context/` or
equivalent). In ORIENT mode, never create a scratch dir or alter `.gitignore`.
In WRITE mode, if the project has no scratch convention, propose a location and
ask before creating it or changing `.gitignore`. One file, kept current.

## WRITE mode

First bring reality in sync: docs, decision log, TODO — nothing of value may
exist only in the session (same rule as pre-compaction). Then write the note,
self-contained for a reader with zero session context:

- **Anchor** — branch, HEAD commit, write date/time, and a dirty-tree fingerprint
  (`git status --short` plus the diff's hash); ORIENT's mismatch check compares
  against exactly this without assuming a matching HEAD means a matching tree.
- **State** — done and verified (with actual gate numbers) vs. in progress
  vs. not started; what was taken on a worker's word.
- **Decisions** — pointers to the durable record. A decision that exists only
  in the note is a sync gap to fix first, not a note feature.
- **Next actions**, priority-ordered, each with enough context to start cold.
- **Open questions / parked decisions**, each with your recommendation.
- **Gotchas** — environment quirks, traps discovered, things that look wrong
  but are intentional.
- **How to verify current state** — the gate commands and expected results.

Don't include: agent IDs or session references, or anything the durable docs
already say (point instead).

## ORIENT mode

When a handover note exists at session start: read it, then verify before
trusting — run its verification commands and compare the tree state against
its anchor. A mismatch is the first finding, not something to silently absorb
(the user may have worked since). Confirm the priority order with the user
(when unattended, proceed on the note's order without asking). Do not rewrite
the note merely to mark it consumed; consumption is session state. Update it
only when WRITE mode next records materially changed handover state.
