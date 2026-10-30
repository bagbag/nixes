## Board coordination (beads)

Deciding and planning sessions: epics, milestones, recorded rulings, deferrals
and upstream waits. The board model is [Board core](../shared/board-core.md)
(`$HOME/.agents/skills/shared/board-core.md`).

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
- When release checks must run on the finished scope, members block a
  `<release> scope` milestone instead, and it blocks the first checks.
- A member epic brings all its descendants; file work that ships later under
  another outcome.
- Membership orders work and never cuts it: P0 items first, then milestone
  work, then the rest, each by priority.
- Place each new item: a member when the goal owner's criterion covers it.
  Move work in or out by adding or removing its edge.
- When the milestone turns ready, a deciding session walks the user through
  it, closes it on acceptance and reconciles the goal owner under
  project-memory.

### Rulings

- At decision time, write the record with `board record <id> <file>`, which
  moves the packet into the first comment and sets status `decided`
  (autopilot: `--status needs_ratification`). The file holds these `##`
  sections, which `board bd lint` checks before release: `Question`,
  `Alternatives Considered`, `Decision`, `Rationale` (with provenance: user or
  the ruling session's role, and date) and `Rule owner`.
- Record each ruling you make as "ruling — rejected: <alternative>, fails
  <cleanliness test, principle or correctness property>". For a consequential
  ruling without a question, create and answer one at once.
- Open a revision with
  `board revise <old> --title "<question>" --body-file <packet>`; for one rule
  of a record add `--partial "<rule>"`, and the rest stays in force. Its
  record restates the rule in full. `board release` supersedes the old record; autopilot runs
  `board supersede <old> --with <new>` when it records the revision. A
  revision question blocks only the work items whose part it would change.
- On the user's ratification, the claiming deciding session closes a
  `needs_ratification` record with the ratification as reason; a reversal
  becomes a revision record.
- Owner text contradicting a newer released ruling is a missed owner write:
  the ruling binds; fix the owner.
- Write each rule into its owner under project-memory
  [Durable owners](../shared/project-memory.md#durable-owners)
  (`$HOME/.agents/skills/shared/project-memory.md`).

### Deferrals and environment facts

| Item | Lifecycle |
|---|---|
| Deferral | `board bd defer <id> --reason "<revisit condition>"`, plus `--until <date>` for a date condition (bd undefers it then); undefer other conditions on named new evidence. Deferred items are the project backlog. |
| Environment fact | `board bd remember --key <key>` for temporary repository-wide facts needed by every current session, a user's broad stop (area, paths, kind of action) included with its words and date; state a removal condition; remove with `board bd forget`. |

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
