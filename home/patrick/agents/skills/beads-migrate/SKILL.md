---
name: beads-migrate
description: >-
  Explicit user-invoked migration of one Markdown-tracked arc (board lists,
  issue ledger, notes and their forwarded checklist, decision records,
  handover) to beads and the current lead-mode conventions. Carries over live
  state only; history stays in files.
---

# Beads migrate

Migrate the arc the user names; for a goal pair, both sides in one run.
Follow the work-tracking conventions below; for a goal pair, also
`$HOME/.agents/skills/shared/goal-relay.md`.

<!-- @include shared/beads-setup.md -->

<!-- @include shared/work-tracking.md -->

## 1. Inventory and map

List the arc's trackers, including a goal objective or standing prompt, lead
notes and the topic's entries in a Markdown backlog, and count their live
entries by kind: decisions awaiting the lead, open issues, packages planned or
in flight, deferrals, rulings in force, unreleased rulings, standing
principles and constraints, environment caveats, arc-only rules and done
criteria. Map every live entry into `import.jsonl` (§2) and every other
entry, with its reason, into `history.md`, both in the arc's `.scratch/`.

- **Live** = the entry's own acceptance or decision remains. A finished
  dispatch, plan or review archives; its remaining criteria move to the live
  owner. An arc-wide gate clause copied into packages becomes one gate task.
  Flag to the user any criterion that keeps most entries open.
- **Rule provenance:** trace each standing rule and constraint to a user source
  (goal objective, lead notes, instructions). Present rules without a source,
  stricter than their source, or covered by current skills or global
  instructions for keep or drop.
- **Rulings:** map those that live entries or the epic cite. Sweep the lead
  notes for library-wide rulings without a durable owner and present them to
  the user one by one.
- History stays in files: classify live entries only and cite sources by path
  and anchor. Split large trackers by source range; each worker writes its
  range's import and history files.
- An independent `verify` samples retained, archived and merged entries and
  the gate edges.
- Show the user the inventory, the provenance and ruling findings and the
  mapping counts before setup or import. The user's confirmation releases the
  mapped rulings, arc rules, done criteria and memories; the migrating agent
  writes them.

## 2. Import live state

With the user's confirmation, run the beads setup unless the repository
already has `.beads/`, then import `import.jsonl`: the arc epic and its
children, each with `external_ref` = old id, `source_system` = its tracker
and the source anchor in `metadata.source`:

| Old entry | Beads |
|---|---|
| Item awaiting a decision | question, type `decision`, label `human`; packet sections it lacks marked "not recorded" |
| Report awaiting acknowledgment | comment on its live owner, or history |
| Open issue, defect, investigation | `task`, `bug`, `spike`; label `human` when it waits for a person's action |
| Planned or in-flight package | `task` with acceptance, `blocks` dependencies, assignee when in flight; label `review` and the acceptor when awaiting acceptance |
| Paused package | open `task` assigned to its worker, pause comment |
| Merged duplicates | one issue; the other old ids as `aliases: <ids>` in its description |
| Deferral, backlog entry | status `deferred`, `defer_until` when dated, the revisit condition as a comment |
| Ruling in force | held by its owner: history; otherwise a task writing it into its owner (work-tracking), or the implementing package's spec. The source note stays the decision record |
| Unreleased ruling | decision comment on its question, label `decided` (relay) |
| Released round not yet taken in | intake (relay) |
| Principle, constraint | the user's chosen owner: docs, skills, AGENTS.md or the epic `design` |
| Arc-only rule | arc epic `design` |
| Temporary environment fact | memory row `{"_type":"memory","key":…,"value":…}` |
| Arc done criteria | arc epic `acceptance_criteria` |

`import.jsonl` uses the `bd export` schema (`bd import --help`): give each
issue a stable id (`<prefix>-<old id>`), an explicit `priority` (omitted means
0, critical), its labels including `topic:<topic-slug>` (import does not
inherit them), its `dependencies` including `parent-child` to the epic, and
its comments inline. Run `bd import --dry-run import.jsonl` first; it must
report every issue as new. Import upserts by id and resets live state (status,
assignee, notes), so qualify an id that reports "updated" with the arc slug,
and on a retry import only the entries still missing. Import skips a
dependency whose target is missing, prints `Skipped dependency`, and still
succeeds.

## 3. Reconcile and retire

- Compare per-source counts with `import.jsonl` and `history.md`. Read back
  each mapped dependency (`bd dep list <id>`) and resolve every skipped one.
- Write the board summary into the arc epic's description (work-tracking).
- For a goal pair: the owners and the epic's arc rules replace the old lead
  notes as authority; the notes stay in `history/` as decision records.
  Give the user the replacement goal objective
  `$goal-agent for arc epic <title>`.
- After the user confirms the reconciliation, move the replaced trackers to
  `history/` with a one-line banner pointing to beads, remove the migrated
  entries from their backlog docs, and report the counts, gaps and epic id.
