# Accept protocol

Entry: [decide.md](decide.md#accept) Accept. Read `$HOME/.agents/skills/shared/change-requests.md` for Git authorization and the CR model.

1. **Claim** a CR, ratification or milestone: `board claim <id>`.
   Output: `claimed <cr> (look <look>, view <view>, checkpoint <c>); author
   <actor>`, `claimed <id> (milestone)`, or `epic <id>`.
2. **Evidence.** Read `$HOME/.agents/skills/shared/acceptance.md`; check the
   named evidence under its
   [Evidence and gates](../../shared/acceptance.md#evidence-and-gates). For a
   code CR, inspect the check shown for the current tip. A conflict on the
   user's edit commit follows change-requests.md Rebase.
   Note the tip and base the walkthrough starts on. For a user design checkpoint, note the
   `design hash` the claim printed.
   Output: one line per gate: command, result; check state and tip, or the
   design hash.
3. **Walk through** with the user under
   [Asking the user](../../shared/asking.md#asking-the-user), by the CR's
   `view`: `code`, the row's delta since the user's last look and its incoming
   commits. For `result`, show the outcome. A user checkpoint: a [Round](decide.md#round) (`start round --discussion --subject <cr>`);
   its pre-pass report is the walkthrough (verdict and findings first, then the
   design). A ratification: the
   landed result, in its user review or at the result. If the refresh changed
   the CR meanwhile, show the range-diff before continuing. Open with the
   defaults its hand-over lists; the user keeps or changes each. After each
   answer, re-check the walkthrough's open verdicts under
   [Changed premises](../../shared/decision-protocol.md#changed-premises).
   Output: the walkthrough; for a design, the round's answers.
4. **Land or return.**
   - **Accept:** `board cr land <cr> --tip <tip> --base <base>` with the pair
     shown at Accept.
     **Accept with edits** (the user's commits since Open or uncommitted
     changes in the review folder; the prompt names the `board cr edits`
     line): run that line and read the edits like a reviewer. On a likely
     mistake (a missed rename, a broken reference) stop and ask the user before
     landing; never change the edits. Pick the gate by stakes: none for docs
     (`--no-gate`), a targeted command (`--gate`), or the project's checks
     (`--checks`). Commit with that line plus `--commit -m "<msg>" <gate>`, then
     show the newly checked pair and any delta before running Accept. If the
     gate fails, tell the user what `board` printed.
   - **Review:** the user's Review action (or
     `board cr request-review <cr> ["<reason>"]`) sends the change since the last
     review to agent review.
   - **Design checkpoint:** name the outcome the round's answers entail for
     one confirmation. Nothing changes the design: `board cr land <cr>
     --checkpoint --design <hash>` (the hash from step 2). Otherwise
     `board return <cr> "<records>"`.
   - **Changes wanted:** talk the root fix through with the user, then
     `board return <cr> "<findings>"`; add follow-up items to the CR.
     **Return with edits:** `board cr edits <cr> --tip <tip> --commit -m
     "<msg>" --no-gate "returned"`. Claim it again if it went to agent review,
     then run `board return <cr> "<findings>"`.
   - **Rejected:** `board cr reject <cr> "<reason>"`; delete branch `cr/<id>` and its worktree only on the user's
     confirmation (they hold the only copy).
   - **Ratification:** `board ratify <id> yes|edits|no` with the user's
     verdict. `edits`: read the edits first, as
     for an Accept, and pick the gate the same way; the follow-up CR it starts
     waits for the user's Accept and lands with `board cr land` like any CR.
     `no`: ask what the user wants (fix or revert); `board ratify` files it as
     the follow-up CR.
   - **Epic, milestone:** close on the user's acceptance
     (`board close <id> --reason "<verdict>"`). Otherwise for an epic, create
     the findings as items under it; for a milestone, as members, and unclaim
     it (`board unclaim <id>`).
   When the item received a ruling, check that the rule sits in its owner and
   every conflict became a question.
   Output: `landed <cr>`, `checkpoint passed <cr>`, `returned <cr>`,
   `rejected <cr>`, `closed <id>` or `findings <ids>`.

**Stop:** the user rejects the CR or result: return it, reject it, file the
findings under the epic, or add them to the milestone. A required gate cannot
run: return it naming the unestablished claim. If the base moves after
the look, show the new Accept row to the user. For a failed check or conflict,
report the refusal and follow Rebase.

**Exit:** the item is closed, landed or returned, or the milestone has new
members.

## Ratification

The landing or design ratification task
([Change requests](../../shared/change-requests.md#change-requests)) takes the
user's verdict through `board ratify`: `yes` closes it (a default reason names the CR) and
removes its review worktree and `ratify/<id>` branch, refused while they
hold the user's edits; `edits` makes them the follow-up CR's (branch renamed
to `cr/<follow-up>`), commits uncommitted edits as the user's, rebased
onto the target and checked at once, waiting for the Accept (a rebase
conflict: change-requests.md Rebase, user's edits); `no` closes it with the reason and files the
follow-up the user wants (fix or revert).

## User review

The user reviews an item in its own worktree on its own branch.
`board review open <item>` opens it at the recorded tip. A ratification
opens branch `ratify/<id>` at the landed tip. The user's edits are their
commits after the opened tip plus uncommitted changes. Before Accept or
Return, use `board cr edits` to commit the uncommitted changes as the user's
and record all of their edits. `board show <item>` names whether it is open for review
and whether the user edited it.

## Commands

| Command | Effect |
|---|---|
| `board cr land <cr> --checkpoint --design <hash>` | The user's design checkpoint accept: closes the in-review design items, returns the CR to `open`, and clears the checkpoint for planning; nothing lands. Accepted by autopilot, it also files a `design` ratification. `<hash>` is the `design hash` `board claim <cr>` printed, still matching the design items' description, design, acceptance and notes. |
| `board cr edits <cr> --tip <sha> [--commit …]` | Prints, or with `--commit` commits and records as the user's, the user's edits in the CR's review; flags and gates: `board cr edits --help`. A failing gate keeps the commit and the CR waits for the user. |
