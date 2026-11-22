## Change requests

A change request (CR) is the one claimed, reviewed and landed unit
([Cut work](../role/protocols/plan.md#cut-work) sizes it). Its work items are
children (`--parent <cr>`); topic epics parent CRs. The board is the local
queue: no GitHub PRs, no agent pushes. Holds, routing and hand-over:
[Board core](board-core.md) (`$HOME/.agents/skills/shared/board-core.md`);
queue order and refresh work: [Board coordination](board-coordination.md).

| Status | Meaning |
|---|---|
| `open` | Ready, or returned (worktree kept). |
| `in_progress` | Held by its session. |
| `in_review` | Agent review. |
| `needs_acceptance` | Waiting for the user: a finished CR (`look` `before`). Shown as "to accept". |
| closed | Landed, or rejected unlanded. |

- **Metadata:** `look` (`before`: lands on the user's Accept; `after`: lands
  after agent review), `view` (`code`: the user reads the diff; `result`: walked through the
  outcome), `deep_review` (the path a review
  escalated, removed by the deep-review), `base` (target or
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
- **Claim** creates the worktree (branch from `base`), assigns and runs
  setup. A worktree failure leaves the CR unclaimed; a setup failure keeps the
  claim and blocks hand-over until the holder reruns setup by claiming again.
- **Items:** a worker claims an item of the held CR, commits its pass on
  `cr/<id>` (one commit per pass; no git notes), then
  `agents board close <item> --reason "<sha>: <what>"`. Items carry no review of
  their own.
- **Check:** valid for the (branch tip, base tip) pair it ran on, recorded only
  from a clean tree. Queue state: `current`, `stale` (base moved), `conflict`
  (`git merge-tree --write-tree` dry run), `failed`, `unchecked`. Rule "no new
  failures": the project check prints one `file code` line per failure; it
  passes when no (file, code) count rises from the base to the tip. The
  stored check is the CR's gate evidence while `current`; a reviewer
  reproduces a decisive check in the worktree on the tip under review.
  Every verb that stores a check (`handover`, `cr refresh`, `cr edits`,
  `ratify … edits`) takes one gate option: `--checks` (the default),
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
- **Waiting and stacks:** declare outside work and gate waits on the CR they
  hold. Use links within a CR to order that session's items. See
  [Questions and rulings](board-core.md#questions-and-rulings) for decision
  holds. A wait on a work item, a design included, waits on its CR's landing. A CR
  waits while a CR it depends on is unlanded,
  except one in `needs_acceptance` that is not design-only (every work item a
  `design`): the CR stacks on it (`base` = that CR); a dependent of a
  design-only CR waits until it lands. At most one unlanded parent, else wait for
  the rest. Parents in agent review, `open` or in work are
  waited for, so in `look` `after` projects children wait for the landing.
  Closed means landed. A returned parent holds its children: they cannot
  land and their reviews wait. A child's Accept waits until its parent has
  landed; its Return and Reject do not.
- **Rebase:** always `rebase --onto <current base tip> <base_sha>`. A child
  follows a rebased parent through its own holder or refresher, never the
  parent's. A rebase the board started and stopped on a conflict stays the
  CR's: `agents board claim` accepts the CR mid-rebase, and `handover` or `cr refresh`
  continues it once its files are resolved and added (only one whose target is
  the recorded `rebase_onto`). A conflict on a commit of the user's edits
  (`agents board cr edits`, a ratification follow-up) is merged by a deciding session
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
  without the Accept and without a ratification. Plan work that commits
  nothing here as a no-commit task ([Work items](../shared/board-core.md#work-items)).
- **Ratification:** after a `look` `after` landing, a child task titled
  `<CR title>` sits in `needs_ratification` under the CR and blocks nothing.
  The board creates one only when no landing ratification is currently
  `needs_ratification`; a closed one does not block a later review. The user's verdict goes through
  `agents board ratify` (accept.md Ratification).
- **User review:** from `agents board review open` until the user's Accept or Return
  (ratification: verdict), refresh and agent steps leave the item alone; Open
  does not refresh it. Opening, reading and recording edits: accept.md User
  review.

| Command | Effect |
|---|---|
| `agents board handover <cr> "<evidence>" [<gate>] [--no-agent-review "<reason>"]` | Rebases onto the base tip, runs setup and the gate, stores the check. Author work enters `in_review` by default. The [eligible author flag](acceptance.md#review-policy) sends it to `needs_acceptance`; the flag shows its reason. A reviewer pass records coverage and goes to `needs_acceptance` (`look` `before`) or lands (`look` `after`, or a CR with nothing to merge). |
| `agents board return <cr> "<findings>" [--ruling <id>]` | `open`, unassigned; also the user's "changes". `--ruling`: the planner holding that released ruling returns an unclaimed review ([Released rulings](../role/protocols/plan.md#released-rulings)). |
| `agents board cr request-review <cr> ["<reason>"]` | From Accept, send the change since its last review to agent review. |
| `agents board cr refresh <cr> [<gate>]` | Rebases and reruns setup and the gate. An uncovered agent-reviewed result goes to agent review. |
| `agents board cr land <cr> --tip <sha> --base <sha>` | Pass the tip and base shown at Accept. Land rebases and checks first when the check is not a pass for that pair. Land only a covered series with a passing check. If the base has moved since the look, land refuses and shows the incoming commits. A `look` `after` CR on a `needs_acceptance` parent waits marked `after <base>`; landing the parent lands each such child whose check and coverage still match, else leaves it as refresh work. Advances `custom.board.target`. Removes worktree and branch; stacked children get `base` = target; `look` `after` creates the ratification, unless nothing was merged. |
| `agents board cr reject <cr> "<reason>"` | Closes unlanded; items reopen, children return to planning. Branch `cr/<id>` and worktree stay until the user confirms deletion (the only copy). |
| `agents board unclaim <cr>`, `agents board take <cr>` | Release, take over. Your own work in progress needs `--resume "<next action>"`, which the next `agents board claim` prints. `take` clears the taker's seen tip. |

Close a CR only through `agents board cr land` or `agents board cr reject`.
