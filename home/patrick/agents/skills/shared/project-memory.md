# Project memory (shared convention)

## Durable owners

- Project goals in `docs/goals.md`; topic contracts in `docs/<topic-slug>/`
  (`docs/<topic-slug>/goals.md` by default). Reuse suitable existing owners;
  organize by product or technical boundary; a small project may use one
  document. Execution topics may reference owners elsewhere; directory
  symmetry is not required. Each level adds specificity and links its parent;
  entry points link the owners. A fresh reader understands commitments and
  milestones without scratch.
- One canonical owner holds project purpose, defining value, enduring
  constraints and ratified cross-topic priorities; a substantial topic owns
  its distinct outcome, milestone commitments, scope and acceptance.
- Goals state outcomes, not execution permission. Distinguish product
  non-goals, milestone exclusions and committed deferrals; the eventual
  outcome, the approved checkpoint and the work authorized now. A checkpoint
  may validate a narrow executable path before broader delivery; keep
  integrity and authority constraints and later acceptance requirements in
  their approved sequence. Milestones may span arcs; closing an arc retires no
  commitment. Keep independently active milestones distinguishable within
  their owners.
- Record ratified goal and sequencing changes in their owner before dependent
  work consumes them, also when the product goal is unchanged; the board links
  the checkpoint. A child plan narrows a parent commitment only through a newer
  user decision. Cross-topic and cross-project work links its owners and
  dependencies; priority conflicts return to the decision owner. When goals,
  sequencing or authority change, reconcile affected owners, plans and next
  actions; park only dependent work.
- Rulings live in their owners (work-tracking).
- Outstanding work is deferred issues (work-tracking): problem or intended
  outcome, area, reason, revisit condition, and the findings, reproduction
  details and active containment needed to resume without scratch. Labels
  distinguish defects, investigations and unapproved proposals; keep
  investigations and proposals only with a concrete revisit reason. Recording
  an item or reaching its revisit condition authorizes nothing. Reconcile
  entries when setting scope, when revisit conditions change and at arc close;
  close resolved ones with disposition and evidence. A project-defined roadmap
  document keeps what the project assigns it.
- Structure: one document for a small topic; `index.md` (owners, product
  state, milestones, read order) and topical subfolders by enduring boundary
  when size or ownership warrants; `history/` for superseded material, clearly
  labelled; one owning section per concept, referenced by name and anchor;
  English names (domain and legal prose may keep its language).
- Source and executable checks establish implementation reality; label
  unproven mechanisms "design intent — validation-pending".

## Arc state

- **Board:** the description of the arc epic `<topic-slug>/<arc-slug>`, one
  per arc, short and replaced in place. Top: topic and arc slugs, mode,
  status, owner links. Then a first-screen summary sufficient to pick the next
  action: goal and checkpoint links, checkpoint evidence, verified position,
  next authorized work and return boundary, and the blockers, pending choices,
  deferrals and parallel tracks shaping it. Then authority, containment and
  evidence qualifications. Link plans and reports; distinguish executed
  evidence from author reports and intent.
- One active lead per topic, or one goal pair (goal-agent owns the board). A
  lead may run several arcs, each with its own epic and
  `.scratch/<topic-slug>/<arc-slug>/` (plans, drafts, reviews, `evidence/`,
  `history/`). Lowercase kebab-case slugs. Keep `.scratch/` gitignored and
  free of secrets.
- Workers get the epic id and their issue and flag board/spec contradictions;
  board edits stay with the lead.

## Synchronization

- Update beads as work changes state. Refresh the board at plan or decision
  changes, material completion, failed checks, changed blockers and before
  recovery boundaries.
- Record decisions and reconcile the plan before dependent dispatch. Trivial
  defaults go in their package; consequential decisions are rulings
  (work-tracking).
- Append evidence to its report and link it from the issue or board.
- Promote ratified conclusions that future implementation, operation or
  maintenance needs into their canonical owners in the same pass as the
  reality-changing work, keeping working artifacts as evidence. Link evidence
  where it changes interpretation; scratch links are optional context, and
  contracts stay complete without them.
- Before removing sole provenance from a legacy tracker, preserve it in its
  owner or `history/`.

## Recovery and closure

- Recover checkpoint, next work and authority from the epic and its views,
  then from the goal owners.
- At arc close, run the work-tracking arc close. At phase boundaries or
  architecture resets, review affected owners and links (a topic inventory
  when cross-document changes or uncertain ownership warrant it): classify
  each as canonical, narrow reference, `history/` or redundant. Check status
  and milestones, single ownership, resolving links and index authority;
  reconcile terminology, versions, migration identities and implementation
  claims across owners and entry points.
