## Work tracking (beads)

**Commands:** `board` in every skill command is `$HOME/.agents/bin/board`
(not on `PATH`): type `$HOME/.agents/bin/board bd show <id>`, never bare
`board` or bare `bd`. Run every bd command as `board bd <args>`
(`board bd <command> --help`).

Keep item-specific packets, block reasons, evidence and verdicts in the item;
link shared briefs and reports from `.scratch/` files. Reference rulings and
rule owners by id and anchor instead of restating their text. The session hook
injects `board bd remember` facts.

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
| `epic` | Outcome ([Epics](#epics)). |
| `milestone` | Release checkpoint ([Milestones](#milestones)). |
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
  `board related <terms>` and `board bd find-duplicates`; extend an open item on the same decision, files or
  migration instead.
- Create items with one `board bd create --graph <plan.json>` per wave. Let Beads
  generate every id; confirm creation before creating dependents.
- When an open item becomes redundant, move its leftover work into the owning
  item's `--acceptance`, then `board bd supersede <id> --with <owner>`, or
  `board bd duplicate <id> --of <canonical>` for an exact duplicate.

### Epics

- Root a project's board at a goal epic with finite outcome epics below it.
  Nest deeper only for independently closable sub-outcomes. Place an item
  under the outcome it contributes to; loose items sit under the goal epic.
  Topics are labels (`topic:<topic-slug>`). `board bd create --graph` copies
  no labels from the parent: give each node its `topic:` label.
- Title: the outcome. Description: two to four sentences on what will be true,
  why, scope and the owner link. `--acceptance`: checkable done criteria.
  Epics carry no rules, holds, status, item lists or history; history goes to
  comments, rules to their owners.
- An outcome's own verification is its epic acceptance; name the user there
  when the outcome needs the user's judgment.
- The planning session closes an epic as soon as its criteria hold and no
  child is open (`board bd epic close-eligible --dry-run`), detaching deferred
  children first (`board bd update <id> --parent ""`). A
  [deciding session](../role/SKILL.md#roles) walks the user through an epic
  whose acceptance names the user and closes it on acceptance; it or the user
  closes the goal epic once the user confirms the goal is reached.

### Milestones

- Track each release checkpoint as one `milestone` item (`1.0-beta`) under
  the goal epic. Its acceptance names the checkpoint's evidence and the user;
  the goal owner states which work belongs to it.
- Add members with `board bd dep add <milestone> <member>`, without a reason
  line. Everything a member waits on belongs to the milestone too. Block the
  milestone by the last release step as well.
- A member epic brings all its descendants; file work that ships later under
  another outcome.
- Membership orders work and never cuts it: P0 items first, then milestone
  work, then the rest, each by priority.
- Place each new item: a member when the goal owner's criterion covers it. An
  item discovered from milestone work joins unless it is a pure addition. Move
  work in or out by adding or removing its edge.
- When the milestone turns ready, a deciding session walks the user through
  it, closes it on acceptance and reconciles the goal owner under
  project-memory.

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
  [Decision packet](#decision-packet). At decision time, move the packet into
  the first comment and rewrite the description into these `##` sections,
  which `board bd lint` checks before release: `Question`,
  `Alternatives Considered`, `Decision`, `Rationale` (with provenance: user or
  the ruling session's role, and date) and `Rule owner`.
- Make the question block the items it holds up, creating missing ones, and
  depend on each open question its options assume (`board bd dep add <id> <other>`).
- Implementation steps, file lists and test lists become work items, never
  ruling text.
- Record each ruling you make as "ruling — rejected: <alternative>, fails
  <cleanliness test, principle or correctness property>". For a consequential
  ruling without a question, create and answer one at once.
- Record a revision as a new record restating the rule in full; supersede the
  old record when the revision takes effect (release; autopilot: when it
  records the revision). Full replacement:
  `board supersede <old> --with <new>`. One rule of a record:
  name it and add `--partial`; the rest stays in force. A revision question
  blocks only the work items whose part it would change.
- On the user's ratification, the claiming deciding session closes a
  `needs_ratification` record with the ratification as reason; a reversal
  becomes a revision record.
- Answer provenance questions from the record (`board bd show`,
  `board bd history <id> --events`).
- Owner text contradicting a newer released ruling is a missed owner write:
  the ruling binds; fix the owner.
- Write each rule into its owner under project-memory
  [Durable owners](../shared/project-memory.md#durable-owners)
  (`$HOME/.agents/skills/shared/project-memory.md`).

### Decision packet

Use these `##` sections:

| Section | Content |
|---|---|
| Question | Exact choice. |
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
| `deferred` | [Deferral](#deferrals-and-environment-facts). |

Question statuses: [Questions and rulings](#questions-and-rulings). Assign
only a task waiting on a human action to `user`; express waiting on other work
with `blocks`.

### Dependencies

Use the first matching row. Beads allows one edge kind per pair: remove a
`relates-to` edge before adding `blocks` or `supersedes` to the same pair; when
order and context coincide, keep `blocks`.

| Relation | Use |
|---|---|
| B can't start before A, including released ruling A changing B | `blocks`: `board bd dep add B A`, with a one-line reason naming A in B ([Milestones](#milestones) members excepted). |
| B is part of outcome A | `--parent A` |
| B found while working on A | `discovered-from`: `board bd create … --deps discovered-from:A` |
| Shared context, alternatives, a ruling's context-only item | `relates-to`: `board bd dep relate A B` |
| B revises ruling A | `supersedes` ([Questions and rulings](#questions-and-rulings)) |
| B waits on the user's go (no open decision) | On the user's instruction only; raise your own caution as a question. `board bd gate create --type=human --blocks B --title "user <date>: '<words>'"`; more items: `board bd dep add <item> <gate>`; lift on the user's word or a covering released ruling: `board bd gate resolve <gate>`. |
| External wait | gate ([Upstream waits](#upstream-waits)) |

### Hand-over and acceptance

1. Scope an item's acceptance under the review protocol's Evidence and gates
   (`$HOME/.agents/skills/role/protocols/review.md#evidence-and-gates`).
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

### Deferrals and environment facts

| Item | Lifecycle |
|---|---|
| Deferral | `board bd defer <id> --reason "<revisit condition>"`, plus `--until <date>` for a date condition (bd undefers it then); undefer other conditions on named new evidence. Deferred items are the project backlog. |
| Environment fact | `board bd remember --key <key>` for temporary repository-wide facts needed by every current session, a user's broad stop (area, paths, kind of action) included with its words and date; state a removal condition; remove with `board bd forget`. |

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

### Upstream waits

1. The delivering upstream issue carries `export:<capability>`. With user
   approval, the waiting session files a missing issue or labels/comments an
   existing one:
   `board bd -C <upstream path> create … --assignee user --label export:<capability>`;
   description names the waiting issue.
2. Create the local wait:
   `board bd gate create --type=human --blocks <issue> --reason "waits for <project>:<capability>"`.
   Make further waiting issues depend on the same gate.
3. Upstream runs `board bd ship <capability>` at issue closure. The waiting
   session resolves the gate once
   `board bd -C <upstream path> list --label provides:<capability> --status closed`
   shows the capability.

### Views

`board` views read one board snapshot per run; most take `--root <epic>` or
`--root <milestone>`. Other queries: `board bd query`, `search`, `find-duplicates`,
`blocked`, `lint`, `dep tree`.

| Command | View |
|---|---|
| `board queue` | Ready work plus released rulings to plan, milestone work marked. |
| `board position` | Ready work against registered sessions and their pulls; held items with holder, role, tool, age and gone or idle marks; open questions holding work; ready milestones; finished epics not closed. |
| `board mine` | Items your session and its workers hold; holds of stopped workers marked. |
| `board health` | Counts, with each open milestone's progress; dispatchable counts include only unblocked items. |
| `board holders` | Items by open downstream count. |
| `board check` | Deviations from these conventions on live items, each naming the section it breaks; closed items are never checked; squashed text in editable fields as a flag. `board health` names their count; a board with deviations moves through `/board-migrate`. |
| `board related <terms> [--docs <paths>]` | Items (closed included) and canonical docs mentioning the terms, with holders. |
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
  `board bd list --all --limit 0 --json` instead of per-item `board bd show`.
- Edit fields with `board bd update --title/--description/--design/--acceptance`;
  `board bd edit` opens an editor and blocks.
- Give `board bd create` a description and `board bd close` a reason of 20+
  characters.
- Inspect changes with `board bd history <id> --events` and board-wide changes
  with `board bd events tail --since <seq>`.
- `board bd show --json` omits dependents unless you pass
  `--include-dependents`; plain `board bd show` lists them under BLOCKS.
