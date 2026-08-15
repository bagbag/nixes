# Board files (shared convention)

Keep one living board per multi-step arc at
`.scratch/<topic-slug>/<arc-slug>/board.md`. It is transient coordination
state, not a durable project conclusion. Supervisor and autopilot use the same
filename and shape. Keep a concise append-only index at `log.md` and rotate
complete former boards into `history/` at coherent phase boundaries.

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
  task · status); a mutable current-decisions summary; full pending
  ratification items; a concise minor-decisions section; pending decisions and
  scope proposals; verified vs. taken-on-a-worker's-word; external-validation
  items (claim · owner · status · evidence · affected behavior);
  containment; and the next action.
- Keep the entire `.scratch/` tree gitignored. Do not store secrets there.

## Sync

- Update as you dispatch / decide / accept — never reconstruct later.
- A decision is recorded only when the file edit lands, not when stated in chat.
- Keep full decision and ratification records on the current board. Within a
  phase they are append-only: a reversal adds a new entry and updates the
  mutable current summary rather than rewriting the original.
- Keep `log.md` short and append-only: one dated sentence per rotated board,
  naming the phase or milestone and linking to its file under `history/`. It is
  an archive index, not a decision or evidence store.
- At a coherent phase boundary, move the complete `board.md` to
  `history/<date>-<phase>.md`, append its one-line index entry to `log.md`, and
  create a new current board containing only the carried-forward state. Do not
  copy the historical body into the new board. Recovery reads `board.md` first
  and follows `log.md` references only when provenance is needed.
- Re-sync the instant reality changes, and immediately when a compaction/context warning fires.

## Subagents

- Relay a board pointer in every worker brief: "Living board at `<path>`; flag any board/spec
  contradiction; return results in a form I can distil onto it."
- Distil worker results onto the board yourself; worker reports stay in transcripts.
