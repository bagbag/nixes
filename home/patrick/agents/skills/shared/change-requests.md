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
| `in_review` | Agent review, or checkpoint review by an agent (metadata `checkpoint` is set). |
| `needs_acceptance` | Waiting for the user: a finished CR (`look` `before`) or a user design checkpoint. Shown as "to accept". |
| closed | Landed, or rejected unlanded. |

- **Metadata:** `look` (`before`: lands on the user's Accept; `after`: lands
  after agent review), `view` (`code`: the user reads the diff; `result`: walked through the
  outcome), `checkpoint` (`agent|user`: a
  design checkpoint, cleared when passed), `deep_review` (the path a review
  escalated, removed by the deep-review), `base` (target or
  CR), `base_sha` (fork point, set at creation and after every rebase),
  `setup_sha`, `check` and `review` = {tip, baseTip, result, at}.
- **Settings** (project bd config): `target`, `setup`, `checks`, `look`,
  `view`, set only through `board setup --target … --setup … --checks … --look
  … --view …`. `setup` and `checks` name scripts kept in the project. A new
  CR takes the defaults; its own `look` or `view` only overrides them (clear
  the ones a changing `board setup` lists); a bad or missing
  value fails closed where used; `board check` lists them. The `checks` exit
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
- **Git authorization:** the user's explicit authorization, for a session
  holding a CR (and its workers) under the work, review or decide protocol,
  and only for these commands:
  - in that CR's worktree on `cr/<id>`: `git mv`, `git add`, one commit per
    pass, and resolving the files of a conflict that `board handover` or
    `board cr refresh` stops on (edit, `git add`), then rerunning that command,
    which continues the rebase;
  - the git steps of `board claim`, and of `handover` and `board cr refresh` on the
    held CR; `board cr land` only in a deciding session's Accept. A reviewer's
    passing `handover` of a `look` `after` CR also lands it;
  - in a deciding session, with the user: the git steps of `board review
    open`, `board cr edits` (`--commit`, and `--merged` after the user
    confirms a conflict merge on their edit commit) and `board ratify`, and
    resolving such a conflict with the user.
  Removing an unlanded CR's worktree or branch needs the user's confirmation.
  A land refused for the user's uncommitted edits (`land blocked`): ask the user to commit or move them;
  never restore, stash or commit them yourself.
- **Claim** creates the worktree (branch from `base`), assigns and runs
  setup. A worktree failure leaves the CR unclaimed; a setup failure keeps the
  claim and blocks hand-over until the holder reruns setup by claiming again.
- **Items:** a worker claims an item of the held CR, commits its pass on
  `cr/<id>` (one commit per pass; no git notes), then
  `board close <item> --reason "<sha>: <what>"`. Items carry no review of
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
- **Review:** one agent review per CR, plus the checkpoints planning states on
  it. The agent review's pass holds for the (tip, base tip) it was given on,
  like a check; after a base change the refresh triage keeps it or sends the
  CR back to `in_review`.
  The user's edit commits (accept.md User review) keep it, rebased too, or merged with
  the user's confirmation (Rebase); any other new commit voids it. A CR whose own commits are all such user edits needs no
  agent review: it lands on the user's Accept once its gate passes.
- **Waiting and stacks:** item edges lift to their CRs; items in a CR order
  only that session's work. A CR waits while a CR it depends on is not landed,
  except one in `needs_acceptance` that is no user design checkpoint: the CR
  stacks on it (`base` = that CR). At most one unlanded parent, else wait for
  the rest. Parents in agent review, at any checkpoint, `open` or in work are
  waited for, so in `look` `after` projects children wait for the landing.
  Closed means landed. A returned parent holds its children: they cannot
  land and their reviews wait. A child's Accept waits until its parent has
  landed; its Return and Reject do not.
- **Rebase:** always `rebase --onto <current base tip> <base_sha>`. A child
  follows a rebased parent through its own holder or refresher, never the
  parent's. A rebase the board started and stopped on a conflict stays the
  CR's: `board claim` accepts the CR mid-rebase, and `handover` or `cr refresh`
  continues it once its files are resolved and added (only one whose target is
  the recorded `rebase_onto`). A conflict on a commit of the user's edits
  (`board cr edits`, a ratification follow-up) is merged by a deciding session
  with the user; on the user's confirmation the board
  records the merged commit as the user's edit in place of the pre-rebase one,
  otherwise it counts as an agent change. A rebase,
  merge, cherry-pick, revert or bisect the board
  did not start takes the CR out of the claim queue and shows on its pane row
  and in `board check`; the board never continues or aborts it, its owner ends
  it. Uncommitted changes alone keep a CR claimable.
- **Shared append-lists:** design away files that parallel CRs would each add
  entries to (changelogs, registries, catalogs, route or export lists): each
  change adds its own file, found by naming convention or composed by a
  generator in the project's build or release. Ordinary code edited often and
  generated files (lockfiles) are not such lists. A review flags a new one.
- **Nothing to merge:** a CR whose branch holds no commit of its own and is
  at no design checkpoint lands when its review passes, in either `look`,
  without the Accept and without a ratification. Plan work that changes no
  code as a no-code task ([Work items](../shared/board-core.md#work-items)).
- **Ratification:** after a `look` `after` landing, or an agent design
  checkpoint pass in such a project, the child task `Ratify: <CR title>` sits
  in `needs_ratification` under the closed CR and blocks nothing; the user's
  verdict goes through `board ratify` (accept.md Ratification).
- **User review:** from `board review open` until the user's Accept or Return
  (ratification: verdict), refresh and agent steps leave the item alone; Open
  does not refresh it. Opening, reading and recording edits: accept.md User
  review.

| Command | Effect |
|---|---|
| `board handover <cr> "<evidence>" [<gate>]` | Rebases onto the base tip, runs setup and the gate, stores the check. `in_review`, or `needs_acceptance` when `checkpoint` is `user`; the worktree stays. The reviewer's pass is `handover` again: it stores the review, then `needs_acceptance` (`look` `before`), landed (`look` `after`, or a CR with nothing to merge), or `open` for planning (agent checkpoint; in a `look` `after` project also a design ratification). |
| `board return <cr> "<findings>"` | `open`, unassigned; also the user's "changes". |
| `board cr refresh <cr> [--review-holds] [<gate>]` | Rebases, reruns setup and the gate, stores the check, prints `git range-diff` and the incoming file list (for `cr-refresh`); for a CR whose review is stale both are measured since the review, not since the last refresh. `--review-holds` (the triage found no link) re-stamps the review for the new (tip, base tip) when the gate passes and each reviewed commit replayed cleanly (edit commits aside). |
| `board cr land <cr> [--tip <sha>]` | Lands the CR's tip (`--tip`: the tip the user reviewed; a short sha is accepted) when base is the target and check (full, or the `board cr edits` gate result, for exactly this tip) and review are `current` and passing. A `look` `after` CR on a `needs_acceptance` parent waits marked `after <base>`; landing the parent lands each such child whose check and review still match, else leaves it as refresh work. Advances `custom.board.target`. Removes worktree and branch; stacked children get `base` = target; `look` `after` creates the ratification, unless nothing was merged. |
| `board cr reject <cr> "<reason>"` | Closes unlanded; items reopen, children return to planning. Branch `cr/<id>` and worktree stay until the user confirms deletion (the only copy). |
| `board unclaim <cr>`, `board take <cr>` | Release, take over. `take` clears the taker's seen tip. |

Close a CR only through `board cr land` or `board cr reject`.
