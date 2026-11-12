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
  CR takes the defaults; a bad or missing
  value fails closed where used; `board check` lists them. The `checks` exit
  status is a contract: 0 = ran, the printed `file code` lines are the
  failures; 1 = ran with failures, at least one line printed; any other
  status, or 1 with no line, is a broken check and fails closed.
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
    pass, and resolving a conflict that `board handover` or `board refresh`
    stops on, then `git rebase --continue`;
  - the git steps of `board claim`, and of `handover` and `refresh` on the
    held CR; `board land` only in a deciding session's Accept. A reviewer's
    passing `handover` of a `look` `after` CR also lands it.
  Removing an unlanded CR's worktree or branch needs the user's confirmation.
- **Claim** creates the worktree (branch from `base`), assigns and runs
  setup. A worktree failure leaves the CR unclaimed; a setup failure keeps the
  claim and blocks hand-over until the holder reruns setup by claiming again.
  Hand-over and refresh rerun setup when the base commit differs from
  `setup_sha`.
- **Items:** a worker claims an item of the held CR, commits its pass on
  `cr/<id>` (one commit per pass; no git notes), then
  `board bd close <item> --reason "<sha>: <what>"`. Items carry no review of
  their own.
- **Check:** valid for the (branch tip, base tip) pair it ran on, recorded only
  from a clean tree. Queue state: `current`, `stale` (base moved), `conflict`
  (`git merge-tree --write-tree` dry run), `failed`, `unchecked`. Rule "no new
  failures": the project check prints one `file code` line per failure; it
  passes when no (file, code) count rises from the base to the tip. The base
  result is cached per base commit; a green project has an empty base. The
  stored check is the CR's gate evidence while `current`; a reviewer
  reproduces a decisive check in the worktree on the tip under review.
- **Review:** one agent review per CR, plus the checkpoints planning states on
  it. The agent review's pass holds for the (tip, base tip) it was given on,
  like a check; after a base change the refresh triage keeps it or sends the
  CR back to `in_review`.
- **Waiting and stacks:** item edges lift to their CRs; items in a CR order
  only that session's work. A CR waits while a CR it depends on is not landed,
  except one in `needs_acceptance` that is no user design checkpoint: the CR
  stacks on it (`base` = that CR). At most one unlanded parent, else wait for
  the rest. Parents in agent review, at any checkpoint, `open` or in work are
  waited for, so in `look` `after` projects children wait for the landing.
  Closed means landed. A returned parent holds its children: they cannot
  land and their reviews wait.
- **Rebase:** always `rebase --onto <current base tip> <base_sha>`. A child
  follows a rebased parent through its own holder or refresher, never the
  parent's.
- **Ratification:** after a `look` `after` landing, or an agent design
  checkpoint pass in such a project, the child task `Ratify: <CR title>` sits
  in `needs_ratification` under the closed CR and blocks nothing; the user's
  "no" becomes a follow-up CR.

| Command | Effect |
|---|---|
| `board handover <cr> "<evidence>"` | Refuses open items, uncommitted changes, conflict state, failed setup or checks. Rebases onto the base tip (a conflict: resolve, rerun), runs setup and checks, stores the check. `in_review`, or `needs_acceptance` when `checkpoint` is `user`; the worktree stays. The reviewer's pass is `handover` again: when the tip moved since the reviewer looked (or no look is recorded) it prints the range and records nothing, so the reviewer looks and passes again; otherwise it stores the review, then `needs_acceptance` (`look` `before`), landed (`look` `after`), or `open` for planning (agent checkpoint; in a `look` `after` project also a design ratification). |
| `board return <cr> "<findings>"` | `open`, unassigned; also the user's "changes". |
| `board refresh <cr> [--review-holds]` | Rebases, reruns setup and checks, stores the check, prints `git range-diff` and the incoming file list (for `cr-refresh`); for a CR whose review is stale both are measured since the review, not since the last refresh. Refuses while another session holds the CR. `--review-holds` (the triage found no link): re-stamps the review for the new (tip, base tip); refused unless the check passes, the commits are patch-identical to the reviewed range, and the base and tip are those the last refresh showed (otherwise it prints the new incoming list and asks for a new triage). |
| `board land <cr> [--tip <sha>]` | Refuses unless the base is the target, check and review are `current` and passing, no item is open, no worktree is rebasing or bisecting the target, and the branch is at `--tip` (the tip the user reviewed; a short sha is accepted). A `look` `after` CR on a `needs_acceptance` parent waits marked `after <base>`; landing the parent lands each such child whose check and review still match, else leaves it as refresh work. Advances `custom.board.target` (`merge --ff-only` where checked out, else `update-ref`); overlap with uncommitted edits there refuses (`land blocked: <paths>`). A landing that stopped midway (its tip already on the target, recorded by `land` or checked) closes the CR on the next board read; a failure there shows as a `cr-landing` deviation in `board check`. Removes worktree and branch; stacked children get `base` = target; `look` `after` creates the ratification. |
| `board land <cr> --checkpoint --design <hash>` | The user's design checkpoint accept: `open`, checkpoint cleared, to planning; nothing lands. Refuses unless `<hash>` is the `design hash` `board claim <cr>` printed and still matches the design items' description, design, acceptance and notes. |
| `board reject <cr> "<reason>"` | Closes unlanded; items reopen, children return to planning. Branch `cr/<id>` and worktree stay until the user confirms deletion (the only copy). |
| `board unclaim <cr>`, `board take <cr>` | Release, take over. `take` refuses the author's own CR in `in_review` and clears the taker's seen tip. |

Close a CR only through `land` or `reject`; `board bd close` refuses one.
