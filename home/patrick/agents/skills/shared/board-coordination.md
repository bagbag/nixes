## Board coordination (beads)

Deciding and planning sessions: topics, change requests in the queue,
milestones, recorded rulings and deferrals. The board model is
[Board core](../shared/board-core.md)
(`$HOME/.agents/skills/shared/board-core.md`).

### Topics

- A topic is a label (`topic:<topic-slug>`); there is no epic type. A
  [change request](../shared/change-requests.md#change-requests) carries its
  topic label and its work items sit under it; loose change requests carry
  none. `agents board create --graph` copies no labels from the parent: give
  each node its `topic:` label.
- A topic carries no rules, holds, status, item lists or history; history goes
  to comments, rules to their owners. An outcome that needs the user's
  judgment is a milestone whose acceptance names the user.

### Milestones

- Track each release checkpoint as one `milestone` item (`1.0-beta`). Its
  acceptance names the checkpoint's evidence and the user; the goal owner
  states which work belongs to it.
- Add members with `agents board move <change request> --to <milestone>`: a
  change request is part of a milestone, which waits on nothing. Everything a
  member waits on belongs to the milestone too. Make the last release step a
  member as well.
- When release checks must run on the finished scope, members go into a
  `<release> scope` milestone, and the first checks wait on it.
- A member change request brings its items; file work that ships later under
  another milestone.
- Membership orders work and never cuts it. `agents board claim` order: P0 items,
  then planning (in-force rulings, a `plan_first` CR, no-commit tasks), then milestone work, then reviewing
  (CR reviews and refresh work) and accepting, then the rest. Within
  each, priority, then kind (plan, review, refresh, accept, question,
  implement). A record counts
  at the highest priority of the open work waiting on it; a CR counts with its
  open items, and is milestone work when it or one of its parts is.
- Place each new item: a member when the goal owner's criterion covers it.
  Move work in or out by adding or removing its edge.
- When the milestone turns ready, a deciding session walks the user through
  it, closes it on acceptance and reconciles the goal owner under
  project-memory.

### Change-request queue

- **Accept queue:** `passed` CRs of `look` `before`: parents before the CRs stacked
  on them, then the `agents board claim` order without kind
  ([Milestones](#milestones)), then age (stacks:
  [Change requests](../shared/change-requests.md#change-requests)).
- **Unlock rank:** Within a tier and effective priority, take the larger
  unlock score, then the larger immediate solo count, then the claim order's remaining ties.
  Count one credit per work unit that can become dependency-ready. Divide
  it among its ready blockers when several contribute. Count solo and
  shared unlocks separately. A landing delivers its CR and its work items.
- **Check state** (`agents board queue`, `agents board health`, console): every live CR's
  check against the current refs.
- **Refresh work:** the first CR of the accept queue that lands, waits on no other CR and whose check is not
  `current` is claimable by `review` pulls as
  kind `refresh`; that CR only. Protocol: review.md
  [Refresh](../role/protocols/review.md#refresh).

### Rulings

- At decision time, write the record with `agents board ruling record <id> <file>`:
  it replaces the packet and sets status `decided`; an autopilot ruling or a
  standing two-way default uses `--unratified`, which releases it and files a
  related Confirm-or-revise question. `--replaces <old>[,<old>]` links each
  ruling it replaces, decided, released or closed after planning; each is
  superseded when the new ruling comes into force: at its release, or at once
  with `--unratified`. Rerun it after a stop; `agents board ruling supersede <old>
  --with <new>` alone for one rule or by hand. The file holds these `##` sections, which `agents board ruling record`
  checks: `Question`, `Alternatives Considered`, `Decision`, `Rationale` (with
  provenance: user or the ruling session's role, and date) and `Rule owner`;
  `--unratified` also requires `Reversal`.
- Record each ruling you make as "ruling — rejected: <alternative>, fails
  <cleanliness test, principle or correctness property>". For a consequential
  ruling without a question, create and answer one at once.
- Open a revision with
  `agents board ruling revise <old> --title "<question>" --body-file <packet> --holds <ids>|none`; the old ruling may be released or closed after planning. For one rule
  of a record add `--partial "<rule>"`, and the rest stays in force. Its
  record restates the rule in full. `agents board ruling release` supersedes a released
  old record. A revision
  question blocks only the work items whose part it would change.
- Owner text contradicting a newer released ruling is a missed owner write:
  the ruling binds; fix the owner.
- Write each rule into its owner under project-memory
  [Durable owners](../shared/project-memory.md#durable-owners)
  (`$HOME/.agents/skills/shared/project-memory.md`).

### Deferrals and environment facts

| Item | Lifecycle |
|---|---|
| Deferral | `agents board defer <id> --reason "<why>"`: someday, off the queue, blocked by nothing; `--until <day>` only shows it as due then. For CRs, tasks and questions (an item: move it into its own CR first). A condition on a record or event is a wait ([Dependencies](board-core.md#dependencies)); `defer` refuses one, and nothing waits on a deferred record. Only the deferrer undefers (`agents board undefer`): a planning session or autopilot its own, the user's through a lead or solo session. Deferred records are the backlog. |
| Environment fact | `agents board bd --raw --yes remember --key <key>` (no board command) for temporary repository-wide facts needed by every current session, a user's broad stop (area, paths, kind of action) included with its words and date; state a removal condition; remove with `agents board bd --raw --yes forget`. |
