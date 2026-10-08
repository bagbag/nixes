## Goal relay

goal-lead prepares decisions with the user; the user decides and releases
them; goal-agent applies them and owns implementation, sequencing and the
board.

- **Channel:** goal-agent raises questions (work-tracking) assigned to
  `goal-lead`. It rules itself only where exactly one realistic clean option
  exists, or on internal detail that consumers never see and that sets no
  convention, and comments the choice on its package. A change to a general
  rule is a question.
- **Writers:** goal-lead writes the topic contract (`docs/<topic-slug>/`) and
  the epic's `--design` and `--acceptance`. goal-agent writes every other
  owner a released ruling changes.
- **Pending:** goal-lead comments each decision on its question as it is
  made and adds `decided`; pending decisions bind nobody. Add consumer
  examples, affected callers, withdrawn premises and `path:line` citations
  where they apply.
- **Release** of one ruling or a set of interdependent ones, in this order:
  1. Create the intake `apply: <subject>` (label `intake`, assigned to
     `goal-lead` while the release is in progress): each ruling with its
     owner and anchor. Write the contract and epic changes.
  2. Create the tasks it implies: changelog and upgrade duties, hints
     (planning input), proposals (goal-agent confirms, refines or replaces them
     through a question). Relate the intake to each task and question
     (`bd dep relate`).
  3. Publish: `bd update <intake> --assignee goal-agent`.
  4. Answer the settled questions (`bd human respond`; remove `decided`).

  An intake assigned to `goal-lead` without `review` is an unfinished
  release; resume it from its relations.
- **Contract:** goal-lead writes or advances the arc's contract with the user
  (`define-goal`) and releases it like a ruling. goal-agent's intake returns
  gaps, contradictions and refinement proposals as questions; only rulings
  change the contract.
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
- **Intake review:** goal-agent hands the reconciled intake to goal-lead
  (work-tracking acceptance); delivery proceeds meanwhile.
