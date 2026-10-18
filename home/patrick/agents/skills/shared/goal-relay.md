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
| Unanswered | Question `open`, assigned to goal-lead. |
| Decided / pending release | Decision in `--design`, status `decided`; when gated, blocked by its release gate. goal-lead retains it until release. Decisions bind on release. |
| Released | Approved handoff: status `released`, assigned to goal-agent. Question blocks dependents until landing. |
| Landed | Owners and affected issue state reconciled; question closed. |

### Write timing

- goal-lead records each decision on its question when it is made. When the
  user asks for the overall picture first, record that round's decisions
  after the walkthrough.
- goal-lead writes ruling-bearing changes to canonical contract owners and epic
  `--design` / `--acceptance` only in the approved [Release](#release).
- goal-lead sets epic rank (work-tracking
  [Priority](../shared/work-tracking.md#priority)) and checkpoints as
  bookkeeping at any time.

### Pending

goal-lead records each decision in its question's `--design` at the
[Write timing](#write-timing) and sets status `decided`. Put a plain one-line
summary first, followed by:

- provenance (`user` or `lead`);
- for lead rulings, rejected alternative and checks;
- owners and anchors, consumer examples, affected callers;
- withdrawn premises and `path:line` citations.

Use work-tracking's [Rulings](../shared/work-tracking.md#rulings) record format
and destination mapping.

### Release gates

- Gate a decided question or set that waits on prerequisites or spans rounds;
  a ruling released in the round it is decided needs no gate.
- Create one human gate per set under the owning arc epic and make every
  question in the set depend on it:

  ```sh
  bd gate create --type human --title "[Gate] Release: <set>" \
    --blocks <first id> --reason "<set scope, prerequisites, plan link>"
  bd dep add <other id> <gate>
  bd update <gate> --parent <arc epic> --assignee goal-lead
  ```
- Make prerequisites (reviews, sign-offs, prerequisite questions) block the
  gate: `bd dep add <gate> <prerequisite>`. A gate without open blockers is
  ready for the release ask.

### Release

Release one ruling or an interdependent set once the user approves that set.
Conditional approval covers that round's items. Preserve this order:

1. goal-lead writes the ruling-bearing changes to canonical contract owners and
   epic `--design` / `--acceptance` ([Write timing](#write-timing)).
2. Record each revision of an earlier ruling: `bd supersede <old> --with <new>`
   when the new ruling replaces it entirely; otherwise
   `bd dep add <new> <old> -t supersedes` and name the revised part in the new
   ruling's `--design`. Add `blocks` only where landing order matters. Relate
   the set's questions to affected issues outside their edges with
   `bd dep relate`. Comment planning input (ordering, scope growth) and
   proposals; goal-agent confirms, refines or replaces proposals through a
   question.
3. Resolve the set's gate: `bd gate resolve <gate>`.
4. Hand each question over with one update per id:

   ```sh
   bd update <id> --assignee goal-agent --status released
   ```

Handoff is not atomic across ids. goal-agent lands a gated set together once
its gate is resolved and none of its questions remains `decided`.

### Contract

- goal-lead drafts or advances the arc contract with the user through
  `define-goal`; release its revision through a question like any ruling.
- goal-agent returns gaps, contradictions and refinements as questions. Only
  rulings change the contract.

### Design gate

- Apply to slices opening boundaries, public contracts, data flow, mechanisms
  or the clean end state, and to contract items marked "design first".
- goal-agent creates `[Design] <slice>` with architecture where open, the package
  graph and needed decisions. Make slice packages depend on it (`blocks`);
  hand it to goal-lead under work-tracking
  [Acceptance](../shared/work-tracking.md#acceptance).
- goal-lead closes the design item on user acceptance or returns it with findings.
- Continue other slices on settled items; turn consequential mid-slice choices
  into questions blocking their dependents.

### Landing

- Require owner writes, affected issues' design/acceptance updates, refreshed
  questions against superseded state and reconciled duplicates before closure.
  goal-agent performs the role-specific steps in its Land released rulings phase.
- Keep the released question in status `released`; its `blocks` edges hold
  dependents until landing completes.
- A gap, conflict or follow-up found while landing becomes a new question,
  discovered from and blocking the released one; the released question keeps
  its ruling and status: `bd create … --deps discovered-from:<released>`, then
  `bd dep add <released> --blocked-by <new question>`.
- Close after landing: `bd close <id> --reason "landed in <owners>"`.
- The acceptor checks landing when accepting an affected issue.
