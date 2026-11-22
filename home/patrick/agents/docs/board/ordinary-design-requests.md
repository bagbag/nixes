# Ordinary design change requests

Design intent — validation-pending under `nixes-aq9ca`. This change request
carries the design through ordinary review and Accept. The lifecycle change
and conversion of existing records follow separately.

Revised by `nixes-lwf8q` (22.11.2026, [workflow.md](workflow.md#designs)):
a design lands with its implementation by default; this contract applies to
a separate design CR, the exception that names its reason.

## Contract

Plan a design-only change request (CR) with a `design` work item. Commit the
design to the existing topic owner under `docs/`. Carry its scope, constraints,
authority, and validation criteria in the committed text. Use the project's
normal `look` setting. When a design opens a one-way door on the next run's
path, use `look before`, setting an override only if the project default
differs.

The design item routes authoring. Closing that item records the committed
authoring pass. Landing the CR delivers the approved design. The CR's
ordinary review, Return, refresh, Review Open, user edits, and Accept operate
on the committed range. A change to that range follows existing coverage and
check rules. The accepted text lives on the target, where Release can apply
later rulings through its existing owner-write path.

Create the implementation CR after verified design landing on the target.
Reference the document and its relevant section from the implementation
brief. A dependent that needs the accepted design waits on the design CR
(`blocks`); a design-only CR is never a stack base, so the dependent starts
after verified landing. Regular CR stacking continues for other work. At implementation acceptance, update
the design owner with verified behavior and any remaining validation scope.

An open decision still holds affected work items under `nixes-abhy5`. A
ruling that changes an in-review design can use the explicit planner Return
from `nixes-9mooj` when its conditions hold. A held review follows the current
holder route. Review and Return carry the same authority as for other CRs.

## Runtime and owner changes

| Owner | Change |
| --- | --- |
| Board lifecycle and writers | Keep design pull routing for open design-only CRs. Never stack work on a design-only CR. Remove checkpoint metadata from live writes, the design hash and `land --checkpoint --design`, design branches of claim, handover and Return, and checkpoint-only wait, refresh and acceptance behavior. Ordinary landing and its recovery settle a design CR. Keep decision holds and the released wait contract. |
| Console and adapters | Remove the checkpoint field and checkpoint-specific stages, title text, buttons and commands from the board payload and console parser, types, notifications and rendering. Use ordinary CR diff or result review, with the existing tip and check information. |
| Ratification and unattended operation | Stop creating design ratifications. A design landed through `look after` can have the usual landing ratification. Remove the special autopilot path for a user checkpoint. A look-before design follows ordinary user Accept authority. Historical design ratifications remain board history. |
| Planning and operating instructions | Update plan and work for a landed design followed by an implementation CR. Update role entry, review, decide, accept, unattended, board-core, change-requests, board-coordination and board-migrate where they describe the retired stage. Update board and console docs with the corresponding runtime change. Keep milestone, release, and scratch session checkpoints. |
| Protocol consumers | Use ordinary Accept and Release for design documents. Leave protocol-engine Record recovery checkpoints and unrelated proposal behavior in place. |

Pair the board schema and lifecycle changes with their consumer and fixture
updates. Use the supported board workflow for the new design CR while the old
checkpoint path still exists. The implementation CR follows after this
design lands.

## Existing records and rollout

Use the existing board-migrate process, per board after the new runtime is
installed and the board's sessions restarted. Inventory each board before
writing: live CRs with `checkpoint`, design children, open design
ratifications, their linked dependents and ruling records, and known document
or scratch body references. Include record status, holder, base and tip,
dirty and open review worktrees, and exact edge directions. Resolve each
source body and compare its provenance to the approved or reviewed range.
The owner approves the per-board mapping, backup and any live review exits.
Pause affected writers while moving data. Treat the user’s
unrecorded edits and held work as exclusions until their owners resolve them.

| Existing record | Transition |
| --- | --- |
| Dropped or superseded checkpoint | Use its recorded disposition through the current deciding workflow. Keep its branch, worktree, and history under existing retention authority. |
| Live checkpoint with an outstanding design | Preserve the CR and item identities when possible. End an open review through the current workflow, return the work to authoring, place the remaining design text in the topic document on the branch, and send that commit through ordinary review and the required Accept. Move implementation items into a distinct dependent CR if they already exist. |
| Passed checkpoint with implementation still live | Preserve the prior verdict and implementation branch. If the accepted text has no durable owner, carry it unchanged into a documentation CR, linked to the former record and verdict, and land it before new dependent authoring. A new change to the design follows normal design review. |
| Existing waiters | Retain unsatisfied delivery waits as dependencies on the ordinary design CR. Block already-filed waiters that require the landed design on the design CR. Turn already-satisfied design waits (on a closed design inside an unlanded CR) into `relates-to` links; keep ordinary implementation waits. Quiesce affected work until linked replacement edges are reconciled. |
| Live design ratification | Preserve its verdict opportunity and review worktree. Resolve it through `agents board ratify`, preserving any user edits. Closed ratifications stay intact. |
| Missing or conflicting body or verdict | Preserve the record and data, block the affected work, and bring the choice to its owner. A scratch reference alone establishes neither the approved text nor authority to publish it. |

Prepare the durable bodies, validate the
mapping against a read-only re-export, and close or resolve obsolete stages
through their owners. Once an approved checkpoint has returned to authoring,
clear its live checkpoint marker and obsolete review or check coverage before
its ordinary handover. Preserve the base and fork, holds and dependencies that still
apply, and the earlier review evidence in history.
Recheck the expected status, hold, tip, and edges before each write. On an
interruption, reconcile completed writes with that mapping and stop at any
divergence. Before resuming writers, confirm that no live checkpoint
metadata, actionable design ratification or satisfied design wait remains.
Preserve historical fields.

Keep an owner-approved recovery baseline until the transition smoke passes. A failed verification pauses that board’s
cutover. Before resuming writers, reconcile to the saved baseline or finish
the approved conversion. Any restore or reversal after new writes requires
the owner's approval and reconciliation of those writes.

## Verification

- Through normal board entry points, exercise design authoring, review,
  Return and re-review, clean refresh after base changes, user edits, and
  landing in a disposable board. A look-before design waits for the user.
  A look-after design produces only a normal landing ratification. An
  unattended session gains no authority over ordinary user Accept.
- Verify planning can find the design from the landed target, the
  pre-existing dependent waiting on the design CR cannot begin during review or Accept, and
  it can start after delivery. Exercise item-scoped questions and an
  explicit planner Return alongside unaffected reviews.
- Exercise migration fixtures for an open agent and user checkpoint, a
  returned checkpoint with a branch, a prior passed design with code in
  progress, deferrals and dependent edges, one design ratification, a
  scratch-held body, and missing provenance. Verify rerun after partial
  conversion, refusal on a changed hold or tip, preservation of legacy
  history and user edits, and a satisfied design wait across CRs.
- Run the configured check, shared-board CR integration, and console
  contracts on the implementation. The exact migration inventory belongs
  to each board's reviewed mapping. Local planning evidence is an export
  for `nixes-67agm`; it does not establish the state of other boards.
