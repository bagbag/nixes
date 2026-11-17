## Board core (beads)

**Commands:** `board` in every skill command is `$HOME/.agents/bin/board`
(not on `PATH`): type `$HOME/.agents/bin/board show <id>`, never bare `board`
or bare `bd`. `board help [<verb>]` lists every verb. Board
verbs own every write. `board bd <args>` runs bd with `--readonly`: reads pass
and bd refuses a write, naming the board command (it does not catch every
write: `import`, `rename`, `config set` and `dolt remote add` pass on a server
board). **Raw bd writes only when no board command does it, or the user
authorized it:** `board bd --raw --yes <args>` (`--raw` alone prints this rule
and runs nothing). When board output stops early, run the command it prints
before relying on the missing part.

**Codex sandbox:** run every `board` command with elevated sandbox permissions.

**Content:** make each item complete without its linked files.

- Keep the work content in the item: what to do, packets, designs, findings,
  evidence summaries, verdicts, block reasons. Reference rulings, rule owners
  and items by id and anchor instead of restating their text.
- Keep working drafts and data files in the item's scratch folder
  (`$HOME/.agents/bin/scratch dir --for <id>`); move a draft's result
  into the item before hand-over or closure.
- Name each data file the work consumes or produces (dumps, diagnostics, logs,
  fixtures, generated output) in the item with path, size or hash, and how to
  obtain it: the regenerating command and commit, or its location and
  holder.

Without `.beads/`: a project with existing trackers or backlog files moves onto
the board through `/board-migrate`; otherwise run `$HOME/.agents/bin/board
setup` with the user's confirmation
(`$HOME/.agents/skills/shared/beads-setup.md`). Leave `bd setup` unrun. Share or join a board only on the user's request
([Shared boards](../shared/beads-setup.md#shared-boards)); `board` syncs a
shared board, the user an unshared one (`bd dolt push`/`pull`).

### Actors and holds

- **Actor:** the last 8 characters of the session id; a worker's actor is
  `<session actor>/<last 8 of its agent id>`. `board` derives it; Claude
  workers get theirs from bd-guard.
- **Hold:** an item's assignee is the doer holding it. A session holds a
  whole [change request](../shared/change-requests.md#change-requests);
  the CR's items go to its workers. Each doer claims, hands over
  and closes as itself; a session owns every hold under its actor prefix.
  Only the exact assignee can close an item.
- Claim with `board claim` (the next CR or item routed to your
  session under [Routing](#routing)) or `board claim <ids>`
  (named). Claiming a named item held within your own session (your
  actor or one of your workers) takes it over.
- Finish, hand over or unclaim each hold you still have.
- Free another doer's hold only with
  `board take <id>` (reassign to you with a comment) or
  `board unclaim <id>`. Take an item from a gone holder (`board position` or
  the claim report marks it gone) whenever your role could claim it; free any
  other session's hold only as the user or a
  [deciding session](../role/SKILL.md#roles), once you judge an idle-marked
  holder gone. For your own workers' holds marked stopped in `board mine`:
  continue the worker, hand the item over or free it.
- At your worker cap, hand over or unclaim partial work before
  `board claim --force "<reason>"`.
- A CR that leaves its holder unfinished (unclaimed, returned, freed from a
  gone holder) keeps its worktree, branch and uncommitted edits; its next
  claimer reuses the worktree as it stands. Git states stopping a CR:
  [Change requests](change-requests.md) Rebase.

### Kinds

| Type | Kind |
|---|---|
| `task`, `bug`, `spike` | Work item; lives in a CR, unless marked no-code ([Work items](#work-items)). |
| `design` | Design item: architecture, package graph and needed decisions for a slice. |
| `decision` | Question, later the ruling's record ([Questions and rulings](#questions-and-rulings)). |
| `change-request` | The claimed, reviewed and landed unit ([Change requests](../shared/change-requests.md#change-requests)). |
| `epic` | Topic or outcome, never claimed ([Epics](../shared/board-coordination.md#epics)). |
| `milestone` | Release checkpoint ([Milestones](../shared/board-coordination.md#milestones)). |
| `gate` | Upstream wait or the user's go ([Dependencies](#dependencies)). |

Titles carry no prefixes; use only these types (a check others wait on is a
task, [Work items](#work-items)). Review is a status, not
a kind: create a findings-only review (outside any CR) as an
unassigned task directly in review,
`board create <title> -t task --status in_review …`.

### Routing

A bare `board claim` takes the unassigned ready CRs and items routed to the
session's role or pulls (`board position` counts them). A claim by id checks
no role; follow these rules yourself:

- CRs by pull: `open` to `design` when its open items are design items, else
  `implement`; `in_review` (agent review or agent checkpoint) to `review`;
  refresh work to `review`, kind `refresh`
  ([queue](../shared/board-coordination.md#change-request-queue)).
- A work item is claimed by id only inside a CR your session holds. Decision,
  plan and milestone kinds, findings-only reviews and challenges, and work
  items marked no-code need no CR.
- Pull `plan` also claims the board restructuring tasks it creates itself,
  and an `open` CR with no open items or marked for replanning (returned from
  an agent checkpoint, or a child of a rejected CR).
- A session with the decide set (lead, solo) claims by id its round's open
  decisions, `needs_ratification` records, CRs in `needs_acceptance`, passed
  `look` `after` children marked `after <base>` and ready milestones, and
  closes finished epics whose acceptance names the user.

Questions, autopilot's parked ones included, stay unassigned until a session
claims them.

On a shared board (`.beads/board-shared.json` exists):

- **Queue:** each item's person is its `queue:<person>` label, else its nearest
  ancestor's (none, or parents in different queues: unrouted); a new item
  takes its parent's queue, else its creator's. Your person: `git config
  agents.person`. Claims take only your queue's items.
- **Moves:** only lead and solo sessions and a person's terminal move items
  (`board route <person> <ids…>`, `board send <person> <ids…>` into their
  inbox); others ask a deciding session. File a find for another person with
  `board create --for <person>`; decide.md Inbox routes it.
- **Sync:** run the fix a `board: sync …` line names; other work continues
  unless beads refuses the write.
- Raw bd never creates with `--id` or dotted child ids: parent.N ids stop sync.

### Work items

- Cut one item per outcome a dependent could need, sized for one worker pass
  Keep parts that must land together
  in one item (atomic rename, contract plus its only caller).
  Move a part with a different blocker or dependent to its own item in another
  CR (planning decides); items do not split inside a CR.
  Cut a check others wait on (whole typecheck, fresh build), or other work
  that by design changes no code, as a task marked no-code when created
  (metadata `no_code=1` on `create` or a `create --graph` node). It sits outside any
  CR, runs against the target, and its acceptance is the recorded passing
  run; a defect it finds becomes a code item in a CR.
- Fields: description (outcome and reason), design (contract, files,
  checks, ruling ids with owner anchors), acceptance (done criteria),
  `spec_id` (specification reference; a key of a `create --graph` node, set
  at creation), `blocks` edges.
- Keep every field of every item (description, design, acceptance,
  `notes`) at its current state. Change fields with `board field export <id>…
  [--field F]…`, edit the files in place, `board field apply <id>…` (one update
  per item; `discard` drops an export); never rewrite a field from memory. Comments hold only one-line events (a failed attempt is one line);
  history lives in `board bd history`.
- Before creating an item or question, search with
  `board related --like <draft>` (or `board related <terms>`); extend an open
  item on the same decision, files or migration instead.
- Create items with one `board create --graph <plan.json>` per wave (a single item: `board create <title> --type … --description-file …`). Let Beads
  generate every id; confirm creation before creating dependents.
- When an open item becomes redundant, move its leftover work into the owning
  item's `--acceptance`, then `board bd --raw --yes supersede <id> --with <owner>`, or
  `board bd --raw --yes duplicate <id> --of <canonical>` for an exact duplicate (no board command does either).

### Questions and rulings

| Status | Question state |
|---|---|
| `open` | Unanswered and unclaimed. Blocks its dependents. |
| `in_progress` | Unanswered; claimed by the session running its round. Blocks its dependents. |
| `decided` | Answered, release pending. Still blocks. |
| `released` | Binding. Blocks the open items it changes until a `plan` session plans it and closes it. Waits only on what its planning needs: a live decision, a `user <date>` gate, a design or a spike. Holds no decided record resting on it. |
| `needs_ratification` | Autopilot ruling in force, awaiting the user's ratification through a deciding session. Blocks nothing. |
| closed | Planned, superseded or withdrawn. A reversal is a revision record (`board ruling revise <id>`, [Rulings](../shared/board-coordination.md#rulings)). |

- Withdraw a question the user drops with
  `board close <id> --reason "withdrawn: <why>"`, quoting the user.
- In role `agent`, put every user-facing question in Beads, including
  clarifications, blockers and approvals a governing rule reserves for the
  user; quote that rule in an approval question. Reuse the existing question
  or create one; report its id and status in chat. Never ask the user in the
  agent session or through a question tool; deciding sessions handle user
  rounds.
- One decision per record. While open, the description holds the
  [Decision packet](#decision-packet).
- Name the items a question or ruling holds up when you create it, creating
  missing ones first: `--holds <ids>` (shorthand for blocking links; also
  `--deps blocks:<id>` on `board create --type decision` and `board ruling
  revise`; a plan's links from its decision node; in a round, the question's
  `holds`, which Record passes) or `--holds none`. Depend on each open question its options
  assume (`board block <id> --on <other>`; no reason line when the blocker is a
  question).
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
| Prior rulings (evidence) | Rulings, rules, docs and pending approvals touching the question: owner, and whether the end state keeps or revises each ([Others' input](../shared/decision-protocol.md#others-input)); options a missing approval blocks stay in the set. |
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
| `in_review` | A findings-only review ([Kinds](#kinds)); CR statuses: [Change requests](../shared/change-requests.md#change-requests). |
| `deferred` | [Deferral](../shared/board-coordination.md#deferrals-and-environment-facts). |

Question statuses: [Questions and rulings](#questions-and-rulings). Assign
only a task waiting on a human action to `user`; express waiting on other work
with `blocks`.

### Dependencies

Use the first matching row. `board block` and the `board ruling` verbs replace an existing link; by hand,
first remove the pair's `relates-to` edge. When order
and context coincide, keep `blocks`.

| Relation | Use |
|---|---|
| B can't start before A, including released ruling A changing B | `blocks`: `board block B --on A --reason "<why>"` ([Milestones](../shared/board-coordination.md#milestones) members: `board block <milestone> --on <member>`, no reason line). |
| B is part of outcome A | `--parent A` |
| B found while working on A | `discovered-from`: `board create … --deps discovered-from:A` |
| Shared context, alternatives, a ruling's context-only item | `relates-to`: `board link A B --type relates-to` |
| B revises ruling A | `board ruling revise A` links B at creation; release supersedes A ([Rulings](../shared/board-coordination.md#rulings)) |
| B waits on the user's go (no open decision) | On the user's instruction only; raise your own caution as a question. `board gate create --blocks B --reason "<why>" --title "user <date>: '<words>'"`; more items: `board block <item> --on <gate>`; lift on the user's word or a covering released ruling: `board gate resolve <gate>`. |
| External wait on another project's delivery | gate; read `$HOME/.agents/skills/shared/upstream-waits.md` first |

### Hand-over and acceptance

1. Scope a CR's acceptance under Acceptance [Evidence and gates](../shared/acceptance.md#evidence-and-gates)
   (`$HOME/.agents/skills/shared/acceptance.md#evidence-and-gates`).
2. Keep active work `in_progress` with its current state in `notes` (resume
   point, what it waits on; edit fields as under [Work items](#work-items)). Hand over only with
   complete evidence for the CR's acceptance. When an item starts waiting on a
   blocker, block the item with notes: `board block` on your own held item
   unclaims it.
3. Hand over: `board handover <cr> "<evidence>"` ([Change requests](../shared/change-requests.md#change-requests)).
4. The acceptor passes with `board handover <cr> "<verdict>"` or returns it
   with `board return <cr> "<findings>"`. The user's accept is a deciding
   session's [Accept](../role/protocols/decide.md#accept).
5. `board block` on a CR in review returns it to the queue; amend it to the
   blocker before handing it over again.

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

`board check` lists deviations from these conventions on live
items; a board with deviations moves through
`/board-migrate`.

Other queries: `board bd query`, `search`, `blocked`, `lint`, `dep tree`; the
decision log, `board bd list --type decision --all --label topic:<slug>`; the
topic backlog, `board bd list --status deferred --label topic:<slug>`; before
dispatch, `board bd dep cycles`.

### Limits

- Board mode: `.beads/metadata.json` with `"dolt_mode": "server"` marks a
  server-mode board; otherwise it is embedded.
- A server-mode board's `board` starts a stopped server. Under Codex, every commit in a CR worktree
  needs elevation too (`.git` is read-only in its sandbox).
- On an embedded board, run `board` commands one at a time and never
  interrupt a running one.
- `board bd ready` returns 100 rows; use `--limit 0` for inventories. Read
  inventories with one `board bd export` or
  `board bd list --all --limit 0 --json` instead of per-item `board show`.
- Give `board create` a description of 20+ characters.
- Inspect board-wide changes with `board bd events tail --since <seq>`.
