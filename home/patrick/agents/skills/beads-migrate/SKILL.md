---
name: beads-migrate
description: >-
  Explicit user-invoked migration of one Markdown-tracked arc (board lists,
  issue ledger, notes and their forwarded checklist, decision records,
  handover) to beads and the current lead-mode conventions. Carries over live
  state only; history stays in files.
---

# Beads migrate

Migrate the arc the user names. For a goal pair, migrate both sides in one run.

## Inventory and map

1. List the arc's trackers: goal objective or standing prompt, lead notes,
   topic entries in Markdown backlogs, and other trackers. Count live entries
   by kind: decisions awaiting the lead, open issues, planned or in-flight
   packages, deferrals, rulings in force, unreleased rulings, standing
   principles and constraints, environment caveats, arc-only rules, and done
   criteria.
   Treat an entry as live while its own acceptance or decision remains. Archive
   a finished dispatch, plan or review and move its remaining criteria to the
   live owner. Collapse an arc-wide gate copied into packages into one gate
   task. Flag any criterion that keeps most entries open and any unranked item.
2. Map every live entry to `import.jsonl`; map every other entry and its reason
   to `history.md`. Store both in the arc's `.scratch/`. Apply the [Import
   mapping](#import-mapping) and [Import file](#import-file) references.
3. Trace each standing rule and constraint to a user source (goal objective,
   lead notes or instructions). Present for keep or drop any rule with no
   source, stricter than its source, or already covered by current skills or
   global instructions.
4. Map rulings cited by live entries or epics. Sweep lead notes for
   library-wide rulings without a durable owner and present them to the user
   one by one.
5. Classify live entries only; cite source paths and anchors. Split large
   trackers by source range, with each worker writing import and history files
   for its range.
6. Have an independent `verify` sample retained, archived and merged entries,
   plus gate edges.
7. Show the user the inventory, provenance and ruling findings, and mapping
   counts before setup or import. The user's first confirmation releases the
   mapped rulings, arc rules, done criteria and memories for the migration;
   then the migrating agent writes them.

## Import live state

After the first confirmation, run beads setup unless the repository already
has `.beads/`, then import `import.jsonl` using the [Import mapping](#import-mapping)
and [Import file](#import-file): the root epic, arc and sub-arc epics,
checkpoints and their items.

- Run `bd import --dry-run import.jsonl` first. It must report every issue as
  new; otherwise choose another epic ID.
- On retry, import only entries still missing.
- Resolve every `Skipped dependency` reported by import; import skips a
  dependency whose target is missing and still succeeds.

## Reconcile and retire

1. Compare per-source counts with `import.jsonl` and `history.md`. Read back
   every mapped dependency with `bd dep list <id>` and resolve every skipped
   dependency.
2. Write the board summary into the root epic description; see
   [Structure](#structure).
3. For a goal pair, make the owners and epic rules authoritative in place of
   the old lead notes; retain the notes under `history/` as decision records.
   Give the user the replacement goal objective `$goal-agent for goal epic
   <title>`; see [Goal relay](../shared/goal-relay.md#goal-relay).
4. Show the reconciliation and obtain the user's second confirmation.
5. After confirmation, move replaced trackers to `history/` with a one-line
   banner pointing to beads. Replace migrated entries in backlog documents and
   topic deferral sections with
   `bd list --status deferred --label topic:<topic-slug>`; see [Deferrals and
   environment facts](#deferrals-and-environment-facts) and
   [Arc close](#arc-close).
   Retain non-goals and milestone exclusions. Report counts, gaps and epic IDs.

## Shared conventions

<!-- @include shared/beads-setup.md -->

<!-- @include shared/work-tracking.md -->

For a goal pair, read `$HOME/.agents/skills/shared/goal-relay.md` and apply it,
including its writer ownership, question states and handoff procedure.

## Import mapping

| Old entry | Beads |
|---|---|
| Item awaiting a decision | [Question](#question), type `decision`, status `open`; use [Decision packet](#decision-packet), marking missing sections "not recorded" |
| Report awaiting acknowledgment | comment on its live owner, or history |
| Open issue, defect, investigation | `task`, `bug`, `spike`; assigned to `user` when it waits for a person's action |
| Planned or in-flight package | [Package](#package), with [Acceptance](#acceptance) and `blocks` dependencies; with complete evidence, status `in_review`, assigned to the acceptor; otherwise leave open and unassigned, with the remainder in acceptance |
| Paused package | `task` with pause comment; with complete evidence, status `in_review`, assigned to the acceptor; otherwise open and unassigned, with the remainder in acceptance |
| Merged duplicates | one issue; put other old IDs as `aliases: <ids>` in its description |
| Deferral or backlog entry | [Deferrals and environment facts](#deferrals-and-environment-facts): status `deferred`, `defer_until` when dated, revisit condition as a comment |
| Ruling in force | if held by its owner, history; otherwise a task writing it into its owner ([Rulings](#rulings)) or the implementing package spec. Keep the source note as the decision record |
| Unreleased ruling | decision in its question's `design`, status `decided` (Goal relay) |
| Released ruling not yet landed | its question, ruling in `design`, status `released`, assigned to `goal-agent` (Goal relay) |
| Principle or constraint | user's chosen owner: docs, skills, `AGENTS.md` or root epic `design` |
| Goal-wide rule | goal epic `design` |
| Arc-only rule | arc epic `design` |
| Temporary environment fact | memory row `{"_type":"memory","key":…,"value":…}` |
| Arc done criteria | arc epic `acceptance_criteria` |
| Checkpoint or milestone | [Checkpoint](#checkpoint), type `milestone`, depends on contributing items |

## Import file

Use the `bd export` schema (`bd import --help`). Split source by owner using
[Structure](#structure): use a goal epic over one arc epic per topic arc when
importing several arcs; otherwise use the arc epic as root. Add sub-epics for
sub-arcs. Give each epic its short ID and each child `<epic>.<n>` in source
order. Set explicit per-item `priority` under [Priority](#priority)
(omitted priority means 0), add its labels including
`topic:<topic-slug>` (import does not inherit labels), and add its dependencies
including `parent-child` to its epic. Set `external_ref` to the old ID and
`source_system` to the tracker's file name for each issue. Include comments
inline.

Store live content in fields: `design` describes remaining work; comments hold
latest gate evidence, pause notes and revisit conditions, attributed to who
recorded them. Put migration notes in history; put arc-wide criteria once in
the arc epic's acceptance. Omit retired rules; do not negate them.
