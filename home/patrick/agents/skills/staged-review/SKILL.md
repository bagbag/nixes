---
name: staged-review
description: >-
  Run iterative review rounds over a repository's staged or committed change
  set by snapshotting the index and diffing it against the previous round's
  snapshot. Use when the user asks to review, re-review, or run "round N" of a
  review of staged changes, or to review an implementation against the brief a
  previous round issued. Produces one authoritative verdict per round with a
  brief for the implementing agent. Not for a one-off review of a single diff or
  pull request.
---

# Staged review

A round reviews what changed since the last round, checks it against the brief
that round issued, and hands the next implementer a single authoritative file.
Another agent does the implementation, and the user stages and commits.

## 1. Scope and snapshot

- Before the first round, record the review base and target. For staged work
  the target is the index. For committed work, name the base (a commit, a
  merge-base, or `HEAD`) explicitly, because comparing a clean index with
  `HEAD` shows nothing.
- Capture the tree identity first, then build the snapshot from it, so the two
  cannot disagree:

  ```sh
  tree=$(git write-tree)
  idx=$(mktemp -u)
  GIT_INDEX_FILE=$idx git read-tree "$tree"
  GIT_INDEX_FILE=$idx git checkout-index -a --prefix=/tmp/<repo>-r<N>-index/
  rm -f "$idx"
  ```

  Use a directory that does not exist yet, and record `$tree` in the verdict.
  Treat every snapshot as read-only evidence.
- Take the delta from Git: `git diff --stat <previous-tree> <tree>` and
  `git diff <previous-tree> <tree>`. Round 1 diffs against the recorded base.
  Unreferenced trees are eventually pruned by `git gc`, and `/tmp` is cleared
  on reboot. If the previous tree is gone, diff against the previous snapshot
  directory. If both are gone, say so and review against the recorded base.
- List worktree-only changes separately, as pending staging: modified files
  (`git status --porcelain`: ` M`, `MM`), and untracked files that the delta or
  the brief refers to. A commit from the index would not carry them,
  so they cannot satisfy the brief.

## 2. Adjudicate against the snapshot

- The snapshot owns the verdict. Grep and read it, not the working tree.
- Account for every file in the delta: map each one to a brief item or name it
  as unbriefed, and review unbriefed changes on their merits.
- Settle each brief item by checking the snapshot for the required content.
  An unchanged file can mean "already correct" or "skipped", which are opposite
  verdicts, so the diff alone cannot settle it.
- Treat the implementer's record as a list of claims. Verify each load-bearing
  claim with a grep or a read. Records have reported omitted work as landed.
- Ground every finding in current source. Drop it if it is a false positive or
  an intentional design choice.
- Check each claim a comment, TSDoc block, README, or CHANGELOG entry makes
  against the code it describes, including line references and signatures.

## 3. Verify pins

A *pin* is the test that locks a fix in place. A *defeat probe* deliberately
reverts one site of the fix to prove that the pin fails without it.

- Reuse the implementer's recorded test, typecheck and build results, and label
  them *implementer-reported*, with the command, the outcome, and the revision
  they ran against. Do not re-run everything. Run a check when it answers a
  question the record cannot: a defeat probe, a pin you suspect never executes,
  a claim the snapshot contradicts, or results recorded against different source
  than the reviewed tree. Label those results *reviewer-verified*.
- For a behavioural fix, look for a pin whose shape covers every site the fix
  touches. A final assertion that proves execution reached the last site is
  stronger than any number of probe runs. Name any short-circuit that would let
  the pin pass without reaching the fix.
- Run defeat probes directly, one per site, plus one for the constraint that
  makes the pin load-bearing. The unmutated pin must pass, and each mutation
  must make it fail for the intended behavioural reason. Check the error text:
  a compile or import failure proves nothing about coverage. Prefer a disposable
  copy of the reviewed tree when the project runs there cheaply. Otherwise
  mutate in place, and only on files whose worktree matches the index. Back up
  the file, mutate it, run only the pin, restore from the backup, and verify
  the restore against the backup's checksum and with `cmp`.

## 4. Check the brief before issuing it

- Check every proposed edit against the skills, style guides, and project
  instructions that govern the target file. When a previous brief item
  contradicts one of them, withdraw it explicitly instead of charging the
  implementer for skipping it.
- Classify each open question as ruled (one clean option under the user's
  stated criteria) or as a user decision with lettered options, a
  recommendation, and the case for and against each option.

## 5. Artifacts

Write the round to `.scratch/<topic>/<arc>/round<N>/`:

- `verdict-round<N>.md` is the only file marked **START HERE**. It holds the
  scope (base, target, tree ids, delta counts), the verdict, the finding ledger,
  per-item brief conformance, checks labelled by source, what was not verified
  and why, the decisions, and a numbered implementation brief with an explicit
  "not in this brief" list.
- The finding ledger carries every earlier finding ID forward with its status:
  open, fixed, withdrawn, or ruled no-change. Withdrawals and supersessions live
  there, not in edits to older files.
- Carry the user's rulings forward in the verdict. Do not re-raise a closed item
  unless new evidence changes its case, and name that evidence when you do.
- Put supporting evidence in its own files, bannered as read-only evidence.
  Leave earlier rounds' evidence unedited.
- The one exception is the previous entry point: give it a one-line banner
  saying it is superseded and pointing at the new verdict. Then grep the arc for
  `START HERE` and confirm that exactly one file is active.

## 6. Close

Report the verdict, any blockers, the decisions with their recommendations,
the work the user still owns (staging and committing), the pending-staging
list, and whether another round is needed.

When the user asks for a commit after a review, compare `git write-tree` with
the last reviewed tree first. Report anything staged after the review and get
the user's confirmation before committing it.
