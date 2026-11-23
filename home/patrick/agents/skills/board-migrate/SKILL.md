---
name: board-migrate
description: >-
  Bring a project onto the current model: an older board's stored forms and its
  model marker, trackers and TODO/REVIEW files onto the board, an older board to
  change requests, live design checkpoints to ordinary design change requests,
  in-repo `.scratch` folders out of the repository.
argument-hint: "[project or arc] [focus, e.g. scratch]"
disable-model-invocation: true
---

# Board migrate

Migrate the project or arc the user names; derive the work from the gap
between what exists and the target. Give each step's output compactly; detail
only findings and stops.

## Start

Parts: [Model](#model), **Tracker** (Target through Exit), [Upgrade](#upgrade),
[Checkpoints](#checkpoints) and [Scratch](#scratch).

1. **Scan.** Read-only, a few commands:
   - trackers: `TODO.md`, `REVIEW.md`, Markdown boards, `docs/` backlogs;
   - board: `.beads/`, the model marker (`agents board bd config get
     custom.board.model`: `1`, else Model is open), `agents board check --limit 0`
     classes with counts, `board holders`, stored settings (`agents board bd
     config list`), live change requests with `checkpoint` metadata or an open
     design ratification;
   - scratch: in-repo `.scratch` folders (count, size);
   - dirty main-tree paths.
   Output: one line per part: open work found, done, or not applicable.
2. **Ask.** One dialog: a question per part with open work, with its scan
   line and a recommendation (the argument's focus recommended), plus each
   finding that changes a part's scope (an unclassifiable file, a running
   hold). Run only the picked parts, in the order Model, Tracker, Upgrade,
   Checkpoints, Scratch; a board without the marker refuses every board write
   verb, so Model comes first and its pick is not optional.
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
  closed); fix wrong edges touching a live item, on either end. The one write
  on a closed record is the `outcome` field of a closed decision, gate or
  milestone (Model). Write a rule
  still in force that lives only in a closed record into its owner and link the
  record; never edit it. Add missing
  `supersedes` edges on closed rulings when a release check meets them, not
  as a sweep.
- **Triage before migrating.** Close a live item whose outcome is moot
  (superseded, done elsewhere, no longer wanted) with that reason instead of
  migrating it. Candidates: a superseded linked ruling, an in-force ruling
  whose linked work is all closed, duplicates.
- **Open findings are questions.** A finding needing a decision (possible
  supersession, conflicting rulings) becomes a question blocking the affected
  items; reports list its id.
- **Nothing lost.** Reconcile counts per source with what the target holds
  plus what history holds.
- **Rules have a user source.** Trace every standing rule and constraint to a
  user source (goal, instructions, decision record). Route findings to the
  deciding session uninvestigated: an in-force record whose rules lack a user
  source or exceed it stays in force, with a non-blocking question
  "Ratify or revise the flagged rules of <id>?" naming the finding. Ask the user only migration-scope choices.
- **One owner.** Write each rule into its owner under project-memory
  [Durable owners](../shared/project-memory.md#durable-owners); the board
  keeps the decision record. A milestone's text holds no rules, status or history.
- **Plain text.** Write board text in plain sentences; rewrite shorthand or
  squashed text of live entries when migrating them. Leave decision records
  past decision time as written; Live or history and text rewrites skip them.
  State missing provenance, dates and reasons as "not recorded".

## Model

Per board, first whenever the marker (`custom.board.model`) is not `1`: every
board write verb refuses such a board, naming this skill; reads, `agents board
setup`, `agents board check` and `agents board bd --raw` still work. Scripts:
`$HOME/.agents/skills/board-migrate/scripts/`, run from the project checkout.
`convert-stored-forms.py` writes only through raw bd and ends with the marker,
which `agents board setup` writes on a board it creates and never on an existing
one.

1. **Inspect.** The user pauses every session that writes the board. Run
   `agents board check --limit 0` and `agents board holders`; save one
   `agents board bd export` as `board-baseline.jsonl` in `agents scratch dir
   --shared board-migrate`.
   Output: deviation classes with counts, holds, the baseline path.
2. **Setup.** `agents board setup` brings the settings and the status list to
   the current model (decided, in_force, in_review, passed).
   Output: the settings it changed.
3. **Preview.** To see the whole outcome first, run `python3 -u
   <scripts>/convert-stored-forms.py --rehearse` (a large board takes many
   minutes): it imports this board's export into a temporary board and takes
   the copy through steps 2 to 6 below as a person works them (setup, the
   conversion, the checkpoint conversion, `check`, the mark). It prints a summary first (conversions per kind, deviations
   per class, what blocks the mark, the `for the user:` lines), then each
   step's log. This board is only read. The copy has the branches this
   checkout has for live change requests, and a worktree for each that has one. Then
   `python3 <scripts>/convert-stored-forms.py` is a dry run on this board: one
   `would:` line per conversion, then the `for the user:` lines. Conversions:
   - statuses: `in_progress` open (a held change request keeps its holder, its
     hold is work), `needs_acceptance` passed with look before (a project that
     looks after would otherwise land it unasked), standalone `in_review` open,
     `released` in_force, a ruling at `needs_ratification` in_force with a
     question to confirm or revise it;
   - holds on items cleared (one held by the user is listed); legacy holders
     cleared; a deferred item of a deferred change request is open (the
     deferral holds it), a deferred item of a live one leaves it as the only
     item of a deferred change request of its own, `relates-to` the old one;
   - a work item outside any change request (not no-commit, deferred or
     waiting on a question) becomes the only item of a change request of its
     own, marked `plan_first` with its reason, listed for planning;
   - retired metadata (`no_code` becomes `no_commit` on work items,
     `triaged_tip` and `triaged_base_tip` are dropped, `replan` becomes
     `plan_first` with the same reason);
   - types bug, design, feature, chore (kind `cleanup`) and spike become
     `task`, with a `kind:` label except for spike;
   - an in-review change request gets its `author` from the hand-over comment,
     else bd's status history, else its holder;
   - links: `waits-for` and `conditional-blocks` become waits, with a comment
     naming the earlier link (reason not recorded), `discovered-from` the
     `found_in` field, `related` `relates-to`, a milestone's wait on a change
     request that change request's membership;
   - `defer_until` becomes the `revisit` day and leaves bd; a deferral whose
     reason names a condition (after, until, when, once, waits on, blocked by)
     and an open record becomes a wait on it, the record open;
   - closed decisions get `superseded` (a supersedes link), `planned` (the
     close reason starts "planned in") or `dropped`; closed gates `resolved`,
     closed milestones `accepted`; an open record carries no outcome;
   - an in-force ruling's waits on work (designs, spikes) become `relates-to`
     links, and the rulings are listed for planning, which makes the work wait
     on the design;
   - an open epic's children get its topic label and the epic closes;
   - an open design or landing ratification is listed, not converted;
   - an open gate that is not a human gate, and an item assigned to the user,
     become a human gate of the same title that supersedes the old record;
     waiters move to it; on a shared board it is `for:` the board's person.
   The converter writes no interim form and marks no record it made: grouped
   writes go out as one multi-id `bd update` and one `bd batch` per phase, and
   a rerun finds a filed change request through its item's parent.
   Output: the conversion count; the listed forms.
4. **Convert.** `convert-stored-forms.py --apply`, then rerun it until it
   reports `0 conversion(s)`. An interruption needs no cleanup. On a board with
   live design checkpoints run [Checkpoints](#checkpoints) now.
   Output: the apply log.
5. **Settle.** Resolve each `for the user:` line and each deviation `agents
   board check --limit 0` reports before the mark. The board's write verbs
   refuse until the marker, so write through `agents board bd --raw --yes`.
   Ask the user where the choice is theirs:
   - a ruling taken without your judgment: answer its confirm-or-revise
     question, or leave it for the user;
   - an open design or landing ratification: for a landing, close it as
     accepted or dropped with the user's word; for a design, make an ordinary
     question (`-t decision`, sections Question and Decision) for the user, or
     close it as dropped;
   - a deferral whose condition names no open record, or a wait that became
     one: wait it on what it needs, or leave it set aside;
   - a deferred blocker (a record waiting on a deferred one): undefer the
     blocker, or drop the wait;
   - a wait that would close a cycle: drop one edge;
   - a change request in review without an author: another session reviews
     it, or the user passes it;
   - a timer or CI gate, a milestone waiting on something that is no change
     request: resolve or drop it;
   - a checkpoint hold: [Checkpoints](#checkpoints) step 3.
   The rulings the converter lists for planning stay in force, related to
   their designs.
   Output: each form's resolution; `agents board check --limit 0` reports no
   deviation.
6. **Mark.** `convert-stored-forms.py --mark` writes the marker only with
   nothing left to convert and `agents board check` clean. Tell the user sessions
   may resume.
   Output: `custom.board.model = 1`.

## Tracker

1. **Discover.**
   - Where a board exists, run `agents board check --limit 0` for its mechanical
     deviations and flags, and save one `agents board bd export` as
     `board-baseline.jsonl` in the plan's directory (step 2); derive every
     board mapping from it.
   - Inventory what it can't see: backlog and review files, Markdown boards,
     lead notes, checkpoint files; project instructions and docs that name
     trackers as owners (file roles, backlog pointers); milestone texts holding
     rules, status or history; rules without an owner (including rules in
     force that live only in closed records); acceptance repeated across
     items (one task others wait on, or the milestone acceptance); entries without
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
   back mapped dependencies (`agents board bd dep list <id>`); run `agents board check --limit 0`
   until it reports no deviation (flags are reported, not required clean);
   resolve every gap.
   Output: reconciliation table.
6. **Retire.** With counts reconciled, `git mv` replaced trackers to
   `history/` with a one-line banner naming their new owner; replace migrated
   backlog sections with the board view that lists them; update project
   instructions and docs that named the retired trackers.
   Output: moved files, final counts, milestone ids.

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
   of in-review tasks finish (`agents board mine` per session) before the board
   switches: the standalone review is retired, so one left over is converted
   to an open task, not reviewed.
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
   on the CR's branch for ordinary review. `agents board check --limit 0` clean but for user-accepted
   deviations; one `agents board claim` of a CR works end to end. Defer each open
   backlog work item; a plan pass groups the rest into CRs as they become due.
   Tell the user pulls may start.
   Output: check result.

## Checkpoints

Per board with live design checkpoints, inside [Model](#model) after its
Convert step and before its Mark step: a live checkpoint is a deviation that
holds the marker back (a design checkpoint becomes an ordinary design change request,
`agents board help` lists the rows it passes through). The script runs from the project checkout:
`python3 "$HOME/.agents/skills/board-migrate/scripts/convert-design-checkpoints.py"`.
It writes only through raw bd (a change request back to open, the wait on it,
`relates-to`, the cleared marker); everything else it lists as a manual step.

1. **Inventory.** `convert-design-checkpoints.py inventory --mapping <file>`
   (read-only; the file goes in `agents scratch dir --shared board-migrate`):
   one row per live checkpoint (a change request with `checkpoint`
   metadata) and met design wait.
   Output: the rows; the draft mapping path.
2. **Approve.** Show the owner the rows, the manual steps and each `hold`; the
   owner approves the mapping, an `agents board bd export` backup and any live
   review exits, and has writers paused. A scratch
   reference or a missing provenance line alone approves no text: bring each
   to the owner. The owner sets `approved_by` in the mapping and removes or
   edits rows.
   Output: the owner's approval, quoted.
3. **Resolve holds.** Per reason, in a lead or solo session: end a review or
   hold through its workflow, record the user's edits, then rerun step 1 and re-approve
   the changed rows. Block work behind missing bodies on a question to the
   owner.
   Output: each hold resolved, or its question.
4. **Convert.** `convert-design-checkpoints.py apply <mapping>` (dry run), then
   with `--apply`. After an interruption, rerun it; on a divergence, return
   the record to step 1.
   Output: the apply log.
5. **Manual steps.** Do each listed step through its owner: place the design
   text in the topic document on the branch (compare it with the reviewed
   range), move
   implementation items into a dependent CR, add waits for held waiters.
   Output: each step done, or the owner it waits on.
6. **Verify.** `convert-design-checkpoints.py verify` exits 0 only with no
   live checkpoint metadata or met design wait left;
   then the owner resumes writers. Keep the backup until the owner's
   transition smoke passes.
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
  omitted `priority` means P0; labels are not inherited from parents; set
  `external_ref` to the old id and `source_system` to the source file; add
  `parent-child` dependencies explicitly.
- Temporary environment facts import as memory rows
  `{"_type":"memory","key":…,"value":…}`.

