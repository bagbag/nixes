## Goal relay

goal-lead prepares decisions with the user; the user decides and releases them.
goal-agent applies released rulings and owns implementation, sequencing and the
board. Root the pair's board at a goal epic.

### Channel and granularity

- Assign goal-agent's questions to `goal-lead`, with plain-question titles and
  work-tracking's [Question](../shared/work-tracking.md#question) shape.
- goal-agent rules under
  [Decision authority](../shared/decision-protocol.md#decision-authority) with
  goal-lead as decider. Comment the choice on its package. Raise changes to
  general rules as questions.
- Before creating an item or question, search the root epic with `bd search`
  and `bd find-duplicates`; extend an open item on the same decision, files or
  migration. Put scope in `--acceptance` and the reason in a comment.
- Scope one question to a decision across all sites, one package to a module's
  complete change, and one migration item to every call site. Split only for
  parallelism, ownership, risk or real dependencies.
- Make each question block every issue it holds up, creating missing issues.
  Add dependencies on each open question its options assume:
  `bd dep add <id> <other>`.

### Writers

| Writer | Ownership |
|---|---|
| goal-lead | Its arcs' topic contracts (`docs/<topic-slug>/`); goal/arc epic `--design`, `--acceptance`, rank; checkpoints. |
| goal-agent | Checkpoint contribution edges (`blocks`); every other owner changed by a released ruling, including other topics' docs; implementation, sequencing, board. |

For a settled decision, goal-lead may apply small, fully specified edits
(doc edits, few-line source fixes) to files no goal-agent item holds
`in_progress`; verify and comment them on the item.

### Decision states

| State | Record and authority |
|---|---|
| Unanswered | Question assigned to goal-lead, labelled `human`. |
| Decided / pending release | Decision in `--design`, labelled `decided`; goal-lead retains it until release. Decisions bind on release. |
| Released | Approved handoff to goal-agent; `human` and `decided` removed. Question remains open and blocks dependents until landing. |
| Landed | Owners and affected issue state reconciled; question closed. |

### Write timing

- goal-lead records each decision on its question when it is made. When the
  user asks for the overall picture first, record that cluster's decisions
  after the walkthrough.
- goal-lead writes ruling-bearing changes to canonical contract owners and epic
  `--design` / `--acceptance` only in the approved [Release](#release).
- goal-lead sets epic rank (work-tracking
  [Priority](../shared/work-tracking.md#priority)) and checkpoints as
  bookkeeping at any time.

### Pending

goal-lead records each decision in its question's `--design` at the
[Write timing](#write-timing) and adds `decided`. Put a plain one-line summary
first, followed by:

- provenance (`user` or `lead`);
- for lead rulings, rejected alternative and checks;
- owners and anchors, consumer examples, affected callers;
- withdrawn premises and `path:line` citations.

Use work-tracking's [Rulings](../shared/work-tracking.md#rulings) record format
and destination mapping.

### Release

Release one ruling or an interdependent set once the user approves that set.
Conditional approval covers that round's items. Preserve this order:

1. goal-lead writes the ruling-bearing changes to canonical contract owners and
   epic `--design` / `--acceptance` ([Write timing](#write-timing)).
2. Relate each question to the set's other questions and affected issues outside
   its `blocks` edges: `bd dep relate`. Comment planning input (ordering, scope
   growth) and proposals; goal-agent confirms, refines or replaces proposals
   through a question.
3. Hand each question over with one update per id:

   ```sh
   bd update <id> --assignee goal-agent \
     --remove-label human --remove-label decided
   ```

Handoff is not atomic across ids. goal-agent lands a related set together once
none of its questions remains `decided`.

### Contract

- goal-lead drafts or advances the arc contract with the user through
  `define-goal`; release its revision through a question like any ruling.
- goal-agent returns gaps, contradictions and refinements as questions. Only
  rulings change the contract.

### Design gate

- Apply to slices opening boundaries, public contracts, data flow, mechanisms
  or the clean end state, and to contract items marked "design first".
- goal-agent creates `design: <slice>` with architecture where open, the package
  graph and needed decisions. Make slice packages depend on it (`blocks`);
  hand it to goal-lead with `review`.
- goal-lead closes the design item on user acceptance or returns it with findings.
- Continue other slices on settled items; turn consequential mid-slice choices
  into questions blocking their dependents.

### Landing

- Require owner writes, affected issues' design/acceptance updates, refreshed
  questions against superseded state and reconciled duplicates before closure.
  goal-agent performs the role-specific steps in its Land released rulings phase.
- Keep the released question open; its `blocks` edges hold dependents until
  landing completes.
- A landing conflict becomes a question blocking the released ruling:
  `bd dep add <released> --blocked-by <conflict>`.
- Close after landing: `bd close <id> --reason "landed in <owners>"`.
- The acceptor checks landing when accepting an affected issue.
