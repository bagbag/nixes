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

Distinguish the eventual product outcome, the current approved checkpoint and
the work authorized now. A checkpoint may validate a narrow executable path
before broader capability delivery. Retain applicable integrity and authority
constraints; keep later acceptance requirements in their approved sequence.
Record sequencing changes in the milestone owner even when the product goal
is unchanged; the board links that checkpoint and owns its execution state.

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
`.scratch/<topic-slug>/<arc-slug>/`. Own current execution state in one brief,
current-only `board.md` per multi-step arc, shared by supervisor and autopilot:
`.scratch/<topic-slug>/<arc-slug>/board.md`.

The board owns the live execution summary. Update it in place. Keep superseded
instructions and completed-work narratives in history; retain their resulting
verified state and evidence links on the board.

- Use lowercase kebab-case for topic and arc slugs.
- Each active lead owns exactly one topic, and each topic has one active lead.
  A lead may run multiple arcs for its topic; give each arc its own subdirectory.
  Record the stable topic slug, arc slug, mode, status, and durable-owner links
  at the top of each board.
- Keep `handover.md` for recovery anchors, environment caveats and pointers
  to live state. Use the `handover` skill for recovery notes.
  Keep `log.md` as the history index; use `evidence/` and `history/` for detailed
  grounding and retained snapshots.
- Make the opening summary sufficient to select the next action: goal and
  checkpoint links, checkpoint completion evidence, verified position, next
  authorized work and return-to-user boundary, blockers/pending choices, explicit
  deferrals and independently authorized parallel tracks.
- Keep active ownership (id · zone · task · status) and necessary authority,
  containment and evidence qualifications below it. Link detailed plans, full
  decisions and reports rather than copying them. Distinguish executed evidence
  from author reports and unverified intent.
- Aim for a first-screen summary and a short board.

- Keep the entire `.scratch/` tree gitignored. Do not store secrets there.

### Worker coordination

Supply the board pointer in every worker brief and require workers to flag
board/spec contradictions. Workers report state deltas; the lead integrates
them into the current board and links substantive assessments. A board reference
grants reading and reporting; assign and sequence board edits explicitly.

## Synchronization

Replace affected board state at dispatch, plan/decision changes, material
completion, failed checks and changed blockers, and before recovery boundaries.
Remove settled work from the active queue; update the verified position and the
next action it unblocks. Record decisions and reconcile the plan before
dependent dispatch.
Append evidence to its report or history; replace the corresponding board summary.

Promote ratified conclusions needed by future implementation, operation or
maintenance into canonical owners, retaining working artifacts as evidence.
Update affected owners and entry points in the same pass as reality-changing
work. Link evidence when it changes interpretation; label ignored-scratch links
as optional context and keep the contract complete without those artifacts.

### Decision provenance

Record relevant trivial defaults in their owning work artifact when one exists;
otherwise keep them directly on the board while they affect current work.
Keep full consequential decisions and ratifications in an existing durable or
arc decision record; create one only when none fits. Preserve provenance
append-only there: refinements and reversals state what changed, why and which
decision they supersede. Summarize these records on the board with their current
disposition and owning-record link.
Before removing sole provenance from a legacy board, preserve it in its owner or
an archived snapshot. Reconcile affected owners, plans and next actions when
goals, sequencing or authority change; park only dependent work.

### Rotation and recovery

Archive a board snapshot when it preserves meaningful phase evidence or sole
legacy provenance, using `history/<date>-<phase>.md`; otherwise replace board
state in place. Keep `log.md` as an append-only archive index:
one dated sentence per rotated board, naming its phase/milestone and linking
to it, rather than storing decisions or evidence.

Recover the current approved checkpoint, next work and authority from the board,
then consult its goal owners and applicable constraints. Use handover for recovery
anchors and caveats. Read history when provenance is needed.

### Closure

At phase boundaries or material architecture resets, review affected owners and
links. Broaden to a topic inventory when cross-document changes or uncertain
ownership warrant it; classify entries as canonical, narrow reference,
superseded for `history/`, or redundant for removal.

Check consistent status and milestones, single ownership, resolving links and
current index authority. Reconcile stale terminology, versions, migration
identities and implementation-status claims across owners and entry points.
