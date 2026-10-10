## Goal relay

goal-lead prepares decisions with the user; the user decides and releases
them; goal-agent applies them and owns implementation, sequencing and the
board.

- **Channel:** goal-agent raises questions (work-tracking) assigned to
  `goal-lead`, titled as a plain question. It rules itself only where exactly
  one realistic clean option exists, or on internal detail that consumers
  never see and that sets no convention, and comments the choice on its
  package. A change to a general rule is a question.
- **Granularity:** before creating an item or question, search the root epic
  (`bd search`, `bd find-duplicates`) for an open one on the same decision,
  files or migration and extend it (scope in `--acceptance`, reason in a
  comment). A question covers one decision across all its sites; a package one
  module's complete change; a migration one item listing every call site.
  Split only for parallel work, ownership, risk or a real dependency.
- **Question edges:** a question blocks every issue it holds up (create
  missing ones) and depends on (`bd dep add <id> <other>`) each open question
  its options assume.
- **Writers:** goal-lead writes the topic contracts of its arcs
  (`docs/<topic-slug>/`), the goal and arc epics' `--design`, `--acceptance`
  and rank, and the checkpoints. goal-agent links the contributing items
  to each checkpoint (`blocks`) and writes every other owner a released ruling
  changes, other topics' docs included.
- **Pending:** goal-lead records each decision in its question's `--design`
  (work-tracking): a plain one-line summary first, then provenance (user or
  lead), lead rulings with the rejected alternative and what was checked,
  owners and anchors, consumer examples, affected callers, withdrawn premises
  and `path:line` citations; it adds `decided`. Decisions bind on release.
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
  affected issues' design and acceptance, refreshes open questions written
  against the superseded state, merges duplicates it finds (re-point their
  dependents to the keeper, then `bd duplicate <duplicate> --of <keeper>`),
  then closes the question (`bd close <id> --reason "landed in <owners>"`); its
  `blocks` edges hold dependents until then. A conflict found while landing
  becomes a question that blocks the released one
  (`bd dep add <released> --blocked-by <conflict>`). The acceptor checks the
  landing when accepting an affected issue.
