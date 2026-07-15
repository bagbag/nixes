# Board files (shared convention)

One living file per multi-step arc, in the project scratch dir — the durable record of arc state. The
supervisor skill's decision board and autopilot's `autopilot-journal.md` are its instances.

## Where & what

- Scratch dir (`short-term-context/` or the handover skill's scratch dir), recognizably named:
  `<arc>-board.md`, `board.md`, or the mode's name (`autopilot-journal.md`).
- Hold: live/queued workers or tracks (id · zone · task · status); an append-only, dated decision log;
  pending decisions with their state; verified vs. taken-on-a-worker's-word; the next action.

## Sync

- Update as you dispatch / decide / accept — never reconstruct later.
- A decision is recorded only when the file edit lands, not when stated in chat. A superseding decision
  edits the old line in the same moment (mark superseded, point to the new entry).
- Decision log is append-only: never edit an old dated entry; add a new one (a decision and its reversal
  both stay visible).
- Re-sync the instant reality changes, and immediately when a compaction/context warning fires.

## Subagents

- Relay a board pointer in every worker brief: "Living board at `<path>`; flag any board/spec
  contradiction; return results in a form I can distil onto it."
- Distil worker results onto the board yourself; worker reports stay in transcripts.
