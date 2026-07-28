# Board files (shared convention)

Keep one living board per multi-step arc at
`.scratch/<topic-slug>/<arc-slug>/board.md`. It is transient coordination
state, not a durable project conclusion. Supervisor and autopilot use the same
filename and shape; autopilot's ratification log is a section of its board.

## Where & what

- Use lowercase kebab-case for topic and arc slugs.
- Each active lead owns exactly one topic, and each topic has one active lead.
  A lead may run multiple arcs for its topic; give each arc its own subdirectory.
  Record the stable topic slug, arc slug, mode, status, and durable target
  `docs/<topic-slug>/` at the top of each board.
- Keep `handover.md` beside the board. Create `evidence/` only when transient
  grounding artifacts need files of their own.
- Hold the current goal contract; live/queued workers or tracks (id · zone ·
  task · status); a mutable current-decisions summary; an append-only, dated
  decision or ratification log; pending decisions and scope proposals; verified
  vs. taken-on-a-worker's-word; external-validation items (claim · owner ·
  status · evidence · affected behavior); containment; and the next action.
- Keep the entire `.scratch/` tree gitignored. Do not store secrets there.

## Sync

- Update as you dispatch / decide / accept — never reconstruct later.
- A decision is recorded only when the file edit lands, not when stated in chat.
- The dated decision log is append-only: never edit an old entry. A reversal or superseding decision
  adds a new dated entry, then updates the mutable current-decisions summary to point to it. The
  original decision and its reversal both stay visible.
- Re-sync the instant reality changes, and immediately when a compaction/context warning fires.

## Subagents

- Relay a board pointer in every worker brief: "Living board at `<path>`; flag any board/spec
  contradiction; return results in a form I can distil onto it."
- Distil worker results onto the board yourself; worker reports stay in transcripts.
