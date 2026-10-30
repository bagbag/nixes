---
name: board-migrate
description: >-
  Move a project's TODO/REVIEW files, trackers or older board onto the
  current board.
argument-hint: "[project or arc]"
disable-model-invocation: true
---

# Board migrate

Migrate the project or arc the user names; derive the work from the gap
between what exists and the target.

## Target

- Board model: [Board core](#board-core-beads) and
  [Board coordination](#board-coordination-beads), included below.
- Owners of knowledge, outstanding work, arc state and history:
  `$HOME/.agents/skills/shared/project-memory.md`.
- Sessions enter through `/role`; read `$HOME/.agents/skills/role/SKILL.md` for
  roles and protocols.

## Invariants

- **Live or history.** An entry is live while its own acceptance or decision
  remains open; it moves to the board. Everything else goes to history:
  `history/` files for trackers, comments for board items. A finished plan,
  dispatch or review is history; its remaining criteria move to their live
  owner. Per sentence: rules in force stay in the item's fields; dated logs
  and status go to comments.
- **History is immutable.** Leave closed board items as written: text,
  prefixes, holders and epics. Change live items only (every status except
  closed); fix wrong edges touching a live item, on either end. Write a rule still in force that lives only in a closed
  record into its owner and link the record; never edit it. Add missing
  `supersedes` edges on closed rulings when a release check meets them, not
  as a sweep.
- **Triage before migrating.** Close a live item whose outcome is moot
  (superseded, done elsewhere, no longer wanted) with that reason instead of
  migrating it. Candidates: a superseded linked ruling, a released ruling
  whose linked work is all closed, duplicates.
- **Open findings are questions.** A finding needing a decision (possible
  supersession, conflicting rulings) becomes a question blocking the affected
  items; reports list its id.
- **Nothing lost.** Reconcile counts per source with what the target holds
  plus what history holds.
- **Rules have a user source.** Trace every standing rule and constraint to a
  user source (goal, instructions, decision record). Route findings to the
  deciding session uninvestigated: a released record whose rules lack a user
  source or exceed it stays released, with a non-blocking question "Ratify or revise the flagged rules of <id>?"
  naming the finding. Ask the user only migration-scope choices.
- **One owner.** Write each rule into its owner under project-memory
  [Durable owners](../shared/project-memory.md#durable-owners); the board
  keeps the decision record. Epic text holds no rules, status or history.
- **Plain text.** Write board text in plain sentences; rewrite shorthand or
  squashed text of live entries when migrating them. Leave decision records
  past decision time as written; Live or history and text rewrites skip them.
  State missing provenance, dates and reasons as "not recorded".

## Steps

Give each step's output compactly; detail only findings and stops.

1. **Discover.** Where a board exists, run `board check --all`
   for its mechanical deviations and flags. Then inventory what it can't see:
   backlog and review files, Markdown boards, lead notes, checkpoint files,
   project instructions and docs that name trackers as owners (file roles,
   backlog pointers), epic texts holding rules, status or history, rules
   without an owner (including rules in force that live only in closed
   records), acceptance repeated across items (one task others wait on, or
   the epic acceptance), entries without a deliberate priority (rank under
   [Priority](#priority)), user stops stated in comments or deferral reasons
   (convert those in force under [Dependencies](#dependencies) or
   [Deferrals and environment facts](#deferrals-and-environment-facts), drop
   lifted ones) and `board bd memories` past their removal condition (to the
   user). Classify every doc under `docs/` as current owner, proposal (to
   the board) or history (to `history/`). Include untracked files and
   record each source's hash. Where a board exists, save one
   `board bd export` as `board-baseline.jsonl` in the plan's directory (step
   2) and derive every board mapping from it. Delegate sweeps of large
   sources by range.
   Output: sources with counts of live entries by kind and hashes; the
   baseline path; deviations by class.
2. **Gap plan.** Triage live items first: list moot ones for closing with
   their reason. Map every remaining entry and deviation to its target owner or
   to history, with source path or id. Write it to
   `.scratch/<topic-slug>/<arc-slug>/board-migrate-plan.md`, with the rule
   findings and the order of changes. Write every command with its full text
   into one change-set file beside it. Have an independent `verify`
   sample retained, archived and merged entries and each class of generated
   text in the change set.
   Output: plan path, mapping counts per source, rule findings.
3. **Confirm.** Show the plan summary, counts and rule findings; the user's
   confirmation authorizes every step below, including retiring trackers.
   Output: the user's confirmation, quoted.
4. **Apply.** Before the first write, ask the user to pause sessions that
   write the board or the sources; re-check every source hash and diff a
   fresh `board bd export` against `board-baseline.jsonl` (no board: hashes
   only), and stop on drift. Report when the paused
   sessions may resume. Set up beads under the included setup when `.beads/`
   is absent.
   Apply only from the change set, directly, or for large boards through
   outcome-sized tasks under Cut work in
   `$HOME/.agents/skills/role/protocols/plan.md`. Mechanical fixes (edge
   kinds, types, holders, prefixes) write no comments. Write each rule into
   its owner.
   Output: one line per applied part; each moot close with its reason.
5. **Reconcile.** Compare counts per source with the target and history; read
   back mapped dependencies (`board bd dep list <id>`); run `board check --all`
   until it reports no deviation (flags are reported, not required clean);
   resolve every gap.
   Output: reconciliation table.
6. **Retire.** With counts reconciled, `git mv` replaced trackers to
   `history/` with a one-line banner naming their new owner; replace migrated
   backlog sections with the board view that lists them; update project
   instructions and docs that named the retired trackers. Write the position
   into the checkpoint file under project-memory Arc state.
   Output: moved files, final counts, epic ids.

## Stop

- Counts don't reconcile or `board check` still reports deviations: stop
  before Retire and report the gap.
- A rule lacks an owner the user accepts: keep its source in place and report
  it.
- A source can't be classified as live or history: list it in the plan as a
  question for the user.

## Exit

The target holds every live entry, history holds the rest, counts reconcile,
replaced trackers sit in `history/`, and sessions are told to enter with
`/role`.

## Tool facts (bd 1.3.1)

- Comments are permanent (no edit or delete). Read them as JSON with
  `board show <id> --json --field comments`.
- Merge duplicates after import: `board bd duplicate <dup> --of <keeper>`.
- `board bd import --dry-run <file>` first; it must report every issue as new,
  otherwise choose other ids. On retry, import only missing entries.
- Import skips a dependency whose target is missing and still succeeds:
  resolve every `Skipped dependency` it reports.
- Import file uses the `board bd export` schema (`board bd import --help`); an omitted
  `priority` means P0; labels are not inherited from epics; set
  `external_ref` to the old id and `source_system` to the source file; add
  `parent-child` dependencies explicitly.
- Temporary environment facts import as memory rows
  `{"_type":"memory","key":…,"value":…}`.

## Shared conventions

<!-- @include shared/beads-setup.md -->

<!-- @include shared/board-core.md -->

<!-- @include shared/board-coordination.md -->
