## Board core (beads)

**Commands:** run the board as `agents board <verb>`, never bare `bd`.
`agents board help [<verb>]` lists every verb. Board
verbs own every write. `agents board bd <args>` runs bd with `--readonly`: reads pass
and bd refuses a write, naming the board command (it does not catch every
write: `import`, `rename`, `config set` and `dolt remote add` pass on a server
board). **Raw bd writes only when no board command does it, or the user
authorized it:** `agents board bd --raw --yes <args>` (`--raw` alone prints this rule
and runs nothing). When board output stops early, run the command it prints
before relying on the missing part.

The model's tables (statuses, outcomes, transitions, authority) print from the
code: `agents board help` lists statuses and outcomes by type, and a verb's
`--help` lists its rows (types, from and to, who, outcomes); a refusal names
its rule.

**Codex sandbox:** run every `board` command with elevated sandbox permissions.

**Content:** make each item complete without its linked files.

- Keep the work content in the item: what to do, packets, designs, findings,
  evidence summaries, verdicts, block reasons. Reference rulings, rule owners
  and items by id and anchor instead of restating their text.
- Keep working drafts and data files in the item's scratch folder
  (`agents scratch dir --for <id>`); move a draft's result
  into the item before hand-over or closure.
- Name each data file the work consumes or produces (dumps, diagnostics, logs,
  fixtures, generated output) in the item with path, size or hash, and how to
  obtain it: the regenerating command and commit, or its location and
  holder.

Without `.beads/`: a project with existing trackers or backlog files moves onto
the board through `/board-migrate`; otherwise run `agents board setup` with the user's confirmation
(`$HOME/.agents/skills/shared/beads-setup.md`). Leave `bd setup` unrun. Share or join a board only on the user's request
([Shared boards](../shared/beads-setup.md#shared-boards)); `board` syncs a
shared board, the user an unshared one (`bd dolt push`/`pull`).

### Actors and holds

- **Actor:** the last 8 characters of the session id; a worker's actor is
  `<session actor>/<last 8 of its agent id>`. `board` derives it; Claude
  workers get theirs from bd-guard.
- **Hold:** the holder field, set by claim and never by status. Holdable: a
  [change request](../shared/change-requests.md#change-requests) (CR), a task,
  a decision and a milestone. A session holds a whole CR; an item has no holder of its
  own, so the holder's session and its workers close its items (`agents board
  close <item> --reason "<what>"`); nothing is assigned to the user (a user
  step is a human gate, [Dependencies](#dependencies)).
- Claim with `agents board claim` (the next CR, task or question routed to your
  session under [Routing](#routing)) or `agents board claim <ids>` (named).
  Claiming a named record held within your own session takes it over.
- Finish, hand over or unclaim each hold you still have. Hand back unfinished
  work with `agents board unclaim <id> --resume "<next action>"`; work that
  waits on something is a wait first (`agents board wait`).
- Free another session's hold only with `agents board take <id>` or
  `agents board unclaim <id>`: the user, or a [deciding session](../role/SKILL.md#roles)
  once the holder is gone (`agents board position` or the claim report marks
  it; `--agreed "<the user's words>"` when it only looks live). For your own
  workers' holds marked stopped in `agents board mine`: continue the worker,
  hand the item over or free it.
- At your worker cap, hand over or unclaim partial work before
  `agents board claim <id> --force "<reason>"`.
- A CR that leaves its holder unfinished (unclaimed, returned, freed from a
  gone holder) keeps its worktree, branch and uncommitted edits; its next
  claimer reuses the worktree as it stands. Git states stopping a CR:
  [Change requests](change-requests.md) Rebase.

### Kinds

| Type | Kind |
|---|---|
| `task` | A bd `task`. In a CR it is an *item*: a structured part, closed `done` or `dropped`, with no holder or review of its own. What sort it is (`kind:bug`, `kind:feature`, `kind:design`, `kind:cleanup`) is a label; no rule reads it. Outside a CR it is a standalone task: work that commits nothing, marked no-commit ([Work items](#work-items)). |
| `decision` | Question, later the ruling's record ([Questions and rulings](#questions-and-rulings)). |
| `change-request` | The claimed, reviewed and landed unit ([Change requests](../shared/change-requests.md#change-requests)). |
| `milestone` | A goal the user accepts; CRs are parts of it ([Milestones](../shared/board-coordination.md#milestones)). |
| `gate` | A step only a person takes, human only ([Dependencies](#dependencies)). |

Titles carry no prefixes; use only these types (a check others wait on is a
task, [Work items](#work-items)). Topics are labels and a review belongs to its
CR; a challenge is a question, its review the no-commit task it waits on ([Challenge](../role/protocols/review.md#challenge)).

### Routing

A bare `agents board claim` takes the unheld, ready CRs, tasks and questions
routed to the session's role or pulls (`agents board position` counts them). A
claim by id checks no pull; follow these rules yourself:

- CRs by pull: `open` to `implement`; `in_review` to `review`; refresh work to
  `review`, kind `refresh` ([queue](../shared/board-coordination.md#change-request-queue)).
- Items are never claimed: claim their CR. Work that commits belongs to a CR;
  a task outside a CR is no-commit and is claimed as such.
- Pull `plan` also claims in-force rulings, the board restructuring tasks it
  creates itself, ready no-commit tasks, and an `open` CR marked `plan_first` (needs planning before work: a
  child of a rejected CR, or migrated loose work). An open CR without open items is `implement` work: its holder hands it over.
- A deciding session (lead, solo; autopilot takes questions only) claims by id
  its round's open decisions, `passed` CRs of `look` `before` waiting for the
  user's Accept, `passed` `look` `after` children marked `after <base>` and
  ready milestones.

Questions, autopilot's parked ones included, stay unheld until a session
claims them.

On a shared board (`.beads/board-shared.json` exists):

- **Queue:** each item's person is its `queue:<person>` label, else its nearest
  ancestor's (none, or parents in different queues: unrouted); a new item
  takes its parent's queue, else its creator's. Your person: `git config
  agents.person`. Claims take only your queue's items.
- **Moves:** only lead and solo sessions and a person's terminal move items
  (`agents board route <person> <ids…>`, `agents board send <person> <ids…>` into their
  inbox); others ask a deciding session. File a find for another person with
  `agents board create --for <person>`; decide.md Inbox routes it.
- **Sync:** run the fix a `board: sync …` line names; other work continues
  unless beads refuses the write.
- Raw bd never creates with `--id` or dotted child ids: parent.N ids stop sync.

### Work items

- Cut one item per outcome a dependent could need, sized for one worker pass.
  Keep parts that must land together in one item (atomic rename, contract plus
  its only caller). Move a part with a different wait or dependent to its own
  CR (`agents board move <item> --to <cr>`; planning decides); items do not
  split inside a CR. Cut a check others wait on (whole typecheck, fresh
  build), or other work that by design commits nothing to this repository, as
  a task marked no-commit (`create --no-commit` or a graph node's
  `"no_commit": true`). It sits outside any CR, runs against the target, and
  its acceptance is the recorded passing run; a defect it finds becomes a code
  item in a CR.
- Fields: description (outcome and reason), design (contract, files,
  checks, ruling ids with owner anchors), acceptance (done criteria),
  `spec_id` (specification reference; a key of a `create --graph` node, set
  at creation), waits.
- Keep every field of every item (description, design, acceptance,
  `notes`) at its current state. Change fields with `agents board field export <id>…
  [--field F]…`, edit the files in place, `agents board field apply <id>…` (one update
  per item; `discard` drops an export); never rewrite a field from memory. Comments hold only one-line events (a failed attempt is one line);
  history lives in `agents board bd history`.
- Before creating an item or question, search with
  `agents board related --like <draft>` (or `agents board related <terms>`); extend an open
  item on the same decision, files or migration instead.
- Create items with one `agents board create --graph <plan.json>` per wave (a single item: `agents board create <title> --parent <cr> --description-file …`). Let Beads
  generate every id; confirm creation before creating dependents. A found
  record carries `--found-in <id>`.
- When an open item becomes redundant, move its leftover work into the owning
  item's `--acceptance`, then `agents board bd --raw --yes supersede <id> --with <owner>`, or
  `agents board bd --raw --yes duplicate <id> --of <canonical>` for an exact duplicate (no board command does either); close it `dropped`.

### Questions and rulings

| Status | Question state |
|---|---|
| `open` | A question: unanswered. It can wait and be waited on. |
| `decided` | Answered, release pending. A wait on it stays unmet. |
| `in_force` (shown "in force") | Binding. The open items it changes wait on it until a `plan` session plans it and closes it. It waits only for its own planning: a live decision or a human gate. |
| closed | `planned` (carried into work), `superseded` (a later ruling replaces it) or `dropped` (never ruled). A reversal is a revision record (`agents board ruling revise <id>`, [Rulings](../shared/board-coordination.md#rulings)). A wait on a question is met when it closes. |

- Withdraw a question the user drops with
  `agents board close <id> --reason "withdrawn: <why>"`, quoting the user.
- In role `agent`, put every user-facing question in Beads, including
  clarifications, blockers and approvals a governing rule reserves for the
  user; quote that rule in an approval question. Reuse the existing question
  or create one; report its id and status in chat. Never ask the user in the
  agent session or through a question tool; deciding sessions handle user
  rounds.
- One decision per record. While open, the description holds the
  [Decision packet](#decision-packet).
- Name the affected items (a whole CR only when all of it waits), when creating a question or
  ruling; create missing items first. Pass the affected ids with
  `--holds <ids>` (shorthand for blocking links, on `agents board create --type decision` and `agents board ruling
  revise`; a plan's links from its decision node; in a round, the question's
  `holds`, which Record passes) or `--holds none`. Make a question wait on each
  open question its options assume (`agents board wait <id> --on <other>`; `--for` is optional there).
- Implementation steps, file lists and test lists become work items, never
  ruling text.
- Answer provenance questions from the record (`agents board show`,
  `agents board bd history <id> --events`).
- Deciding and planning sessions record rulings under
  [Rulings](../shared/board-coordination.md#rulings).

### Decision packet

Use these `##` sections:

| Section | Content |
|---|---|
| Question | Exact choice. |
| Consumer scenarios | The simple case and each realistic case where the options' outcomes differ, with who hits it. |
| Root cause and end state | Decision protocol's Root fix and End state, designed fresh, with its consumer code. |
| Prior rulings (evidence) | Rulings, rules, docs and pending approvals touching the question: owner, and whether the end state keeps or revises each ([Others' input](../shared/decision-protocol.md#others-input)); options a missing approval blocks stay in the set. |
| Premises and evidence | Each premise with `path:line` or executed results, or the question that asks it; limits. |
| Options | Decisive trade-offs, always including the end-state option and the prior rulings it revises; use `architect` or `option-explorer` for consequential choices or open option spaces. |
| Recommendation | Recommended option and conditions changing it. |

### Statuses and labels

Statuses carry the lifecycle and the holder field carries who works it;
labels only classify (`topic:<topic-slug>`, `kind:<kind>`, `export:<capability>`,
`provides:<capability>`, `for:<person>`, `queue:<person>`). A status is never a
label. The statuses, outcomes and transitions by type print from `agents board
help` and each verb's `--help`; `deferred` is [Deferral](../shared/board-coordination.md#deferrals-and-environment-facts).
Closing records its outcome: the type's first by default; `close --outcome`
takes only `done` or `dropped`, the others come from their verbs (land and
`cr reject`; `ruling release --closes` and `ruling supersede` write `superseded`;
a plain close of a ruling writes `planned`, of a milestone `accepted`; `gate
resolve`). `ruling record` closes nothing and writes no outcome.

### Dependencies

One relation: a wait, written on the waiter with what it uses (`agents board
wait <waiter> --on <target> --for "<input>"`; a plan node's `waits_on`);
`agents board unlink <a> <b>` removes it. The board refuses a cycle and a
deferred target. Put a wanted order in priority and wanted evidence in
acceptance, never in a wait; when only part of B uses A, split B
([Work items](#work-items)). Use the first matching row.

| Relation | Use |
|---|---|
| B uses A's output (an artifact, contract, decision or environment) or changes code A changes, or released ruling A changes B | `agents board wait B --on A --for "<the input B uses>"`. Waiter: an item, a whole CR (every item, present and future), a task or a question; a milestone waits on nothing. An outside wait goes on B's CR ([Waiting and stacks](change-requests.md#change-requests)). |
| B is part of outcome A | `--parent A` (an item of a CR; `agents board move <cr> --to <milestone>` for a milestone's CR) |
| B found while working on A | `--found-in A` at creation |
| Shared context, alternatives, a ruling's context-only item | `agents board link A B --type relates-to` |
| B revises ruling A | `agents board ruling revise A` links B at creation; release supersedes A ([Rulings](../shared/board-coordination.md#rulings)) |
| B waits on the user's go or another person's step (no open decision) | A human gate, on the user's instruction only; raise your own caution as a question. `agents board gate create --blocks B --reason "<why>" --title "<what, when>"`; more items: `agents board wait <item> --on <gate>`; lift on the user's word or a covering released ruling: `agents board gate resolve <gate>`. |
| External wait on another project's delivery | gate; read `$HOME/.agents/skills/shared/upstream-waits.md` first |

### Hand-over and acceptance

1. Scope a CR's acceptance under Acceptance [Evidence and gates](../shared/acceptance.md#evidence-and-gates)
   (`$HOME/.agents/skills/shared/acceptance.md#evidence-and-gates`).
2. Keep the current state of active work in `notes` (resume point, what it
   waits on; edit fields as under [Work items](#work-items)). Hand over only
   with complete evidence for the CR's acceptance and every item closed
   (handover refuses open items and never closes them). An item that starts
   waiting: `agents board wait <item> --on <blocker> --for "<input>"`, then
   unclaim the CR (`--resume "<next action>"`) or ask the planner to move the item into its own CR.
3. Hand over: `agents board handover <cr> "<evidence>"` ([Change requests](../shared/change-requests.md#change-requests)).
4. The reviewer passes with `agents board handover <cr> "<verdict>"` or returns it
   with `agents board return <cr> "<findings>"` (each finding becomes an open
   item). The user's Accept is a deciding session's
   [Accept](../role/protocols/decide.md#accept).
5. A hold leaves the review stage in place. Apply
   [Released rulings](../role/protocols/plan.md#released-rulings) when a ruling
   changes a CR in review.

### Priority

- Rank each item by how much existing or committed work will build on its
  structure, API or conventions, including work it does not block.
- Count only items on the board or work committed in the goal or contract;
  hypothetical future work counts zero.
- Set priority per item at creation (`-p`) and when its impact changes. Give
  greater impact a higher priority (lower number). A CR's priority orders it;
  its items do not inherit it.
- Rank a milestone and a topic's decision clusters by the same measure applied
  to the outcome.
- Use P0, the highest priority, for a broken shared build/environment, data loss
  or a live security hole; running work continues. Use `deferred` for backlog;
  leave P4 unused.
- Inspect what an item holds up with `agents board bd dep tree <id> --direction=up` or
  `agents board holders`; include committed nonblocking consumers
  when ranking it.

### Views

`agents board check` lists deviations from these conventions on live
items; a board with deviations moves through
`/board-migrate`.

Other queries: `agents board bd query`, `search`, `blocked`, `lint`, `dep tree`; the
decision log, `agents board bd list --type decision --all --label topic:<slug>`; the
topic backlog, `agents board bd list --status deferred --label topic:<slug>`; before
dispatch, `agents board bd dep cycles`.

### Limits

- Under Codex, every commit in a CR worktree needs elevation too (`.git` is
  read-only in its sandbox).
- On an embedded board, run `board` commands one at a time and never
  interrupt a running one.
- `agents board bd ready` returns 100 rows; use `--limit 0` for inventories. Read
  inventories with one `agents board bd export` or
  `agents board bd list --all --limit 0 --json` instead of per-item `agents board show`.
