# Project memory (shared convention)

## Durable owners

| Content | Owner |
|---|---|
| Project purpose, defining value, enduring constraints, ratified cross-topic priorities | One canonical project owner; `docs/goals.md` by default. |
| Substantial topic outcome, milestone commitments, scope, acceptance | Existing suitable owner under `docs/<topic-slug>/`; `docs/<topic-slug>/goals.md` by default. |
| Ruling destinations | Work-tracking's [Rulings](../shared/work-tracking.md#rulings) mapping. |
| Outstanding work | Deferred issues under work-tracking; retain a roadmap document's project-assigned purpose. |

- Reuse suitable owners; organize by product or technical boundary. Use one
  document for small projects or topics. Each level adds specificity and links
  its parent; entry points link owners. Execution topics may reference owners
  elsewhere; directory symmetry is optional.
- Keep commitments and milestones understandable without scratch. Separate
  product non-goals, milestone exclusions, committed deferrals, eventual
  outcomes, approved checkpoints and currently authorized work.
- Goals state outcomes, not execution permission. A child plan narrows a parent
  commitment only through a newer user decision. Closing an arc retires no
  milestone commitment; distinguish independently active milestones.
- For a narrow path-validation checkpoint, retain integrity, authority and later
  acceptance requirements in their approved sequence.
- Record ratified goal and sequencing changes in their owner before dependent
  work, including sequencing changes with unchanged product goals. Link
  checkpoints from the board.
- Link owners and dependencies for cross-topic/project work; return priority
  conflicts to the decision owner. On changed goals, sequencing or authority,
  reconcile affected owners, plans and next actions; park only dependent work.

## Outstanding work

- Record problem or intended outcome, area, reason, revisit condition, findings,
  reproduction details and active containment sufficient to resume without
  scratch.
- Label defects, investigations and unapproved proposals distinctly. Retain
  investigations and proposals only with a concrete revisit reason.
- Recording an item or reaching its revisit condition authorizes nothing.
- Reconcile at scope setting, changed revisit conditions and arc close. Close
  resolved items with disposition and evidence.

## Document structure

- For larger topics or distinct owners, use `index.md` for owners, product state,
  milestones and read order; use topical subfolders by enduring boundary.
- Give each concept one owning section; reference it by name and anchor.
- Place superseded material in clearly labelled `history/`.
- Use English names; domain and legal prose may retain its language.
- Establish implementation reality from source and executable checks. Label
  unproven mechanisms "design intent — validation-pending".

## Arc state

**Board:** root epic description under work-tracking; short, replaced in place.

| Order | Fields |
|---|---|
| Top | Topic/arc slugs, mode, status, owner links. |
| First-screen summary | Goal/checkpoint links and evidence; verified position; next authorized work and return boundary; blockers, pending choices, deferrals, parallel tracks. |
| Qualifications | Authority, containment, evidence limits; links to plans and reports. |

- Distinguish executed evidence from author reports and intent. Keep the summary
  sufficient to select the next action.
- Use one active lead per topic; it owns the board unless its mode assigns the
  board elsewhere. A lead may run several arcs, each with its own epic and
  `.scratch/<topic-slug>/<arc-slug>/` for plans, drafts, reviews, `evidence/`
  and `history/`.
- Use lowercase kebab-case slugs. Keep `.scratch/` gitignored and free of secrets.
- Give workers the root epic id and their issue; require board/spec contradiction
  reports. Board edits stay with the lead.

## Synchronization

| Event | Action |
|---|---|
| Work changes state | Update beads. |
| Plan/decision change, material completion, failed check, changed blocker, recovery boundary | Refresh the board. |
| Decision before dependent dispatch | Record it and reconcile the plan; put trivial defaults in the package and consequential rulings in work-tracking. |
| New evidence | Append to its report; link from issue or board. |
| Ratified conclusion changes reality | Promote needed implementation/operation/maintenance conclusions into their canonical owner in the same pass; retain working evidence. |
| Removal of sole legacy provenance | Preserve in its owner or `history/` first. |

Link evidence where it changes interpretation. Scratch links provide optional
context; keep contracts complete without them.

## Recovery and closure

- Recover checkpoint, next work and authority from the root epic and its views,
  then from goal owners.
- At arc close, run work-tracking's Arc close.
- At phase boundaries or architecture resets, review affected owners and links;
  inventory the topic for cross-document changes or uncertain ownership.
- Classify each document as canonical, narrow reference, `history/` or redundant.
  Check status, milestones, single ownership, resolving links and index authority.
  Reconcile terminology, versions, migration identities and implementation claims
  across owners and entry points.
