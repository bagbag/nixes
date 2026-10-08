---
name: beads-migrate
description: >-
  Explicit user-invoked migration of one Markdown-tracked arc (board lists,
  issue ledger, notes and their forwarded checklist, decision records,
  handover) to beads and the current lead-mode conventions. Carries over open
  state only; resolved history stays in files.
---

# Beads migrate

Migrate the arc the user names, both sides of a goal pair in one run. Follow
the work-tracking conventions below; for a goal pair, also
`$HOME/.agents/skills/shared/goal-relay.md`.

<!-- @include shared/beads-setup.md -->

<!-- @include shared/work-tracking.md -->

## 1. Inventory

List the arc's trackers, including a goal objective or standing prompt, lead
notes and the topic's entries in a Markdown backlog, and count their open
entries by kind: decisions awaiting the lead, open issues, packages planned or
in flight, deferrals, rulings in force, unreleased rulings, standing
principles and constraints, environment caveats, arc-only rules and done
criteria. Show the user the inventory and the mapping below before writing
anything.

## 2. Import open state

With the user's confirmation, run the beads setup unless the repository
already has `.beads/`, and create the arc epic with its topic label. Then
import as children of the epic, keeping the old id at the start of each title
and the source anchor in the description:

| Old entry | Beads |
|---|---|
| Item awaiting a decision | question labelled `human`; packet sections it lacks marked "not recorded" |
| Open issue, defect, investigation | `task`, `bug`, `spike`; label `human` when it waits for the lead |
| Planned or in-flight package | `task` with acceptance, `blocks` dependencies, assignee when in flight; label `review` and the acceptor when awaiting acceptance |
| Deferral, backlog entry | `bd defer --reason "<revisit condition>"` |
| Ruling in force | its owner (work-tracking): doc text, or the implementing package's spec until the code lands; the source note stays the decision record |
| Unreleased ruling | decision comment on its question (relay) |
| Released round not yet taken in | intake (relay) |
| Principle, constraint | its owner: docs, skills or AGENTS.md |
| Arc-only rule | arc epic `--design` |
| Temporary environment fact | memory (work-tracking) |
| Arc done criteria | arc epic `--acceptance` |

Write the issues as JSONL: give each a stable id (`<prefix>-<old id>`), an
explicit `priority` (omitted means 0, critical), its labels including
`topic:<topic-slug>` (import does not inherit them), and its `dependencies`
including `parent-child` to the epic. Run
`bd import --dry-run <file>` first; it must report every issue as new. Import
upserts by id and resets live state (status, assignee, notes), so qualify an
id that reports "updated" with the arc slug, and on a retry import only the
entries still missing. Import skips a dependency whose target is missing,
prints `Skipped dependency`, and still succeeds.

## 3. Reconcile and retire

- Write a mapping of every open entry to its issue id or to the reason it was
  left out, and compare per-source counts with it. Read back each mapped
  dependency (`bd dep list <id>`) and resolve every skipped one.
- Write the board summary into the arc epic's description (work-tracking).
- For a goal pair: the owners and the epic's arc rules replace the old lead
  notes as authority; the notes stay in `history/` as decision records.
  Give the user the replacement goal objective
  `$goal-agent for arc epic <title>`.
- After the user confirms the reconciliation, move the replaced trackers to
  `history/` with a one-line banner pointing to beads, and report the counts,
  gaps and epic id.
