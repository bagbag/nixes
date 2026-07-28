# Durable docs (shared convention)

Keep each topic's durable design and architecture record under
`docs/<topic-slug>/`. The topic slug is stable across execution arcs. Durable
conclusions graduate here from transient board state; a fresh agent must be
able to orient from this directory alone.

## Structure

- **Honest `index.md`**: current state, next action, locked decisions,
  read order, and file index. Keep live state only; superseded material belongs
  in `history/`.
- **Topical subfolders** when the topic needs them, not a flat accumulation
  (for example model, pipeline, evidence, legal, or build).
- **Separated `history/`** for superseded-but-retained material, clearly
  labeled with what it contains.
- **Single-source cross-doc concepts**: one owning section holds canonical
  wording; other docs reference it by name and anchor instead of restating it.
- **English names** for files, folders, identifiers (domain/legal prose may stay in its language).

## Sync

Update durable docs in the same pass as the reality-changing work. Keep
`index.md` sufficient for cold orientation. When a single-sourced concept
changes, edit its owning section.
