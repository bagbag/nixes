## Work tracking (beads)

Use session-hook `bd prime` for command guidance. Keep issue-specific packets,
block reasons, evidence and verdicts in the issue; link shared briefs and reports
from `.scratch/` files.

Without `.beads/`, follow `$HOME/.agents/skills/shared/beads-setup.md` with the
user. Agent guidance comes from session hooks, not `bd setup`. Remote sync
(`bd dolt push`/`pull`) belongs to the user.

### Structure

| Entity | Shape and ownership |
|---|---|
| Root epic / board | Description holds board prose, no item lists. Recover with `bd show <root epic>` and [Views](#views). |
| Goal epic | Root for multi-arc work. Lead owns `--design` (goal rules) and `--acceptance` (goal-doc owner link). Close under [Arc close](#arc-close). |
| Arc epic | Root or goal-epic child; label `topic:<topic-slug>`. Lead owns `--design` (scope, sequencing, holds, exceptions) and `--acceptance` (done criteria). |
| Sub-arc epic | One per contract-named sub-arc: `--parent <arc epic>`; same shape as arc epic. Topics remain labels. |
| Assignee | Current holder: claimer, acceptor or answerer. Each mode defines which assignments form its dispatch queue. |

- Let Beads generate every issue ID, including epics. Capture the returned ID
  for references and dependencies. Confirm creation succeeds before creating
  dependent items.
- Give epics readable sentence-case titles that state their area or outcome; keep
  the topic slug in the `topic:<topic-slug>` label and both slugs in artifact paths.
- Mark design, gate and checkpoint items with a leading `[Design]`, `[Gate]` or
  `[Checkpoint]`; use no other title prefixes.
- Make each arc item a direct child of its owning (sub-)arc epic with its topic
  label. `--parent <epic>` sets both; graph nodes set `parent_id` and `labels`.
- Group with labels and `bd dep relate`. `bd ready --parent` and
  `bd list --parent` include sub-epic items.
- Place changes in their owning topic's arc epic. Open other-topic work through
  the lead and user under that topic's arc epic within the goal epic; add
  cross-epic `blocks` dependencies from waiting items.
- Close an arc epic only with no open or deferred child; check with
  `bd epic close-eligible --dry-run`.

### Items

#### Package

| Field | Content |
|---|---|
| Type | `task`, `bug` or `spike`. |
| `--design` | Contract, file zones, checks. |
| `--acceptance` | Done criteria. |
| `--spec-id` | Specification reference. |
| Dependencies | `blocks` edges. |

Create packages with one `bd create --graph <plan.json>` per wave. The acceptor
closes each package under [Acceptance](#acceptance).

#### Question

- Use type `decision`, label `human`, assigned to the answerer (`user` unless
  the mode names another).
- Put the [Decision packet](#decision-packet) in the description, the current
  decision in `--design` (rewrite in place), and history in comments. Make the
  question block its dependents.
- Record the answer in `--design` with a provenance comment
  `<ruling> (user|lead) → <owner>`. Keep the question open until its ruling
  is in force; its holder then closes it:
  `bd close <id> --reason "landed in <owners>"`.

#### Checkpoint

- Use type `milestone`, child of the root epic, title `[Checkpoint] <result>`,
  assigned to the lead; put the executable result in `--acceptance`.
- Depend on every contributing item through `blocks`, including across arcs.
  Once contributors close, the lead runs the result and closes the checkpoint.

#### Deferrals and environment facts

| Item | Lifecycle |
|---|---|
| Deferral | `bd defer --reason "<revisit condition>"`; undefer at its date or on named new evidence; detach to topic backlog at arc close. |
| Environment fact | `bd remember --key <key>` for temporary repository-wide facts needed by every current session; state a removal condition; remove with `bd forget`. |

### Priority

- Rank each item by how much existing or committed work will build on its
  structure, API or conventions, including work it does not block.
- Count only tasks on the board or work committed in the goal or contract;
  hypothetical future work counts zero.
- Set priority per item, independently of its epic, at creation (`-p`) and when
  its impact changes. Give greater impact a higher priority (lower number).
- Rank each epic by the same measure applied to its outcome; use epic rank to
  order epics and decision clusters. Items do not inherit it.
- Use P0, the highest priority, for a broken shared build/environment, data loss
  or a live security hole; running work continues. Use `deferred` for backlog;
  leave P4 unused.
- Use `blocks` to enforce hard order. Inspect what an item holds up with
  `bd dep tree <id> --direction=up`; include committed nonblocking consumers
  when ranking it.

### Decision packet

Use these `##` sections:

| Section | Content |
|---|---|
| Question | Exact choice. |
| Root cause and end state | Decision protocol's Root fix and End state. |
| Current authority | Owners in force and conflicts. |
| Evidence | `path:line`, executed results, limits. |
| Options | Decisive trade-offs; use `architect` or `option-explorer` for consequential choices or open option spaces. |
| Recommendation | Recommended option and conditions changing it. |

### Rulings

- Leads rule within mode authority; workers return decisions. The ruling lead
  records user answers from chat and creates memories.
- For a consequential ruling without a question, create and answer one at once.
- Record each lead ruling as: "ruling — rejected: <alternative>, fails <stated
  principle, platform or correctness>".
- Use the answered question as decision record; relate revised records with
  `bd dep relate`. Also write a contested ruling to the project's rationale
  record where one exists.
- Write the rule to its owner at once unless the mode defers writes to a
  release.

| Rule | Authoritative destination |
|---|---|
| Topic contract / design target | `docs/<topic-slug>/`. |
| Authoring convention | Coding style or skill. |
| Consumer-visible module behavior | Module README or `docs/`, with the change making it true; implementing package cites the ruling until then. |
| Goal-wide rule | Goal epic `--design`. |
| Arc-only rule | Arc epic `--design`. |

### Labels

`human` = waits for a person; `review` ([Acceptance](#acceptance));
`expert-claim` (worker-arcs Contain); `export:<capability>` /
`provides:<capability>` ([Upstream waits](#upstream-waits)). Mode labels:
`decided` (goal relay), `needs-ratification` (autopilot).

### Acceptance

1. Scope package acceptance to touched files and affected consumers. Put each
   arc-wide gate (whole typecheck, full suite, fresh build) only in its gate task;
   that task re-checks closed packages.
2. Keep active work `in_progress`. Hand over with `review` only when the package's
   acceptance has complete evidence. Keep partial work open, remainder in
   `--acceptance`; block waiting work on what it needs.
3. Worker comments evidence with `bd comment`, then hands over to its lead:
   `bd update <id> --status open --assignee <acceptor> --add-label review`.
4. Acceptor closes with the verdict as reason, or comments findings and returns:
   `--assignee <worker> --remove-label review`.

Dependents wait on the package itself.

### Upstream waits

1. The delivering upstream issue carries `export:<capability>`. With user
   approval, the waiting lead files a missing issue or labels/comments an
   existing one:
   `bd -C <upstream path> create … --label export:<capability>,human`;
   description names the waiting issue.
2. Create the local wait:
   `bd gate create --type=human --blocks <issue> --reason "waits for <project>:<capability>"`.
   Make further waiting issues depend on the same gate.
3. Upstream runs `bd ship <capability>` at issue closure. The waiting lead resolves
   the gate once `bd -C <upstream path> list --label provides:<capability> --status closed`
   shows the capability.

### Arc close

1. Detach deferrals to the topic backlog: `bd update <id> --parent ""`.
2. Run `bd close <epic>`; its arc rules end with it.
3. Lead closes the goal epic once the user confirms the goal is reached and no
   child is open.

### Views

Scope with `--parent <root epic>` to include every descendant level.

| Command | View |
|---|---|
| `bd ready --unassigned --exclude-type epic,milestone` | Unassigned candidates for modes that dispatch them. |
| `bd ready --assignee goal-agent --parent <goal epic> --exclude-type epic,milestone` | Goal-agent dispatch queue. |
| `bd list --label review --assignee <you>` | Awaiting your acceptance, including blocked items. |
| `bd list --label human --parent <root epic>` | Awaiting a person. |
| `bd dep list <checkpoint>` | Checkpoint contributors. |
| `bd list --type decision --all --label topic:<slug>` | Decision log. |
| `bd list --status deferred --label topic:<slug>` | Topic backlog. |
| `bd gate list` | Upstream waits. |
| `$HOME/.agents/bin/board-health [<root epic>]` | Lead counts, dispatch queue size, items outside epics, `waiting` labels (use `blocks`), `in_progress` start age, expired/missing heartbeats and unknown activity. |
| `bd dep cycles` | Dependency-cycle check before dispatch. |

### Limits

- `bd ready` returns 100 rows; use `--limit 0` for inventories.
- Heartbeat between long steps with `bd heartbeat <id>`; claims lapse after
  five minutes without it. Board owner reclaims with `bd reclaim --id <id>`
  once `worker-last-use` no longer lists the worker (idle 30+ minutes) and the
  platform shows the worker ended. Use `$HOME/.agents/bin/worker-last-use`.
- Pass `--actor <mode or worker>` on writes. `bd close` refuses actors other
  than the assignee; inspect changes with `bd history <id> --events`.
- Give `bd create` a description and `bd close` a reason of 20+ characters.
