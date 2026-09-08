# Project memory (shared convention)

## Durable ownership

Keep project-wide goals under `docs/` and topic contracts under
`docs/<topic-slug>/`. Reuse suitable existing owners and organize by product or
technical boundary. Keep enough context for a fresh reader to understand
commitments and milestones without scratch. Source and executable checks,
rather than documentation alone, establish implementation reality.

### Goals across arcs

Give project purpose, defining value, enduring constraints, and ratified
cross-topic priorities one canonical owner. A substantial topic owns its
distinct outcome, applicable milestone commitments, scope and acceptance.
Use `docs/goals.md` and `docs/<topic-slug>/goals.md` as defaults when suitable
owners do not already exist; a small project may use one document. Link these
owners prominently from project/topic entry points. Each level adds specificity
and links its parent rather than repeating it. Execution topics may reference
existing durable owners elsewhere; directory symmetry is not required.

Distinguish product non-goals from milestone exclusions and committed deferrals.
Keep committed deferrals under the outstanding-work convention below.
Milestones may span arcs; closing an arc does not retire a commitment.
Keep independently active milestones
distinguishable within their owners without another directory or registry.

Record ratified goal changes before dependent work consumes them. Child plans
cannot silently narrow parent commitments; a newer authorized user decision can
revise them. Goals describe intended outcomes, not execution permission.
Cross-topic or cross-project work links its applicable owners and dependencies;
unresolved priority conflicts return to the decision owner.

### Outstanding work across arcs

Keep material outstanding work in one durable owner. Reuse an existing suitable
section; otherwise use `docs/backlog.md`. Group by topic and split when volume or
independent ownership warrants it. Link owners from existing entry points and
reference their entries from boards and plans.

Distinguish committed deferrals, confirmed defects, open investigations and
unapproved proposals. Retain investigations and proposals with a concrete reason
to revisit them. Record approval status where relevant; recording an item or
reaching its revisit condition does not authorize execution.

Capture the problem or intended outcome, responsible area, reason for deferral,
revisit condition and resolution evidence. Preserve enough essential findings,
reproduction details and active containment to resume independently of scratch.

Reconcile relevant entries when setting scope, when revisit conditions change
and at arc closure. Record resolution with a concise disposition and supporting
evidence.

### Structure

Keep a small topic in one canonical document. Add navigation and subdivisions
when the amount of material or distinct ownership makes them useful.

- **`index.md` when navigation needs it**: goal and contract owners, durable
  product state, intended milestones, and read order.
- **Topical subfolders** when the topic needs them, organized by enduring boundary.
- **Separated `history/`** for superseded-but-retained material, clearly labeled.
- **Single-source concepts**: one owning section holds canonical wording;
  other docs reference it by name and anchor.
- **English names** for files, folders and identifiers; domain/legal prose may
  stay in its language.

## Arc state

Keep working plans, drafts, reviews and evidence in
`.scratch/<topic-slug>/<arc-slug>/`. Own current execution state in one living
`board.md` per multi-step arc, shared by supervisor and autopilot:
`.scratch/<topic-slug>/<arc-slug>/board.md`.

- Use lowercase kebab-case for topic and arc slugs.
- Each active lead owns exactly one topic, and each topic has one active lead.
  A lead may run multiple arcs for its topic; give each arc its own subdirectory.
  Record the stable topic slug, arc slug, mode, status, and durable-owner links
  at the top of each board.
- Keep `handover.md` and `log.md` beside the board. Use the `handover` skill
  for writing and consuming recovery notes. Create `evidence/` when grounding
  artifacts need their own files; keep rotated boards under `history/`.
- Link applicable goals and milestones; state the arc's contribution, scope,
  acceptance and execution authority. Include:

  - workers/tracks (id · zone · task · status);
  - current decisions with rationale, assumptions and owning-record links;
  - fully reviewable pending ratifications, minor decisions and scope proposals;
  - verified vs. attributed results and external-validation items
    (claim · owner · status · evidence · affected behavior);
  - containment, blockers and next action.

- Keep the entire `.scratch/` tree gitignored. Do not store secrets there.

### Worker coordination

Supply the board pointer in every worker brief and require workers to flag
board/spec contradictions. Distill their results onto the board and link
substantive assessments. A board reference grants reading and reporting;
assign write ownership explicitly and sequence board edits with the lead.

## Synchronization

Update current board state at dispatch, decision, acceptance and other reality
changes, and immediately on context warnings. Replace superseded summaries and
next actions. Record decisions before dependent work.

Promote ratified conclusions needed by future implementation, operation or
maintenance into canonical owners, retaining working artifacts as evidence.
Update affected owners and entry points in the same pass as reality-changing
work. Link evidence when it changes interpretation; label ignored-scratch links
as optional context and keep the contract complete without those artifacts.

### Decision provenance

Keep each full decision or ratification record in one existing owner: the board
if no other owner exists, an arc decision record, or its durable owner.
Preserve provenance append-only: refinements and reversals state what changed,
why, and which decision they supersede. Update current summaries and affected
work while retaining the earlier record; link full records from summaries.
When the board holds the sole full provenance, rotate it before replacing that
record. Reconcile affected owners, plans and next actions when goals or authority
change; park only work dependent on an unresolved contradiction.

### Rotation and recovery

At coherent phase boundaries, move the complete board to
`history/<date>-<phase>.md`. Keep `log.md` as an append-only archive index:
one dated sentence per rotated board, naming its phase/milestone and linking
to it, rather than storing decisions or evidence.

Create a current board carrying goal links, current and unresolved decisions,
authority, active ownership, blockers and next actions, with necessary history
pointers. For the current task, recovery follows goal-owner and board pointers;
read `log.md` and historical snapshots when provenance is needed.

### Closure

At phase boundaries or material architecture resets, review affected owners and
links. Broaden to a topic inventory when cross-document changes or uncertain
ownership warrant it; classify entries as canonical, narrow reference,
superseded for `history/`, or redundant for removal.

Check consistent status and milestones, single ownership, resolving links and
current index authority. Reconcile stale terminology, versions, migration
identities and implementation-status claims across owners and entry points.
