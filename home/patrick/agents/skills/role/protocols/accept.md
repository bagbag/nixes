# Accept protocol

Entry: [decide.md](decide.md#accept) Accept. Read `$HOME/.agents/skills/shared/change-requests.md` for Git authorization and the CR model.

1. **Claim** a CR, ratification or milestone: `board claim <id>`.
   Output: `claimed <cr> (look <look>, view <view>, checkpoint <c>); author
   <actor>`, `claimed <id> (milestone)`, or `epic <id>`.
2. **Evidence.** Read `$HOME/.agents/skills/shared/acceptance.md`; check the
   named evidence under its
   [Evidence and gates](../../shared/acceptance.md#evidence-and-gates). For a
   code CR the stored check and review must be `current` for the tip you review:
   wait for the refresh a review session took, or run it yourself under the
   review protocol's [Refresh](review.md#refresh) steps 2-3 when none did
   (nothing refreshes one open in the user's review; Accept brings in a moved
   base; a conflict on the user's edit commit: change-requests.md Rebase).
   Note the tip the walkthrough starts on; for a user design checkpoint, the
   `design hash` the claim printed.
   Output: one line per gate: command, result; check state and tip, or the
   design hash.
3. **Walk through** with the user under
   [Asking the user](../../shared/asking.md#asking-the-user), by the CR's
   `view`: `code`, the diff `<base>..<tip>` (in the CR's user review, VS
   Code's Outgoing Changes, or the range-diff of a refresh); `result`, the outcome itself. A user
   checkpoint: a [Round](decide.md#round) (`start round --discussion --subject <cr>`);
   its pre-pass report is the walkthrough (verdict and findings first, then the
   design). A ratification: the
   landed result, in its user review or at the result. If the refresh changed
   the CR meanwhile, show the range-diff before continuing.
   Output: the walkthrough; for a design, the round's answers.
4. **Land or return.**
   - **Accept:** `board cr land <cr> --tip <tip>` (the tip the user reviewed;
     it ends the user's review).
     **Accept with edits** (the user's commits since Open or uncommitted
     changes in the review folder; the prompt names the `board cr edits`
     line): run that line and read the edits like a reviewer. On a likely
     mistake (a missed rename, a broken reference) stop and ask the user before
     landing; never change the edits. Pick the gate by stakes: none for docs
     (`--no-gate`), a targeted command (`--gate`), or the project's checks
     (`--checks`). Commit with that line plus `--commit -m "<msg>" <gate>`, then
     `board cr land <cr> --tip <new tip>`. A failing gate lands nothing: tell
     the user what `board` printed; the CR stays theirs.
     **Moved base** (`land` refuses and names it): commit the edits with no gate
     flag (`--commit -m "<msg>"`; the refresh checks them; `--gate` and
     `--no-gate` store a check and are refused there), refresh under
     [Refresh](review.md#refresh) steps 2-3 (a flagged change goes back to
     agent review), show the user the range-diff, then land the new tip.
   - **Design checkpoint:** name the outcome the round's answers entail for
     one confirmation. Nothing changes the design: `board cr land <cr>
     --checkpoint --design <hash>` (the hash from step 2). Otherwise block the
     CR on each round record that changes it (`board block <cr> --on <record>
     --reason "<what changes>"`, one call per record) and
     `board return <cr> "<records>"`; its author reworks the
     design once they are released.
   - **Changes wanted:** talk the root fix through with the user, then
     `board return <cr> "<findings>"`; add follow-up items to the CR.
     **Return with edits:** `board cr edits <cr> --tip <tip> --commit -m
     "<msg>"` (no gate flag), then `board return <cr> "<findings>"`.
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
run: return it naming the unestablished claim. `board cr land` refuses: report the
refusal, then refresh or wait.

**Exit:** the item is closed, landed or returned, or the milestone has new
members.

## Ratification

The `Ratify: <CR title>` task
([Change requests](../../shared/change-requests.md#change-requests)) takes the
user's verdict through `board ratify`: `yes` closes it (a default reason names the CR) and
removes its review worktree and `ratify/<id>` branch, refused while they
hold the user's edits; `edits` makes them the follow-up CR's (branch renamed
to `cr/<follow-up>`), commits uncommitted edits as the user's, rebased
onto the target and checked at once, waiting for the Accept (a rebase
conflict: change-requests.md Rebase, user's edits); `no` closes it with the reason and files the
follow-up the user wants (fix or revert).

## User review

The user reviews an item in its own worktree on its own
branch; the board owns opening, reading and recording it (mechanism: README,
the `board review open` paragraph). `board review open <item>` opens it at the tip it records; a ratification opens branch
`ratify/<id>` at the landed tip. The user's edits are their commits after the opened tip
plus uncommitted changes; Accept and Return commit the latter as the user's
and record all as the user's edits. Accept on a moved base rebases, checks
and triages like a refresh, then lands; a flagged change returns the CR to
agent review. `board show <item>` names whether it is open for review and
whether the user edited it.

## Commands

| Command | Effect |
|---|---|
| `board cr land <cr> --checkpoint --design <hash>` | The user's design checkpoint accept: `open`, checkpoint cleared, to planning; nothing lands. `<hash>` is the `design hash` `board claim <cr>` printed, still matching the design items' description, design, acceptance and notes. |
| `board cr edits <cr> --tip <sha> [--commit …]` | Prints, or with `--commit` commits and records as the user's, the user's edits in the CR's review; flags and gates: `board cr edits --help`. A failing gate keeps the commit and the CR waits for the user. |
