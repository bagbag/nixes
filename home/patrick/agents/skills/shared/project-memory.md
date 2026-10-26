# Project memory (shared convention)

## Durable owners

| Content | Owner |
|---|---|
| Project purpose, defining value, product facts and principles, enduring constraints, ratified cross-topic priorities | One canonical project owner: `docs/goals.md` by default, or the project instructions' design principles where the project keeps them there. |
| Substantial topic outcome, milestone commitments, enduring plans, scope, acceptance | Existing suitable owner under `docs/<topic-slug>/`; `docs/<topic-slug>/goals.md` by default. |
| Topic contract, ratified specifications, design targets and rationale worth keeping | `docs/<topic-slug>/`. |
| Authoring convention | Coding style or skill. |
| Agent operating rule | Project instructions (`AGENTS.md`). |
| Current consumer-visible behavior | Module README, skill or `docs/`, shipped with the change that makes it true; the topic's design-target doc holds it until then. |
| Release notes | Changelog. |
| Outstanding work, decisions and their rationale | With a board: deferred items and decision records; `TODO.md` and `REVIEW.md` retire through `/board-migrate`. Without a board: `TODO.md`; decisions under `docs/<topic-slug>/`. |

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
  work, including sequencing changes with unchanged product goals. Track an
  approved checkpoint as its outcome epic's acceptance, or as a task when it
  spans outcomes.
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
- Reconcile at scope setting, changed revisit conditions and epic close. Close
  resolved items with disposition and evidence.

## Document structure

- For larger topics or distinct owners, use `index.md` for owners, product state,
  milestones and read order; use topical subfolders by enduring boundary.
- Give each concept one owning section; reference it by name and anchor.
- Keep `docs/<topic-slug>/` to current owners: released rules and accepted
  design targets, stated as current rules only. Proposals live on the board
  (design items, questions); superseded and stale material moves to a clearly
  labelled `history/`.
- Use English names; domain and legal prose may retain its language.
- Establish implementation reality from source and executable checks. Label
  unproven mechanisms "design intent — validation-pending".

## Arc state

- `$HOME/.agents/bin/board position` computes the position; epics hold no status
  (work-tracking [Epics](../shared/work-tracking.md#epics)).
- The planning session keeps a plain-prose checkpoint file,
  `.scratch/<topic-slug>/<arc-slug>/checkpoint.md`, replaced in place:
  verified position, next authorized work and return boundary, blockers by
  board id, pending choices, parallel tracks, and links to plans and reports.
  Distinguish executed evidence from author reports and intent. It holds no
  operating rules.
- Arcs may run in parallel. Each arc has its own outcome epic and
  `.scratch/<topic-slug>/<arc-slug>/` for plans, drafts, reviews, `evidence/`
  and `history/`.
- Use lowercase kebab-case slugs.

## Synchronization

| Event | Action |
|---|---|
| Work changes state | Update beads. |
| Plan/decision change, material completion, failed check, changed blocker, recovery boundary | Refresh the checkpoint file. |
| Decision before dependent dispatch | Record it and reconcile the plan; put trivial defaults in the item and consequential rulings in a decision record. |
| New evidence | Append to its report; link from issue or board. |
| Ratified conclusion changes reality | Promote needed implementation/operation/maintenance conclusions into their canonical owner in the same pass; retain working evidence. |
| Removal of sole legacy provenance | Preserve in its owner or `history/` first. |

Link evidence where it changes interpretation. Scratch links provide optional
context; keep contracts complete without them.

## Recovery and closure

- After compaction, resume or a crash, preserve the current task and newer
  user instructions. Recover holds, the approved checkpoint, next authorized
  work, deferrals, return boundary and authority from
  `$HOME/.agents/bin/board mine`, `$HOME/.agents/bin/board position` and the
  checkpoint file, then from the canonical project goal and the applicable
  topic goal and milestone; reconcile the next action with those commitments
  and existing authority.
- Re-read from tracking each item a summary names as pending or next before
  reporting or acting on it. Resume an existing arc only while it remains the
  current authorized task; keep later product acceptance in its approved
  sequence. Check the working tree and relevant evidence; reuse applicable
  pre-flight results.
- Close finished epics under work-tracking [Epics](../shared/work-tracking.md#epics).
- At phase boundaries or architecture resets, review affected owners and links;
  inventory the topic for cross-document changes or uncertain ownership.
- Classify each document as canonical, narrow reference, `history/` or redundant.
  Check status, milestones, single ownership, resolving links and index authority.
  Reconcile terminology, versions, migration identities and implementation claims
  across owners and entry points.
