---
name: staged-review
description: >-
  Review a staged or committed change set in rounds, each against the
  previous snapshot and brief, with one authoritative verdict and brief per
  round. Use when the user asks to review, re-review or run "round N" of
  staged changes, or to review an implementation against a previous round's
  brief; not for a one-off diff or PR.
---

# Staged review

A round reviews the delta since the previous round, checks it against that
round's brief, and gives the next implementer one authoritative file. Another
agent implements; the user stages and commits.

## Authority and evidence

- Treat the captured target snapshot as the source of the verdict. Read and
  search that snapshot, not the working tree.
- Treat every snapshot as read-only evidence.
- Label reused check results *implementer-reported*, with command, outcome and
  revision. Label checks you run *reviewer-verified*.
- Ground findings in current source; drop false positives and intentional
  choices. Verify claims in comments, TSDoc, README and CHANGELOG against the
  code, including line references and signatures.

## Scope and snapshot

1. Before round one, record the review base and target. Use the index as the
   staged target. For committed work, name the base explicitly: a commit, a
   merge-base or `HEAD`.
2. Capture the tree identity first, then create the snapshot from it:

   ```sh
   tree=$(git write-tree)
   idx=$(mktemp -u)
   GIT_INDEX_FILE=$idx git read-tree "$tree"
   GIT_INDEX_FILE=$idx git checkout-index -a --prefix=/tmp/<repo>-r<N>-index/
   rm -f "$idx"
   ```

   Use a directory that does not exist yet and record `$tree` in the verdict.
3. Take the delta with `git diff --stat <previous-tree> <tree>` and
   `git diff <previous-tree> <tree>`. For round one, diff against the recorded
   base. If the previous tree is gone, diff against its snapshot directory. If
   both are gone, say so and review against the recorded base.
4. List worktree-only changes separately as pending staging: modified files
   (`git status --porcelain`: ` M`, `MM`) and untracked files referenced by the
   delta or brief. They cannot satisfy the brief.

## Adjudicate the brief

- Account for every file in the delta: map it to a brief item or mark it
  unbriefed, then review unbriefed changes on their merits.
- Settle every brief item, including items whose files are unchanged, by
  checking required content in the snapshot, not only the diff.
- Treat the implementer's record as claims; verify every load-bearing claim by
  searching or reading the snapshot.

## Verify pins

Reuse recorded tests, typechecks and builds. Run a check only when the record
cannot answer a question: a defeat probe, a pin suspected not to execute, a
claim contradicted by the snapshot, or results from another revision.

- For a behavioral fix, check that a pin covers every changed site. Prefer a
  final assertion proving execution reached the last site; name any short
  circuit that could let the pin pass without reaching the fix.
- Run defeat probes directly: one per site and one for the constraint that
  makes the pin load-bearing. The unmutated pin must pass; each mutation must
  fail for the intended behavioral reason. Check the error text; compile or
  import failure does not count.
- Prefer a disposable copy of the reviewed tree when the project runs there
  cheaply. Otherwise mutate in place only files whose worktree matches the
  index: back up the file, mutate it, run only the pin, restore the backup, and
  verify restoration with its checksum and `cmp`.

## Before issuing

- Check each proposed edit in the final brief against the skills, style guides
  and project instructions governing the target. Withdraw a brief item explicitly
  when it contradicts a governing source; do not charge the implementer for
  skipping it.
- Classify each open question in the final brief as ruled when the user's
  criteria leave one clean option, or as a user decision with lettered options,
  a recommendation, and the case for and against each.

## Write and close the round

- Write the round under `.scratch/<topic>/<arc>/round<N>/` and follow the
  artifact schema in [Round artifacts](#round-artifacts).
- Carry every earlier finding ID and its status (open, fixed, withdrawn or
  ruled no-change) in the finding ledger. Record withdrawals and supersessions
  there, not by editing older files.
- Carry user rulings forward. Re-raise a closed item only when new evidence
  changes its case, and name that evidence.
- When the user asks for a commit after review, compare `git write-tree` with
  the last reviewed tree first. Report anything staged after review and get the
  user's confirmation before committing it.
- Report the verdict, blockers, decisions and recommendations, work the user
  still owns (staging and committing), pending-staging list and whether another
  round is needed.

## Round artifacts

- `verdict-round<N>.md` is the only file marked **START HERE**. Include scope
  (base, target, tree IDs and delta counts), verdict, finding ledger, per-item
  brief conformance, checks labelled by source, unverified items and reasons,
  decisions, and a numbered implementation brief with an explicit
  **Not in this brief** list.
- Put supporting evidence in separate files and banner them as read-only
  evidence. Leave earlier rounds' evidence unchanged.
- The one exception to leaving older files unchanged: give the previous entry
  point a one-line superseded banner pointing to the new verdict. Search the
  arc for `START HERE` and confirm exactly one active entry point.

## Definitions

- **Pin:** a test that locks a fix in place.
- **Defeat probe:** a deliberate reversal of one fix site that proves its pin
  fails without the fix.
