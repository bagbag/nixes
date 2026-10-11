## Work tracking (beads)

`bd prime` (session hook) teaches the commands; this maps our meanings onto
them. An issue's own text (packet, block reason, evidence, verdict) lives in
the issue; shared prose (briefs, reports) lives in linked `.scratch/` files.
Without `.beads/`, follow `$HOME/.agents/skills/shared/beads-setup.md` with the
user. Agent guidance comes from the session hooks, not `bd setup`; remote sync
(`bd dolt push`/`pull`) belongs to the user.

### Structure

- **Root epic** = the board: its description holds it (prose, no item
  lists). Short explicit id (`bd create --id <prefix>-<abbrev>`). Recover
  with `bd show <root epic>` and the views below.
- **Goal epic** `<goal-slug>`: root when the work spans several arcs (always
  for a goal pair); `--design` = goal-wide rules, `--acceptance` = link to
  the goal's docs owner (lead only); closes per the arc close.
- **Arc epic** `<topic-slug>/<arc-slug>`, label `topic:<topic-slug>`, child of
  the goal epic or itself the root: `--design` = arc rules (scope,
  sequencing, holds, exceptions; lead only), `--acceptance` = done criteria
  (lead only).
- An arc whose contract names sub-arcs gets one sub-epic per sub-arc
  (`--parent <arc epic>`, same shape). Topics stay labels.
- Every arc item is a direct child of its (sub-)arc epic with its topic label:
  `--parent <epic>` sets both; graph nodes set `parent_id` and list the label
  in `labels`. Let beads mint item ids (`<epic>.N`, graph: hash).
  Group with labels and `bd dep relate`; `bd ready --parent` and
  `bd list --parent` include sub-epics' items.
- **Scope:** an item lives in the arc epic of the topic that owns its change.
  Work another topic owns goes into that topic's arc epic under the goal epic,
  opened through the lead and the user; the waiting item depends on it
  (`blocks` across epics).
- An arc epic closes only when no child is open or deferred: the arc's
  closure check (`bd epic close-eligible --dry-run`).
- Assignee = current holder (claimer, acceptor, answerer); unassigned open
  work items (not epics or checkpoints) are the dispatch queue.

### Items

| Item | Shape | Ends |
|---|---|---|
| Package | task/bug/spike; contract, file zones, checks in `--design`; done criteria in `--acceptance`; spec in `--spec-id`; `blocks` deps; one `bd create --graph <plan.json>` per wave | acceptor closes it |
| Question | type `decision`, label `human`, assigned to whoever answers (`user`; `goal-lead` in a goal pair); description = decision packet; `--design` = current decision, rewritten in place; comments = history; `blocks` its dependents | the lead records the answer: `bd human respond <id> "<ruling> (user\|lead) → <owner>"`; in a goal pair, the lead records the decision in `--design` and adds `decided`, and goal-agent closes it once the ruling landed (relay) |
| Checkpoint | type `milestone`, child of the root epic, title `checkpoint: <result>`, assigned to the lead; `--acceptance` = the executable result; depends (`blocks`) on every item it needs, across arcs | ready once those close; the lead verifies the result and closes it |
| Deferral | `bd defer --reason "<revisit condition>"` | undeferred at its date or on named new evidence, or topic backlog at arc close |
| Environment fact | memory `bd remember --key <key>`: temporary, repository-wide, needed by every session now; states its removal condition | `bd forget` |

**Priority** orders work foundation first; `blocks` edges own hard order. The
lead and the user rank the arc epics by what builds on what: P1 foundation, P2
middle, P3 consumers; sub-arc epics take their arc epic's rank. Each item
takes its epic's priority at creation (`-p`; beads does not inherit it) and
when it moves. P0 interrupts per item (broken shared build or environment,
data loss, a live security hole). Backlog = `deferred`; P4 unused. Within an
epic, order by everything an item holds up
(`bd dep tree <id> --direction=up`).

**Decision packet** (`##` sections): **Question** (the exact choice),
**Root cause and end state** (decision protocol Root fix and End state),
**Current authority** (owners in force, conflicts), **Evidence**
(`path:line`, executed results, limits), **Options** (decisive trade-offs;
developed with `architect` or `option-explorer` when the choice is
consequential or its option space is open), **Recommendation** (and what would
change it).

### Rulings

- Leads rule within their mode's decision rules; workers return decisions.
  The ruling lead records the user's answers from chat and creates memories.
  A consequential ruling without a question gets one, answered at once.
- The answered question is the decision record; relate it to the record it
  revises (`bd dep relate`). A contested ruling also gets the project's
  rationale record where one exists.
- One owner holds the rule, written at once unless noted:
  - topic contract or design target: `docs/<topic-slug>/`;
  - authoring convention: coding style or skill;
  - consumer-visible module behaviour: its module docs (README, `docs/`),
    with the change that makes it true; the implementing package cites the
    ruling until then;
  - goal-wide rule: the goal epic's `--design`; arc-only rule: the arc
    epic's `--design`.

Labels: `human` (waits for a person) · `decided` (decision made, not
released) · `review` · `needs-ratification` · `expert-claim` ·
`export:<capability>` / `provides:<capability>`.

### Acceptance

- Scope package acceptance to touched files and affected consumers; each
  arc-wide gate (whole typecheck, full suite, fresh build) lives only in its
  gate task, which re-checks closed packages.
- Keep `in_progress` for active work. Hand over (`review`) once the package's
  own acceptance has complete evidence; partial work stays open with the
  remainder in `--acceptance`; waiting work depends (`blocks`) on what it
  waits for.
- The worker comments its evidence (`bd comment`) and hands over:
  `bd update <id> --status open --assignee <acceptor> --add-label review`. The
  acceptor is the lead of whoever did the work.
- The acceptor closes with the verdict as reason, or comments the finding and
  hands back: `--assignee <worker> --remove-label review`.
- Dependents wait on the package itself.

### Upstream waits

Work waiting on another project's capability:

- Upstream: the delivering issue carries `export:<capability>`. With the
  user's approval, the waiting lead files a missing one
  (`bd -C <upstream path> create … --label export:<capability>,human`,
  description naming the waiting issue) or labels and comments an existing one.
- Local: `bd gate create --type=human --blocks <issue> --reason "waits for
  <project>:<capability>"`; further waiting issues depend on the same gate.
- Upstream runs `bd ship <capability>` when it closes the issue; the waiting
  lead resolves the gate once `bd -C <upstream path> list --label
  provides:<capability> --status closed` shows it.

### Arc close

1. Detach deferrals into the topic backlog: `bd update <id> --parent ""`.
2. `bd close <epic>`; its arc rules end with it.
3. The lead closes the goal epic once the user confirms the goal is reached
   and no child is open.

### Views

Scope with `--parent <root epic>` (includes every level below).

- `bd ready --unassigned --exclude-type epic,milestone` — next work.
- `bd list --label review --assignee <you>` — awaiting your acceptance,
  blocked items included.
- `bd list --label human --parent <root epic>` — awaiting a person.
- `bd dep list <checkpoint>` — the items a checkpoint needs.
- `bd list --type decision --all --label topic:<slug>` — the decision log.
- `bd list --status deferred --label topic:<slug>` — the topic backlog.
- `bd gate list` — upstream waits.
- `$HOME/.agents/bin/board-health [<root epic>]` — lead counts, dispatch
  queue size, priority drift from the arc epic, items outside any epic,
  `waiting` labels (use a `blocks` dependency), `in_progress` started 25+
  minutes ago.
- `bd dep cycles` before dispatch.

### Limits

- `bd ready` returns 100 rows; add `--limit 0` for inventories.
- Claims lapse after five minutes without `bd heartbeat <id>`; send one between
  long steps. Once `$HOME/.agents/bin/worker-last-use` no longer lists a
  worker (idle 30+ minutes) and the platform's agent status shows it ended,
  the board owner returns its lapsed claims: `bd reclaim --id <id>`.
- Writes pass `--actor <mode or worker>`; `bd close` refuses an actor other
  than the assignee; `bd history <id> --events` shows who changed what.
- `bd create` needs a description; `bd close` a reason of 20+ characters.
