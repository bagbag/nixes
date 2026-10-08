## Work tracking (beads)

`bd prime` (session hook) teaches the commands; this maps our meanings onto
them. An issue's own text (packet, block reason, evidence, verdict) lives in
the issue; shared prose (briefs, reports) lives in linked `.scratch/` files.
Without `.beads/`, follow `$HOME/.agents/skills/shared/beads-setup.md` with the
user. Agent guidance comes from the session hooks, not `bd setup`; remote sync
(`bd dolt push`/`pull`) belongs to the user.

### Structure

- **Arc epic** `<topic-slug>/<arc-slug>`, label `topic:<topic-slug>`:
  description = the board (prose, no item lists), `--design` = arc rules
  (scope, sequencing, holds, exceptions; lead only), `--acceptance` = done
  criteria (lead only). Recover with `bd show <epic>` and the views below.
- Every arc item is a direct child of the epic and inherits its topic label.
  Group with labels and `bd dep relate`; `--parent` lists direct children only.
- The epic closes only when no child is open or deferred: the arc's
  closure check.

### Items

| Item | Shape | Ends |
|---|---|---|
| Package | task/bug/spike; contract, file zones, checks in `--design`; done criteria in `--acceptance`; spec in `--spec-id`; `blocks` deps; one `bd create --graph <plan.json>` per wave | acceptor closes it |
| Question | type `decision`, label `human`, assigned to whoever answers (`user`; `goal-lead` in a goal pair); description = decision packet; `blocks` its dependents | the lead records the answer: `bd human respond <id> "<ruling> (user\|lead) → <owner>"` |
| Deferral | `bd defer --reason "<revisit condition>"` | undeferred at its date or on named new evidence, or topic backlog at arc close |
| Environment fact | memory `bd remember --key <key>`: temporary, repository-wide, needed by every session now; states its removal condition | `bd forget` |

**Decision packet** (`##` sections): **Question** (the exact choice),
**Current authority** (owners in force, conflicts), **Evidence**
(`path:line`, executed results, limits), **Options** (decisive trade-offs;
developed with `architect` or `option-explorer` when the choice is
consequential or its option space is open), **Recommendation** (and what would
change it).

### Rulings

- The lead alone rules and creates memories; it records the user's answers
  from chat. A consequential ruling without a question gets one, answered at
  once. A lead ruling has exactly one realistic clean option.
- The answered question is the decision record; relate it to the record it
  revises (`bd dep relate`). A contested ruling also gets the project's
  rationale record where one exists.
- One owner holds the rule, written at once unless noted:
  - topic contract or design target: `docs/<topic-slug>/`;
  - authoring convention: coding style or skill;
  - consumer-visible module behaviour: its module docs (README, `docs/`),
    with the change that makes it true; the implementing package cites the
    ruling until then;
  - arc-only rule: the epic's `--design`.

Labels: `human` (waits for a person) · `decided` (decision made, not
released) · `review` · `needs-ratification` · `intake` · `expert-claim` ·
`export:<capability>` / `provides:<capability>`.

### Acceptance

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

### Views

Scope with `--parent <epic>` when several arcs share the repository.

- `bd ready --unassigned` — next work.
- `bd ready --label review --assignee <you>` — awaiting your acceptance.
- `bd list --label human --parent <epic>` — awaiting a person.
- `bd list --type decision --all --label topic:<slug>` — the decision log.
- `bd list --status deferred --label topic:<slug>` — the topic backlog.
- `bd gate list` — upstream waits.
- `bd stale --days 1 --status in_progress` — lapsed claims recovery missed.
- `bd swarm validate <epic>` before dispatch. `bd swarm status` counts deferred
  and outside-blocked work as ready; dispatch from `bd ready`.

### Limits

- `bd ready` returns 100 rows; add `--limit 0` for inventories.
- Claims lapse after five minutes without `bd heartbeat <id>`; send one between
  long steps. After confirming a worker is gone:
  `bd unclaim <id> --if-assignee <worker>`.
- Writes pass `--actor <mode or worker>`; `bd close` refuses an actor other
  than the assignee; `bd history <id> --events` shows who changed what.
- `bd create` needs a description; `bd close` a reason of 20+ characters.
