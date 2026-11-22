---
name: board-migrate
description: >-
  Bring a project onto the current model: trackers and TODO/REVIEW files onto
  the board, an older board to change requests, live design checkpoints to
  ordinary design change requests, in-repo `.scratch` folders out of the
  repository.
argument-hint: "[project or arc] [focus, e.g. scratch]"
disable-model-invocation: true
---

# Board migrate

Migrate the project or arc the user names; derive the work from the gap
between what exists and the target. Give each step's output compactly; detail
only findings and stops.

## Start

Parts: **Tracker** (Target through Exit), [Upgrade](#upgrade),
[Checkpoints](#checkpoints) and [Scratch](#scratch).

1. **Scan.** Read-only, a few commands:
   - trackers: `TODO.md`, `REVIEW.md`, Markdown boards, `docs/` backlogs;
   - board: `.beads/`, `agents board check --limit 0` classes with counts, `board
     holders`, stored settings (`agents board bd config list`), live change
     requests with `checkpoint` metadata or an open design ratification;
   - scratch: in-repo `.scratch` folders (count, size);
   - dirty main-tree paths.
   Output: one line per part: open work found, done, or not applicable.
2. **Ask.** One dialog: a question per part with open work, with its scan
   line and a recommendation (the argument's focus recommended), plus each
   finding that changes a part's scope (an unclassifiable file, a running
   hold). Run only the picked parts, in the order Tracker, Upgrade, Checkpoints,
   Scratch.
   Output: the picks, quoted.

## Target

- Board model: read `$HOME/.agents/skills/shared/board-core.md` and
  `$HOME/.agents/skills/shared/board-coordination.md` unless their text is
  already in your context.
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
  closed); fix wrong edges touching a live item, on either end. Write a rule
  still in force that lives only in a closed record into its owner and link the
  record; never edit it. Add missing
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
  source or exceed it stays released, with a non-blocking question
  "Ratify or revise the flagged rules of <id>?" naming the finding. Ask the user only migration-scope choices.
- **One owner.** Write each rule into its owner under project-memory
  [Durable owners](../shared/project-memory.md#durable-owners); the board
  keeps the decision record. Epic text holds no rules, status or history.
- **Plain text.** Write board text in plain sentences; rewrite shorthand or
  squashed text of live entries when migrating them. Leave decision records
  past decision time as written; Live or history and text rewrites skip them.
  State missing provenance, dates and reasons as "not recorded".

## Tracker

1. **Discover.**
   - Where a board exists, run `agents board check --limit 0` for its mechanical
     deviations and flags, and save one `agents board bd export` as
     `board-baseline.jsonl` in the plan's directory (step 2); derive every
     board mapping from it.
   - Inventory what it can't see: backlog and review files, Markdown boards,
     lead notes, checkpoint files; project instructions and docs that name
     trackers as owners (file roles, backlog pointers); epic texts holding
     rules, status or history; rules without an owner (including rules in
     force that live only in closed records); acceptance repeated across
     items (one task others wait on, or the epic acceptance); entries without
     a deliberate priority (rank under [Priority](../shared/board-core.md#priority)); user stops
     stated in comments or deferral reasons (convert those in force under
     [Dependencies](../shared/board-core.md#dependencies) or
     [Deferrals and environment facts](../shared/board-coordination.md#deferrals-and-environment-facts),
     drop lifted ones); `agents board bd memories` past their removal condition (to
     the user).
   - Classify every doc under `docs/` as current owner, proposal (to the
     board) or history (to `history/`).
   - Include untracked files and record each source's hash. Delegate sweeps
     of large sources by range.
   Output: sources with counts of live entries by kind and hashes; the
   baseline path; deviations by class.
2. **Gap plan.** Triage live items first: list moot ones for closing with
   their reason. Map every remaining entry and deviation to its target owner or
   to history, with source path or id; backlog work not yet due becomes a
   deferred item, never a new CR. Write it to
   `board-migrate-plan.md` in `agents scratch dir --shared board-migrate`, with the rule
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
   fresh `agents board bd export` against `board-baseline.jsonl` (no board: hashes
   only), and stop on drift; report when they may resume. Run `agents board setup`, which creates or
   updates the board, and act on the exclude lines it reports
   (`$HOME/.agents/skills/shared/beads-setup.md`).
   Apply only from the change set, directly, or for large boards through
   outcome-sized tasks under Cut work in
   `$HOME/.agents/skills/role/protocols/plan.md`. Mechanical fixes (edge
   kinds, types, holders, prefixes) write no comments. Write each rule into
   its owner.
   Output: one line per applied part; each moot close with its reason.
5. **Reconcile.** Compare counts per source with the target and history; read
   back mapped dependencies (`agents board bd dep list <id>`); run `agents board check --fix --limit 0`
   until it reports no deviation (flags are reported, not required clean);
   resolve every gap.
   Output: reconciliation table.
6. **Retire.** With counts reconciled, `git mv` replaced trackers to
   `history/` with a one-line banner naming their new owner; replace migrated
   backlog sections with the board view that lists them; update project
   instructions and docs that named the retired trackers.
   Output: moved files, final counts, epic ids.

## Stop

- Counts don't reconcile or `agents board check` still reports deviations: stop
  before Retire and report the gap.
- A rule lacks an owner the user accepts: keep its source in place and report
  it.
- A source can't be classified as live or history: list it in the plan as a
  question for the user.

## Exit

The target holds every live entry, history holds the rest, counts reconcile,
replaced trackers sit in `history/`, and sessions are told to enter with
`/role`.

## Upgrade

Per project (model:
[Change requests](../shared/change-requests.md#change-requests)); every git
step goes in a change set and runs on the user's confirmation.

1. **Inspect.** `agents board check --limit 0`, `agents board holders`, items in review, dirty
   main-tree paths. A project whose tests share one database needs
   per-checkout test databases landed first.
   Output: holds by holder, in-review items, dirty path count.
2. **Drain.** The user stops starting pull sessions; holds and agent reviews
   of in-review tasks finish (`agents board mine` per session); after the board
   switched, such a review closes as a standalone review (review.md step 7).
   Stop no holder. Designs waiting for the user's
   accept stay; step 5 wraps them. Holds left from before the board switched
   (no drain first) cannot hand over: their edits stay in the main tree for
   the start, their holders `agents board unclaim` them, and planning cuts them into
   CRs with the rest.
   Output: `no holds`, or the holders still working.
3. **Start.** The user finishes and commits the main tree; that commit is the
   start (no baseline CR); a red project needs no green first.
   Output: the start commit.
4. **Settings.** Add the project's setup and check scripts under
   [Change requests](../shared/change-requests.md#change-requests) Settings,
   then `agents board setup --target … --setup … --checks … --look … --view …`
   (`look` and `view`: ask the user). Make each tool that
   scans from the repository root skip `.worktrees/`. A git commit hook that
   runs the same checks: ask the user whether agents commit with
   `--no-verify` or the hook skips `.worktrees/` (the board's checks cover
   both, user review edits included), and record the answer in the project's
   agent docs.
   Output: the settings as stored; the hook answer.
5. **Reconcile.** Wrap each design still waiting for the user's accept in a
   CR under its topic: the design its child, its text in the topic document
   on the CR's branch for ordinary review. `agents board check --fix --limit 0` clean but for user-accepted
   deviations; one `agents board claim` of a CR works end to end. Defer each open
   backlog work item; a plan pass groups the rest into CRs as they become due.
   For live legacy decisions at `needs_ratification`, run
   `python3 "$HOME/.agents/skills/board-migrate/scripts/convert-unratified-rulings.py"`,
   follow its output, then rerun the check.
   Tell the user pulls may start.
   Output: check result.

## Checkpoints

Per board, after the owner installs the runtime without design checkpoints
and restarts its sessions (design: `docs/board/ordinary-design-requests.md`,
Existing records and rollout). The script runs from the project checkout:
`python3 "$HOME/.agents/skills/board-migrate/scripts/convert-design-checkpoints.py"`.
It writes only through `agents board return`, `block`, `unblock`, `link` and
raw bd writes for the checkpoint marker and returned design items; everything
else it lists as a manual step.

1. **Inventory.** `convert-design-checkpoints.py inventory --mapping <file>`
   (read-only; the file goes in `agents scratch dir --shared board-migrate`).
   One row per live checkpoint, passed design and design ratification: status,
   holder, tip, design items, body source, the transition from the spec table,
   hold reasons, dependent edges with direction, manual steps; and each wait the
   old runtime counted as met (on a closed design inside an unlanded CR), which
   `apply` turns into `relates-to`.
   Output: the rows; the draft mapping path.
2. **Approve.** Show the owner the rows, the manual steps and each `hold`; the
   owner approves the mapping, an `agents board bd export` backup and any live
   review exits, and has writers paused. A scratch
   reference or a missing provenance line alone approves no text: bring each
   to the owner. The owner sets `approved_by` in the mapping and removes or
   edits rows.
   Output: the owner's approval, quoted.
3. **Resolve holds.** Per reason, in a lead or solo session: end a review or
   hold through its workflow, record the user's edits, resolve each design
   ratification with `agents board ratify`, then rerun step 1 and re-approve
   the changed rows. Block work behind missing bodies on a question to the
   owner.
4. **Convert.** `convert-design-checkpoints.py apply <mapping>` (dry run), then
   with `--apply`. It rechecks every row's status, holder, tip and waits before
   the first write and again before each write, stops at any divergence, and
   skips what is done: rerun it after an interruption. Return a changed
   record to step 1.
5. **Manual steps.** Do each listed step through its owner: place the design
   text in the topic document on the branch (compare it with the reviewed
   range), a documentation CR for a passed design without a doc owner, move
   implementation items into a dependent CR, add waits for held waiters.
6. **Verify.** `convert-design-checkpoints.py verify` exits 0 only with no
   live checkpoint metadata, design ratification or met design wait left; then
   writers resume. Keep the backup until the board's next ordinary landing.
   Output: the verify result.

## Scratch

Scripts: `$HOME/.agents/skills/board-migrate/scripts/`; save each output as a
log in `agents scratch dir`.

1. **Records.** Ask the user to pause every session of the repository.
   `python3 <scripts>/move-scratch-records.py`; show the user its dry run,
   then rerun with `--apply` (the records log). Show the user each skipped
   record that differs from the file at its target.
   Output: moved and skipped counts.
2. **Migrate.** `agents scratch migrate` (the migrate log); resolve
   each skipped or broken-link line: loose files go to `shared/loose`; a name
   clash goes to `shared/<name>-<folder that held the .scratch>` (`base/.scratch/orm`
   becomes `shared/orm-base`); anything else goes to the user. Show the user
   what it trashed and restore what they name (move a restored folder a live
   item cites into `items/<id>` only if they ask).
   Output: moved, skipped and trashed counts.
3. **Paths.** `python3 <scripts>/rewrite-scratch-paths.py --moves <records
   log> --moves <migrate log>`; show the user its dry run with the `missing`
   and `unmapped` lines, restore or decide each before rerunning with
   `--apply`; rewrite each `ambiguous` path by hand to the one its item means.
   Tell the user sessions may resume.
   Output: rewritten item and memory counts, the paths rewritten by hand.

## Tool facts (bd 1.3.1)

- Comments are permanent (no edit or delete). Read them as JSON with
  `agents board show <id> --json --field comments`.
- Merge duplicates after import: `agents board bd --raw --yes duplicate <dup> --of <keeper>`.
- `agents board bd --raw --yes import --dry-run <file>` first; it must report every issue as new,
  otherwise choose other ids. On retry, import only missing entries.
- Import skips a dependency whose target is missing and still succeeds:
  resolve every `Skipped dependency` it reports.
- Import file uses the `agents board bd export` schema (`agents board bd import --help`); an
  omitted `priority` means P0; labels are not inherited from epics; set
  `external_ref` to the old id and `source_system` to the source file; add
  `parent-child` dependencies explicitly.
- Temporary environment facts import as memory rows
  `{"_type":"memory","key":…,"value":…}`.

