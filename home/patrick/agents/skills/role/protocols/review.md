# Review protocol

Read
`$HOME/.agents/skills/shared/board-core.md`,
`$HOME/.agents/skills/shared/change-requests.md`,
`$HOME/.agents/skills/shared/acceptance.md`,
`$HOME/.agents/skills/shared/decision-protocol.md` and
`$HOME/.agents/skills/shared/reviewers.md` before step 1.

## Entry

One of: an `in_review` change request (CR: agent review or agent
checkpoint), or refresh work ([Refresh](#refresh)), or a standalone review
(findings only, outside any CR), is ready for your session's `review` pull; a
dispatch brief names an id and this protocol. Deciding sessions accept CRs in
`needs_acceptance` and user-judged epics under the decide protocol.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops. A challenge follows [Challenge](#challenge) in place of
steps 3-7.

1. **Claim.** `board claim` for your pull or `board claim <id>` for a named
   CR or item. It prints the author doer, `author unknown (<holder>)` (a
   retired role holder) or `standalone` (a standalone review no one held):
   you are independent unless you are that doer; a fresh-context worker of
   the same session suffices. Review a CR in its worktree as the author left
   it.
   Output: `claimed <id>; author <actor>; independent`, or
   `claimed <id>; standalone review`.
2. **Read.** The CR's acceptance and items, its brief, the released rulings
   it links and their owners, the author's evidence comments, and the diff
   `<base>..cr/<id>`. Current rulings and supersessions win over older briefs
   and verdicts.
   Output: ids and owners read.
3. **Gate.** Select the gate under [Review policy](../../shared/acceptance.md#review-policy)
   (a checkpoint review covers the checkpoint's scope: the design, or the
   work so far).
   Output: gate and reason.
4. **Evidence.** Apply [Evidence and gates](../../shared/acceptance.md#evidence-and-gates) to every
   required gate.
   Output: one line per gate: command, result, accepted or reproduced.
5. **Assess.** Check correctness, the global Cleanliness tests and the
   decision protocol's
   [End-state criteria](../../shared/decision-protocol.md#end-state-criteria);
   triage the author's disclosed judgment calls; classify scope growth under
   [Expansion findings](#expansion-findings).
   Output: verdict; then each confirmed defect, risk and open question.
6. **Fix.** Unless the brief forbids assessor fixes, fix wording, doc and
   comment findings yourself, and fix a code finding when the fix is the only
   clean option and stays within a few lines, as commits on `cr/<id>` in its
   worktree; rerun the gates after a code fix. Return larger fixes to the
   author.
   Output: each fix with its commit, or `no fixes`; gate reruns.
7. **Pass or return.** Pass only when certain everything is clean and every
   required gate passed (your fixes included, listed in the verdict):
   `board handover <cr> "<verdict>"`; when it prints a range instead (the tip
   moved since you looked), review that range and hand over again. Otherwise
   return it with verdict,
   confirmed defects, open questions, executed checks and next action:
   `board return <cr> "<findings>"`.
   Raise a choice that needs a decision as a question blocking the CR. A
   standalone review closes with `board bd close <id> --reason "<verdict>"`,
   recording each finding as a new item discovered from it
   (`--deps discovered-from:<id>`).
   Escalate instead of passing when a
   [hidden-and-costly](../../shared/acceptance.md#review-policy) path stays
   unsettled: comment your findings and evidence, then
   `board bd update <id> --set-metadata deep_review="<the path>"` and
   `board unclaim <id>`. A `deep-review` ending an escalated item removes the
   mark (`--unset-metadata deep_review`).
   Output: `passed <cr> to <status>`, `returned <cr>`, `question <id>`,
   `escalated <id>` or `closed <id>`, plus the new item ids for a standalone
   review.

## Stop

- You are the author doer: `board unclaim <id>`, report it, stop.
- A required gate cannot run: return the item naming the unestablished claim
  and its acceptance consequence.
- Repairs on the same problem reach the retry limit (global Retry limit):
  follow it, recording in the item's `notes`.

## Exit

The CR is passed, returned to the queue or blocked by a question (or the
standalone review closed), and the output lines above are posted.

## Challenge

A standalone review of decided records or a contract draft, before release.

1. **Assess.** Invoke `step-back` on the records and the owners and items
   they rest on, then `challenge-rulings` on the records' rulings; check contradictions with each other
   and with released rulings, integrity and security holes, and gaps a
   realistic consumer hits.
   Output: verdict; each finding with its evidence.
2. **Close.** Create each finding as a question discovered from the
   challenge (`--deps discovered-from:<id>`) and block the record it concerns
   on it (`board block <record> --on <question> --reason "<finding>"`), then
   close the challenge with the verdict.
   Output: `closed <id>`, plus the question ids.

## Refresh

Refresh work: [Change-request queue](../../shared/board-coordination.md#change-request-queue);
its command: the `board refresh` row of
[Change requests](../../shared/change-requests.md#change-requests).

1. **Claim.** `board claim` (kind `refresh`), or `board claim <cr>` for the
   request a prompt names.
   Output: `claimed <cr> (refresh)`.
2. **Refresh.** `board refresh <cr>`; resolve a conflict in the worktree and
   rerun.
   Output: check state, range-diff size, incoming file count.
3. **Triage.** Dispatch the `cr-refresh` agent with the CR id, its worktree
   and the printed range-diff and file list; verify each flag it returns in
   the diffs.
   - A confirmed flag: `board handover <cr> "<confirmed flags>"` sends the CR
     back to `in_review`. Hand over the same way after a resolved conflict
     (the commits changed).
   - None: `board refresh <cr> --review-holds`. When it refuses on a base
     that moved after your triage, triage the new incoming files and rerun.
   Output: flags with verdicts.
4. **Release.** `board unclaim <cr>`.
   Output: `refreshed <cr>: <state>` or `sent back to review`.

## Assessor conduct

- The author repairs; the same assessor checks repairs and the affected
  invariants. Repair completion reopens no broader review.
- Independence: [Reviewers](../../shared/reviewers.md#reviewers).

## Expansion findings

Classify each under
[Concern classes](../../shared/decision-protocol.md#concern-classes). When
reviews keep adding structure without runnable progress, pause affected
fan-out, re-derive the premise with an architect, test a smaller coherent
option against the earliest runnable checkpoint and bring the options to the
decider.
