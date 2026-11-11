## Acceptance

### Review policy

Use one acceptance gate per coherent target (plus `verify` for claims it leaves
open), sized to stakes; a role protocol may tighten it.

| Claim | Gate |
|---|---|
| Settled by a cheap check | Inline check by the acceptor. |
| Checkable beyond that | `verify`. |
| Consequential code or cross-cutting change | `review`, reproducing decisive checks; add `verify` only for remaining open claims. |
| Contract, design, plan; work the planner marked hidden-and-costly; escalation at the retry limit | `deep-review`. |
| Repair after a return | The reviewer that returned it ([Reviewers](../shared/reviewers.md#reviewers)). |

- Reuse a planned later review of the same target (staged or integration
  review) where it replaces a redundant earlier gate.
- A `review` that finds unmarked work hidden-and-costly may ask for
  `deep-review`; the planner's mark rule is plan.md
  [Cut work](../role/protocols/plan.md#cut-work).
- Select and brief reviewers under
  [Reviewers](../shared/reviewers.md#reviewers).
- **Hidden and costly:** a bug that play, tests and the type checker would
  miss, whose harm (to users, data or security, or breaking a published
  contract) is hard to undo. The planner names the harm when marking work.

### Evidence and gates

- Accept author gate results with recorded command and output. Reproduce the
  decisive check as a non-author for missing or contradictory output,
  surprising or disputed claims, security, data-integrity or persistence
  changes, or an item marked hidden-and-costly.
- Let gates fail; fix causes, not results.
- For test gates, confirm the required cases executed and record passed, failed
  and skipped counts alongside the exit code. Skipped or setup-blocked
  cases do not satisfy a required gate.
- Put each gate's command and outcome in the hand-over (on a board, its one
  comment: [Hand-over and acceptance](../shared/board-core.md#hand-over-and-acceptance));
  rerun decisive checks after relevant changes and state the final results in
  the closing verdict. Authors run implementation gates; the planning session
  runs an outcome's acceptance at its close and cuts checks others wait on as
  tasks.
- Scope evidence to the change's own effects and their consumers; attribute
  failures outside it to their cause instead of fixing them.
- Run targeted gates after isolated changes; whole-repository gates after
  cross-cutting changes, at agreed milestones and at final acceptance. With a
  red baseline, target the touched surfaces the broken gate would cover.
- A whole-project check in an item's criteria, failing for others' reasons,
  means no new errors from the item's change: compare the errors before and
  after, tracing new ones to their files; an item with no
  earlier run checks its touched and consuming files. Record that comparison;
  leave the criteria as written. Gate items keep the full check; once it passes,
  the criterion binds as written. An item whose own tests cannot run stays open.
- Proof is the command and its output; leave out hash pins and byte copies. A
  tiny edit gets one check.
