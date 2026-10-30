## Board core (beads)

**Commands:** `board` in every skill command is `$HOME/.agents/bin/board`
(not on `PATH`): type `$HOME/.agents/bin/board show <id>`, never bare `board`
or bare `bd`. Run every other bd command as `board bd <args>`
(`board bd <command> --help`); `board help` lists every board command with an
example. Read items with `board show`; raw `board bd show` and comment
listings are refused except with `--refs`, `--children`, `--as-of` or
`--long`. When board output stops early, run the command it prints before
relying on the missing part.

**Content:** make each item complete without its linked files.

- Keep the work content in the item: what to do, packets, designs, findings,
  evidence summaries, verdicts, block reasons. Reference rulings, rule owners
  and items by id and anchor instead of restating their text.
- Keep working drafts and data files in `.scratch/`; move a draft's result
  into the item before hand-over or closure.
- Name each data file the work consumes or produces (dumps, diagnostics, logs,
  fixtures, generated output) in the item with path, size or hash, and how to
  obtain it: the regenerating command and commit, or its location and
  holder.

The session hook injects `board bd remember` facts.

Without `.beads/`: a project with existing trackers or backlog files moves onto
the board through `/board-migrate`; otherwise follow
`$HOME/.agents/skills/shared/beads-setup.md` with the user. A board in older
conventions also moves through `/board-migrate`. Agent guidance comes from
session hooks, not `bd setup`. Remote sync (`bd dolt push`/`pull`) belongs to
the user.

### Actors and holds

- **Actor:** the last 8 characters of the session id; a worker's actor is
  `<session actor>/<last 8 of its agent id>`. `board` derives it; Claude
  workers get theirs from bd-guard (their scripts act as the session).
- **Hold:** an item's assignee is the doer holding it. Each doer claims, hands
  over and closes as itself; a session owns every hold under its actor prefix.
  Only the exact assignee can close an item.
- Claim with `board claim` (the next item routed to your
  session under [Routing](#routing)) or `board claim <ids>`
  (named items). Claiming a named item held within your own session (your
  actor or one of your workers) takes it over.
- `board claim` lists the items you still hold; run
  `board mine` after compaction or resume. Finish, hand over
  or unclaim each.
- Nothing frees a hold automatically. Free another doer's hold only with
  `board take <id>` (reassign to you with a comment) or
  `board unclaim <id>`. Free another session's hold only as
  the user or a [deciding session](../role/SKILL.md#roles) once
  `board position` marks the holder gone, or you judge an idle-marked holder
  gone. For your own workers' holds marked stopped in `board mine`: continue
  the worker, hand the item over or free it.

### Kinds

| Type | Kind |
|---|---|
| `task`, `bug`, `spike` | Work item. |
| `design` | Design item: architecture, package graph and needed decisions for a slice. |
| `decision` | Question, later the ruling's record ([Questions and rulings](#questions-and-rulings)). |
| `epic` | Outcome ([Epics](../shared/board-coordination.md#epics)). |
| `milestone` | Release checkpoint ([Milestones](../shared/board-coordination.md#milestones)). |
| `gate` | Upstream wait or the user's go ([Dependencies](#dependencies)). |

Titles carry no prefixes; `feature`, `chore` and `check` stay unused (a check
others wait on is a task, [Work items](#work-items)). Review
is a status, not a kind: create a standalone review as an unassigned task
directly in review,
`board bd create … -t task --status in_review`.

### Routing

Sessions claim unassigned ready items by kind:

| Claimer | Claims |
|---|---|
| Pull `plan` | `released` decisions; board restructuring tasks it creates and claims itself. |
| Pull `design` | Open `design` items. |
| Pull `implement` | Open `task`, `bug` and `spike` items. |
| Pull `review` | `in_review` tasks, bugs and spikes, standalone reviews included; first choice while a review-pulling session is active. |
| Lead | By id: its round's open decisions, `needs_ratification` records, `in_review` design items and ready milestones; closes finished epics whose acceptance names the user. A bare `board claim` takes open decisions. |
| Solo | Open and `released` decisions, `needs_ratification` records, `in_review` design items and ready milestones itself; every other kind through one worker per item. |
| Autopilot | Open and `released` decisions and `in_review` design items itself; every other kind through one worker per item. |

Questions, autopilot's parked ones included, stay unassigned until a session
claims them.

### Work items

- Cut one item per independently landable, reviewable outcome a dependent
  could need, sized for one worker session and one review. Keep parts that must
  land together in one item (atomic rename, contract plus its only caller).
  Split parts with a different blocker or dependent. Turn umbrellas into epics.
  Cut a check others wait on (whole typecheck, fresh build) as a task; its
  acceptance is the recorded passing run. Give related small items to one
  worker together.
- Fields: description (outcome and reason), `--design` (contract, file zones,
  checks, ruling ids with owner anchors), `--acceptance` (done criteria),
  `--spec-id` (specification reference), `blocks` edges.
- Before creating an item or question, search with
  `board related --like <draft>` (or `board related <terms>`); extend an open
  item on the same decision, files or migration instead.
- Create items with one `board bd create --graph <plan.json>` per wave. Let Beads
  generate every id; confirm creation before creating dependents.
- When an open item becomes redundant, move its leftover work into the owning
  item's `--acceptance`, then `board bd supersede <id> --with <owner>`, or
  `board bd duplicate <id> --of <canonical>` for an exact duplicate.

### Questions and rulings

| Status | Question state |
|---|---|
| `open` | Unanswered and unclaimed. Blocks its dependents. |
| `in_progress` | Unanswered; claimed by the session running its round. Blocks its dependents. |
| `decided` | Answered, release pending. Still blocks. |
| `released` | Binding. Blocks the open items it changes until a `plan` session plans it and closes it; claimed before equal-priority work. |
| `needs_ratification` | Autopilot ruling in force, awaiting the user's ratification through a deciding session. Blocks nothing. |
| closed | Planned, superseded or withdrawn. |

- In role `agent`, put every user-facing question in Beads, including
  clarifications, blockers and approvals a governing rule reserves for the
  user; quote that rule in an approval question. Reuse the existing question
  or create one; report its id and status in chat. Never ask the user in the
  agent session or through a question tool; deciding sessions handle user
  rounds.
- One decision per record. While open, the description holds the
  [Decision packet](#decision-packet).
- Make the question block the items it holds up, creating missing ones, and
  depend on each open question its options assume (`board bd dep add <id> <other>`).
- Implementation steps, file lists and test lists become work items, never
  ruling text.
- Answer provenance questions from the record (`board show`,
  `board bd history <id> --events`).
- Deciding and planning sessions record rulings under
  [Rulings](../shared/board-coordination.md#rulings).

### Decision packet

Use these `##` sections:

| Section | Content |
|---|---|
| Question | Exact choice. |
| Consumer scenarios | The simple case and each realistic case where the options' outcomes differ, with who hits it. |
| Root cause and end state | Decision protocol's Root fix and End state, designed fresh, with its consumer code. |
| Prior rulings (evidence) | Rulings, rules, docs and pending approvals touching the question: owner, and whether the end state keeps or revises each. They narrow no option; options a missing approval blocks stay in the set. |
| Premises and evidence | Each premise with `path:line` or executed results, or the question that asks it; limits. |
| Options | Decisive trade-offs, always including the end-state option and the prior rulings it revises; use `architect` or `option-explorer` for consequential choices or open option spaces. |
| Recommendation | Recommended option and conditions changing it. |

### Statuses and labels

Statuses carry the lifecycle; labels only classify (`topic:<topic-slug>`,
`export:<capability>`, `provides:<capability>`).

| Status | Meaning |
|---|---|
| `open` | Available; for a question, unanswered. |
| `in_progress` | Claimed by its holder. |
| `in_review` | Handed over for acceptance ([Hand-over and acceptance](#hand-over-and-acceptance)). |
| `deferred` | [Deferral](../shared/board-coordination.md#deferrals-and-environment-facts). |

Question statuses: [Questions and rulings](#questions-and-rulings). Assign
only a task waiting on a human action to `user`; express waiting on other work
with `blocks`.

### Dependencies

Use the first matching row. Beads allows one edge kind per pair:
`board block` and `board supersede` replace an existing link; before adding
another edge by hand, remove the pair's `relates-to` edge. When order and
context coincide, keep `blocks`.

| Relation | Use |
|---|---|
| B can't start before A, including released ruling A changing B | `blocks`: `board block B --on A --reason "<why>"` ([Milestones](../shared/board-coordination.md#milestones) members: `board bd dep add`). |
| B is part of outcome A | `--parent A` |
| B found while working on A | `discovered-from`: `board bd create … --deps discovered-from:A` |
| Shared context, alternatives, a ruling's context-only item | `relates-to`: `board bd dep relate A B` |
| B revises ruling A | `board revise A` links B at creation; release supersedes A ([Rulings](../shared/board-coordination.md#rulings)) |
| B waits on the user's go (no open decision) | On the user's instruction only; raise your own caution as a question. `board bd gate create --type=human --blocks B --title "user <date>: '<words>'"`; more items: `board bd dep add <item> <gate>`; lift on the user's word or a covering released ruling: `board bd gate resolve <gate>`. |
| External wait | gate ([Upstream waits](../shared/board-coordination.md#upstream-waits)) |

### Hand-over and acceptance

1. Scope an item's acceptance under Acceptance [Evidence and gates](../shared/acceptance.md#evidence-and-gates)
   (`$HOME/.agents/skills/shared/acceptance.md#evidence-and-gates`).
2. Keep active work `in_progress` with its current resume point in `notes`
   (`board bd update <id> --notes "<point>"`), replaced as the work moves;
   record history as comments. Hand over only with complete evidence for
   the item's acceptance; keep partial work open with the remainder in
   `--acceptance`, and block waiting work on what it needs.
3. Hand over with the evidence: `board handover <id> "<evidence>"`.
4. The acceptor claims the item (`board claim <id>` prints its author), then
   closes it with the verdict as reason (`board bd close <id> --reason …`) or
   returns it to the queue, open and unassigned:
   `board return <id> "<findings>"`.
5. `board block` returns an unheld item in review to the queue when it gains
   an open blocker; amend your returned item to the blocker before handing it
   over again.

### Priority

- Rank each item by how much existing or committed work will build on its
  structure, API or conventions, including work it does not block.
- Count only items on the board or work committed in the goal or contract;
  hypothetical future work counts zero.
- Set priority per item, independently of its epic, at creation (`-p`) and when
  its impact changes. Give greater impact a higher priority (lower number).
- Rank each epic by the same measure applied to its outcome; use epic rank to
  order epics and decision clusters. Items do not inherit it.
- Use P0, the highest priority, for a broken shared build/environment, data loss
  or a live security hole; running work continues. Use `deferred` for backlog;
  leave P4 unused.
- Inspect what an item holds up with `board bd dep tree <id> --direction=up` or
  `board holders`; include committed nonblocking consumers
  when ranking it.

### Views

`board` views read one board snapshot per run; all but `board show` take
`--root <epic>` or `--root <milestone>`, `--limit <rows>` and
`--offset <rows>`. Output stops at 35,000 characters. Other queries: `board bd query`, `search`,
`blocked`, `lint`, `dep tree`.

| Command | View |
|---|---|
| `board show <id>… [--section <name>] [--comments] [--full]` | Items with links, fields and newest comments; `--json --field <field>` for scripts. |
| `board queue` | Ready work plus released rulings to plan, milestone work marked. |
| `board position` | Ready work against registered sessions and their pulls; held items with holder, role, tool, age and gone or idle marks; open questions holding work; ready milestones; finished epics not closed. |
| `board mine` | Items your session and its workers hold; holds of stopped workers marked. |
| `board health` | Counts, with each open milestone's progress; dispatchable counts include only unblocked items. |
| `board holders` | Items by open downstream count. |
| `board check` | Deviations from these conventions on live items, each naming the section it breaks; closed items are never checked; as flags, squashed text in editable fields and waits whose blocker the waiting item's text does not name. `board health` names their count; a board with deviations moves through `/board-migrate`. |
| `board related <terms>\|--like <draft> [--docs <paths>]` | Items (closed included) and canonical docs mentioning the terms, rarest matches first, with holders; `--like` takes the terms from a draft file. |
| `board bd list --type decision --all --label topic:<slug>` | Decision log. |
| `board bd list --status deferred --label topic:<slug>` | Topic backlog. |
| `board bd dep cycles` | Dependency-cycle check before dispatch. |

### Limits

- Board mode: `.beads/metadata.json` with `"dolt_mode": "server"` marks a
  server-mode board; otherwise it is embedded.
- On a server-mode board, every `board` command needs elevated sandbox
  permissions (global Sandbox and permissions); `board` starts a stopped
  server. Never use `board bd --readonly`.
- On an embedded board, run `board` commands one at a time and never
  interrupt a running one.
- `board bd ready` returns 100 rows; use `--limit 0` for inventories. Read
  inventories with one `board bd export` or
  `board bd list --all --limit 0 --json` instead of per-item `board show`.
- Edit fields with `board bd update --title/--description/--design/--acceptance`;
  `board bd edit` opens an editor and blocks.
- Give `board bd create` a description and `board bd close` a reason of 20+
  characters.
- Inspect changes with `board bd history <id> --events` and board-wide changes
  with `board bd events tail --since <seq>`.
