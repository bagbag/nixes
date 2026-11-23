# Review protocol

Read
`$HOME/.agents/skills/shared/board-core.md`,
`$HOME/.agents/skills/shared/change-requests.md`,
`$HOME/.agents/skills/shared/acceptance.md`,
`$HOME/.agents/skills/shared/decision-protocol.md` and
`$HOME/.agents/skills/shared/reviewers.md` before step 1.

## Entry

One of: an `in_review` change request (CR), or refresh work ([Refresh](#refresh)),
is ready for your session's `review` pull; a
dispatch brief names an id (a CR, or a challenge task, [Challenge](#challenge)) and this protocol.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops. A challenge follows [Challenge](#challenge) in place of
steps 3-7.

1. **Claim.** `agents board claim` for your pull or `agents board claim <id>` for a named
   CR or task. It prints `author <actor>` or `author unknown`: you are independent unless you are that doer; a fresh-context worker of
   the same session suffices. Review a CR in its worktree as the author left
   it.
   Output: `claimed <id>; author <actor>; independent`, or
   `claimed <id>` for a challenge task.
2. **Read.** The CR's acceptance and items, its brief, the released rulings
   it links and their owners, and the author's evidence comments. Read the
   range-diff `agents board claim` prints (the full diff on a first review) and any
   Return findings. Widen where the delta meets the rest. Current rulings and supersessions win over older briefs
   and verdicts.
   Output: ids and owners read.
3. **Gate.** Select the gate under [Review policy](../../shared/acceptance.md#review-policy)
   (a design CR's scope is its doc diff).
   Output: gate and reason.
4. **Evidence.** Apply [Evidence and gates](../../shared/acceptance.md#evidence-and-gates) to every
   required gate.
   Output: one line per gate: command, result, accepted or reproduced.
5. **Assess.** Assess the artifact under the shared
   [review method](../../shared/review-method.md). Verify the author applied
   [Convention changes](../../shared/change-requests.md#change-requests). Triage the author's
   disclosed judgment calls; classify scope growth under
   [Expansion findings](#expansion-findings).
   Output: confirmed defects, risks and open questions with evidence.
6. **Fix.** Unless the brief forbids assessor fixes, fix wording, doc,
   comment and local design findings yourself, and fix a code finding when
   the fix is the only clean option and stays within a few lines, as
   commits on `cr/<id>` in its worktree; rerun the gates after a code fix.
   Return larger fixes, and every fix to a design that opens a one-way
   door, to the author.
   Output: each fix with its commit, or `no fixes`; gate reruns.
7. **Pass or return.** Pass only when certain everything is clean and every
   required gate passed (your fixes included, listed in the verdict):
   `agents board handover <cr> "<verdict>"`; otherwise
   return it with verdict,
   confirmed defects, open questions, executed checks and next action:
   `agents board return <cr> "<findings>"` (each finding becomes an open item
   of the CR).
   Raise a choice that needs a decision as a question the affected items wait
   on under [Questions and rulings](../../shared/board-core.md#questions-and-rulings).
   For a code-review question, say in the findings that the follow-up item the
   Return adds waits on it: the Return releases the CR, and only a deciding
   session or the user writes waits on the items of an unheld CR. A frame change against a released
   ruling the CR applies correctly: pass the CR, then open the decision with
   `agents board ruling revise <ruling> --title <title> --body-file <packet> --holds
   none` and `agents board link <question> <cr> --type relates-to`. A
   non-blocking idea is filed as its own work (`--found-in <cr>`), not as an item of the CR.
   Escalate instead of passing when a
   [hidden-and-costly](../../shared/acceptance.md#review-policy) path stays
   unsettled: comment your findings and evidence, then
   `agents board bd --raw --yes update <id> --set-metadata deep_review="<the path>"` and
   `agents board unclaim <id>`. A `deep-review` ending an escalated item removes the
   mark (`--unset-metadata deep_review`).
   Output: `passed <cr> to <status>`, `returned <cr>`, `question <id>`,
   `escalated <id>`, plus the new ids for a filed idea.

## Stop

- You are the author doer: `agents board unclaim <id>`, report it, stop.
- A required gate cannot run: return the item naming the unestablished claim
  and its acceptance consequence.
- Repairs on the same problem reach the retry limit: follow it, recording in
  the item's `notes`.

## Exit

The CR is passed, returned to the queue or waiting on a question (or the
challenge task closed), and the output lines above are posted.

## Challenge

A task that reviews decided records or a contract draft, before release; the
records wait on it.

1. **Assess.** Invoke `step-back` on the records and the owners and items
   they rest on, then `challenge-rulings` on the records' rulings; check contradictions with each other
   and with released rulings, integrity and security holes, and gaps a
   realistic consumer hits.
   Output: verdict; each finding with its evidence.
2. **Close.** Create each finding as a question found in the
   challenge (`--found-in <id>`) and make the record it concerns wait on it
   (`agents board wait <record> --on <question> --for "<finding>"`), then
   close the challenge with the verdict (`agents board close <id> --reason "<verdict>"`).
   Output: `closed <id>`, plus the question ids.

## Refresh

Refresh work: [Change-request queue](../../shared/board-coordination.md#change-request-queue);
its command: the `agents board cr refresh` row of
[Change requests](../../shared/change-requests.md#change-requests).

1. **Claim.** `agents board claim` (kind `refresh`), or `agents board claim <cr>` for the
   request a prompt names.
   Output: `claimed <cr> (refresh)`.
2. **Refresh.** `agents board cr refresh <cr>`; resolve a conflict in the worktree and
   rerun.
   Output: refreshed tip and check state.
3. **Release.** If you still hold the CR, `agents board unclaim <cr>`.
   Output: `refreshed <cr>: <state>` or `sent to agent review <cr>`.

## Assessor conduct

The author repairs; the same assessor checks repairs and the affected
invariants. Repair completion reopens no broader review.

## Expansion findings

Classify each under
[Concern classes](../../shared/decision-protocol.md#concern-classes) against
the next run ([Frame](plan.md#frame)); deferred ones stay out of the design
text. When
reviews keep adding structure without runnable progress, pause affected
fan-out, re-derive the premise with an architect, test a smaller coherent
option against the earliest runnable checkpoint and bring the options to the
decider.
