# Durable docs (shared convention)

A project's durable design/architecture docs (the docs dir, e.g. `docs/design/`, `docs/architecture/`) —
the record a fresh agent orients from. Distinct from board files (`skills/shared/board-files.md`, transient
scratch state); durable conclusions graduate off the board into these.

## Structure

- **Honest START-HERE index**: current state + next action + locked decisions + read-order + file index;
  live state only, no accreted `UPDATE`/`HISTORICAL` stack (that goes to `history/`). Rebuild it when it
  stops reading as "what is true now."
- **Topical subfolders**, not a flat pile (e.g. model / pipeline / evidence / legal / build).
- **Separated `history/`** for superseded-but-kept material, clearly labeled, with a one-line note of what
  it holds.
- **Single-source cross-doc concepts**: one owning section holds the canonical phrasing; other docs
  reference it by name + anchor, never re-describe.
- **English names** for files, folders, identifiers (domain/legal prose may stay in its language).

## Sync

Update in the same pass as the change that alters the doc — never batched. The index must let a future
session orient from it alone. On a change to a single-sourced concept, edit the owning section.
