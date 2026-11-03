## Acceptance

### Review policy

Use one acceptance gate per coherent target, sized to stakes; a role protocol
may tighten it.

| Claim | Gate |
|---|---|
| Settled by a cheap check | Inline check by the acceptor. |
| Checkable beyond that; repair closure | `verify`. |
| Consequential contract, design, plan, cross-cutting change | `review`, reproducing decisive checks; add `verify` only for remaining open claims. |

- Reuse a planned later review of the same target (staged or integration
  review) where it replaces a redundant earlier gate.
- Select and brief reviewers under
  [Reviewers](../shared/reviewers.md#reviewers).

### Evidence and gates

- Accept author gate results with recorded command and output. Reproduce the
  decisive check as a non-author for missing or contradictory output,
  surprising or disputed claims, or security, data-integrity or persistence
  changes. Let gates fail; fix causes, not results.
- For test gates, confirm the required cases executed and record passed, failed
  and skipped counts alongside the exit code. Skipped or setup-blocked
  cases do not satisfy a required gate.
- Comment each gate's command and outcome on its item; rerun decisive checks
  after relevant changes. Authors run implementation gates; the planning
  session runs an outcome's acceptance at its close and cuts checks others
  wait on as tasks.
- Scope evidence to the item's own changes and their affected consumers;
  attribute failures in others' areas to their holders instead of fixing
  them.
- Run targeted gates after isolated changes; whole-repository gates after
  cross-cutting changes, at agreed milestones and at final acceptance. With a
  red baseline, target the touched surfaces the broken gate would cover.
- A whole-project check in an item's criteria, failing for others' reasons,
  means no new errors from the item's change: compare the errors before and
  after, tracing new ones to their files in a shared tree; an item with no
  earlier run checks its touched and consuming files. Record that comparison;
  leave the criteria as written. Gate items keep the full check; once it passes,
  the criterion binds as written. An item whose own tests cannot run stays open.
- Proof is the command and its output; leave out hash pins and byte copies. A
  tiny edit gets one check.
