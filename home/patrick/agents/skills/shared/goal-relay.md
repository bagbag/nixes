## Goal relay

goal-lead prepares decisions with the user; the user decides and releases
them; goal-agent applies them and owns implementation, sequencing and the
board.

- **Channel:** goal-agent raises questions (work-tracking) assigned to
  `goal-lead`. It rules itself only where exactly one realistic clean option
  exists, or on internal detail that consumers never see and that sets no
  convention, and comments the choice on its package. A change to a general
  rule is a question.
- **Writers:** goal-lead writes this arc's topic contract (`docs/<topic-slug>/`
  of the arc's own topic) and the epic's `--design` and `--acceptance`.
  goal-agent writes every other owner a released ruling changes, other topics'
  docs included.
- **Pending:** goal-lead records each decision in its question's `--design`
  (work-tracking) with provenance (user or lead), owners and anchors, consumer
  examples, affected callers, withdrawn premises and `path:line` citations,
  and adds `decided`. Decisions bind on release.
- **Release** of one ruling or a set of interdependent ones, in this order:
  1. Write the contract and epic changes.
  2. On each question, relate the set's other questions and affected issues
     outside its `blocks` edges (`bd dep relate`); comment planning input
     (ordering, scope growth) and proposals (goal-agent confirms, refines or
     replaces them through a question).
  3. Hand each question over in one update (per id; not atomic across ids):

     ```sh
     bd update <id> --assignee goal-agent \
       --remove-label human --remove-label decided
     ```
- **Contract:** goal-lead writes or advances the arc's contract with the user
  (`define-goal`) and releases it like a ruling, through a question carrying
  the revision. goal-agent returns gaps, contradictions and refinement
  proposals as questions; only rulings change the contract.
- **Design gate:**
  - Applies to a slice that opens boundaries, public contracts, data flow,
    mechanisms or the clean end state, or whose contract item is marked
    "design first".
  - goal-agent creates `design: <slice>` (architecture where open, package
    graph, needed decisions), makes the slice's packages depend on it
    (`blocks`) and hands it to goal-lead with `review`.
  - goal-lead closes it once the user accepts, or hands it back with findings.
  - Other slices proceed on settled items; a consequential choice found
    mid-slice becomes a question that blocks its dependents.
- **Landing:** goal-agent writes each released ruling into its owners and the
  affected issues' design and acceptance, then closes the question
  (`bd close <id> --reason "landed in <owners>"`); its `blocks` edges hold
  dependents until then. A conflict found while landing becomes a question
  that blocks the released one (`bd dep add <released> --blocked-by
  <conflict>`). The acceptor checks the landing when accepting an affected
  issue.
