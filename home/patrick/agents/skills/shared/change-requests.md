## Change requests

A change request (CR) is the one claimed, reviewed and landed unit
([Cut work](../role/protocols/plan.md#cut-work) sizes it). Its items are
children (`--parent <cr>`); a topic is a label. The board is the local
queue: no GitHub PRs, no agent pushes. Holds, routing and hand-over:
[Board core](board-core.md) (`$HOME/.agents/skills/shared/board-core.md`);
queue order and refresh work: [Board coordination](board-coordination.md).

| Status | Meaning |
|---|---|
| `open` | Ready, in work (held by its session) or returned (worktree kept). |
| `in_review` | Agent review. |
| `passed` | Review passed, landing pending: with `look` `before` it waits for the user's Accept (shown "to accept"); with `look` `after` it lands at once, or with its base. |
| `deferred` | Set aside ([Deferrals](board-coordination.md#deferrals-and-environment-facts)). |
| closed | Outcome `landed`, or `dropped` (rejected unlanded). |

Who holds it is the holder field, not a status; the model's tables print from
`agents board help` and each verb's `--help`.

- **Metadata:** `look` (`before`: lands on the user's Accept; `after`: lands
  after agent review), `view` (`code`: the user reads the diff; `result`: walked through the
  outcome), `deep_review` (the path a review
  escalated, set by `unclaim --deep-review`, cleared by the deep-review's handover or unclaim), `base` (target or
  CR), `base_sha` (fork point, set at creation and after every rebase),
  `setup_sha`, `check` and `review` = {tip, baseTip, result, at}.
- **Settings** (project bd config): `target`, `setup`, `checks`, `look`,
  `view`, set only through `agents board setup --target … --setup … --checks … --look
  … --view …`. `setup` establishes every prerequisite used by `checks`, and fails
  when one is missing; `checks` only checks. Setup and checks are commands run
  with `/bin/sh` in the checkout; board setup refuses one whose first word the
  shell cannot resolve. A new
  CR takes the defaults; its own `look` or `view` only overrides them (clear
  the ones a changing `agents board setup` lists); a bad or missing
  value fails closed where used; `agents board check` lists them. The `checks` exit
  status is a contract: 0 = ran, the `file code` lines on stdout are the
  failures; 1 = ran with failures, at least one such line; any other
  status, or 1 with no line, is a broken check and fails closed.
  Board-made commits and branch moves run no git hooks: put what a hook
  enforces in `checks`.
- **Worktree** `<main>/.worktrees/<cr-id>` on `cr/<cr-id>` (`<main>`: first
  entry of `git worktree list`; `board` excludes `.worktrees/` in
  `.git/info/exclude`: commit no ignore line). All board work for the CR,
  sessions and workers, runs in it. Edit `<main>` outside `.worktrees/` only
  on the user's direct ask; never `ExitWorktree` with remove. A worktree
  resolves packages missing from its install from `<main>/node_modules`:
  when a CR drops a dependency, check that nothing still imports it.
- **Git authorization:** AGENTS.md Authorized workflows. Resolve a conflict
  that `agents board handover` or `agents board cr refresh` stops on in the worktree (edit,
  `git add`), then rerun that command, which continues the rebase. `agents board cr
  edits --merged` follows the user's confirmation of a conflict merge on their
  edit commit; resolve such a conflict with the user.
  Removing an unlanded CR's worktree or branch needs the user's confirmation.
  A land refused for the user's uncommitted edits (`land blocked`): ask the user to commit or move them;
  never restore, stash or commit them yourself.
- **Claim** creates the worktree (branch from `base`), takes the hold and runs
  setup. A worktree failure leaves the CR unclaimed; a setup failure keeps the
  claim and blocks hand-over until the holder reruns setup by claiming again.
- **Items:** a worker of the holding session commits its pass on
  `cr/<id>` (one commit per pass; no git notes), then
  `agents board close <item> --reason "<sha>: <what>"`; `--outcome dropped` when
  a ruling made it moot. Items carry no holder or review of their own, and
  closing an item of a CR nobody holds is the user's or a deciding session's.
  Handover refuses while an item is open.
- **Check:** valid for the (branch tip, base tip) pair it ran on, recorded only
  from a clean tree. Queue state: `current`, `stale` (base moved), `conflict`
  (`git merge-tree --write-tree` dry run), `failed`, `unchecked`. Rule "no new
  failures": the project check prints one `file code` line per failure; it
  passes when no (file, code) count rises from the base to the tip. The
  stored check is the CR's gate evidence while `current`; a reviewer
  reproduces a decisive check in the worktree on the tip under review.
  Every verb that stores a check (`handover`, `cr refresh`, `cr edits`) takes one gate option: `--checks` (the default),
  `--gate <cmd>` (a targeted check) or `--no-gate <reason>` (none); a
  reviewer runs its own gates.
- **Review coverage:** a pass covers the series it reviewed (tip, base tip).
  A clean replay keeps it and the user's recorded edits stay covered (Rebase).
  A conflict resolution or new author commit sends an agent-reviewed CR back
  to agent review.
- **Convention changes:** when replacing a shared helper, move every use
  and delete the old helper so checks catch remaining uses in open CRs.
  For a new pattern or style rule, check the open CRs already past review
  at handover and comment on each CR that should adapt.
- **Waiting and stacks:** a wait is written on the waiter
  ([Dependencies](board-core.md#dependencies)); declare outside and gate waits
  on the CR (they hold it whole) and order a CR's own items by waits among them.
  A wait on another CR's item or on that CR is met when it lands, or when this
  CR stacks on it. A CR waits while a CR it depends on is unlanded, except one
  `passed` and waiting for the Accept: the CR stacks on it (`base` = that CR).
  At most one unlanded parent, else wait for the rest. Parents in agent
  review, `open` or in work are waited for, so in `look` `after` projects
  children wait for the landing. A wait is met only by a delivering close: a CR
  that lands, never one rejected (a reject, or a close as dropped, is refused
  while an open or deferred record waits on it, and no new wait names a record
  closed dropped, a question excepted). A returned parent holds
  its children: they cannot land and their reviews wait. A child's Accept waits
  until its parent has landed; its Return and Reject do not.
- **Rebase:** always `rebase --onto <current base tip> <base_sha>`. A child
  follows a rebased parent through its own holder or refresher, never the
  parent's. A rebase the board started and stopped on a conflict stays the
  CR's: `agents board claim` accepts the CR mid-rebase, and `handover` or `cr refresh`
  continues it once its files are resolved and added (only one whose target is
  the recorded `rebase_onto`). A conflict on a commit of the user's edits
  (`agents board cr edits`) is merged by a deciding session
  with the user; on the user's confirmation the board
  records the merged commit as the user's edit in place of the pre-rebase one,
  otherwise it counts as an agent change. A rebase,
  merge, cherry-pick, revert or bisect the board
  did not start takes the CR out of the claim queue and shows on its pane row
  and in `agents board check`; the board never continues or aborts it, its owner ends
  it. Uncommitted changes alone keep a CR claimable.
- **Shared append-lists:** design away files that parallel CRs would each add
  entries to (changelogs, registries, catalogs, route or export lists): each
  change adds its own file to one folder; a generator composes the files
  only where a program needs them as one file. Ordinary code edited often and
  generated files (lockfiles) are not such lists. A review flags a new one.
- **Nothing to merge:** a CR whose branch holds no commit of its own lands when its review passes, in either `look`,
  without the Accept. Plan work that commits
  nothing here as a no-commit task ([Work items](../shared/board-core.md#work-items)).
- **User review:** from `agents board review open` until the user's Accept or Return,
  refresh and agent steps leave the item alone; Open
  does not refresh it. Opening, reading and recording edits: accept.md User
  review.

| Command | Effect |
|---|---|
| `agents board handover <cr> "<evidence>" [<gate>] [--no-agent-review "<reason>"]` | Refuses while an item is open. Rebases onto the base tip, runs setup and the gate, stores the check. Author work enters `in_review` by default. The [eligible author flag](acceptance.md#review-policy) sends a `look` `before` CR to `passed`; the flag shows its reason. A reviewer pass records coverage and goes to `passed` (`look` `before`) or lands (`look` `after`, or a CR with nothing to merge). |
| `agents board return <cr> "<findings>" [--ruling <id>]` | `open`, unheld, one open item per finding; also the user's "changes". `--ruling`: the planner holding that in-force ruling returns an unclaimed review; its consequences become the items ([Released rulings](../role/protocols/plan.md#released-rulings)). |
| `agents board cr request-review <cr> ["<reason>"]` | From Accept, send the change since its last review to agent review. |
| `agents board cr refresh <cr> [<gate>]` | Rebases and reruns setup and the gate. An uncovered agent-reviewed result goes to agent review. |
| `agents board cr land <cr> --tip <sha> --base <sha>` | Pass the tip and base shown at Accept. Land rebases and checks first when the check is not a pass for that pair. Land only a covered series with a passing check. If the base has moved since the look, land refuses and shows the incoming commits. A `look` `after` CR on a `passed` parent waits marked `after <base>`; landing the parent lands each such child whose check and coverage still match, else leaves it as refresh work. Advances `custom.board.target`. Removes worktree and branch; stacked children get `base` = target. |
| `agents board cr reject <cr> "<reason>"` | Closes unlanded (`dropped`) once no item is open (close them dropped, or move them); change requests stacked on it return to planning. Branch `cr/<id>` and worktree stay until the user confirms deletion (the only copy). |
| `agents board unclaim <cr>`, `agents board take <cr>` | Release, take over. Your own work in progress needs `--resume "<next action>"`, which the next `agents board claim` prints. `take` clears the taker's seen tip. |

Close a CR only through `agents board cr land` or `agents board cr reject`.
