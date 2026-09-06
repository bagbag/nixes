# Board files (shared convention)

Keep one living board per multi-step arc at
`.scratch/<topic-slug>/<arc-slug>/board.md`. It is transient coordination state.
Supervisor and autopilot use the same filename and shape. Keep a concise
append-only index at `log.md` and rotate complete former boards into `history/`
at coherent phase boundaries.

## Where & what

- Use lowercase kebab-case for topic and arc slugs.
- Each active lead owns exactly one topic, and each topic has one active lead.
  A lead may run multiple arcs for its topic; give each arc its own subdirectory.
  Record the stable topic slug, arc slug, mode, status, and durable target
  `docs/<topic-slug>/` at the top of each board.
- Keep `handover.md` and `log.md` beside the board. Create `evidence/` only when
  transient grounding artifacts need files of their own; keep rotated boards
  under `history/`.
- Hold the current goal contract; live/queued workers or tracks (id · zone ·
  task · status); a mutable current-decisions summary with rationale and material
  assumptions; full pending ratification items; a concise minor-decisions
  section; pending decisions and
  scope proposals; verified vs. taken-on-a-worker's-word; external-validation
  items (claim · owner · status · evidence · affected behavior);
  containment; and the next action.
- Keep enough current context on the board to choose the next action: decisions,
  rationale, authority, blockers, and next steps. Full provenance may be linked;
  recovery reads linked records when their details govern the next action.
- Keep the entire `.scratch/` tree gitignored. Do not store secrets there.

## Sync

- Update at dispatch, decision, and acceptance so the board reflects events
  as they happen.
- Record current decisions and their owning-record links before dependent work
  consumes them. Keep the board focused on current state and evidence links,
  rather than repeating acceptance chronology from reports or handovers.
- Keep each full decision or ratification record in one existing owner: the
  board if no other owner exists, an arc decision record, or its durable owner.
  Preserve provenance append-only: refinements and reversals state what changed,
  why, and which decision they supersede. Update current summaries and affected
  work while retaining the earlier record. Keep pending ratification items fully
  reviewable; promote enduring decisions to durable ownership and link to them
  instead of duplicating their full text.
- Keep `log.md` short and append-only: one dated sentence per rotated board,
  naming the phase or milestone and linking to its file under `history/`. It is
  an archive index, not a decision or evidence store.
- At a coherent phase boundary, move the complete `board.md` to
  `history/<date>-<phase>.md`, append its one-line index entry to `log.md`, and
  create a new current board containing the carried-forward state and pointers
  to the relevant history. Recovery reads `board.md` first
  and follows `log.md` references only when provenance is needed.
- Re-sync the instant reality changes, and immediately when a compaction/context warning fires.

## Subagents

- Relay a board pointer in every worker brief: "Living board at `<path>`; flag any board/spec
  contradiction; return results in a form I can distil onto it."
- Distill worker results onto the board yourself and link to substantive
  assessments at their assigned report paths.
- A board reference grants reading and reporting. Assign board write ownership
  explicitly when a worker must edit it, and sequence those edits with the lead.
