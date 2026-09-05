# Durable docs (shared convention)

Keep each topic's durable design and architecture record under
`docs/<topic-slug>/`. The topic slug is stable across execution arcs. Durable
conclusions graduate here from transient board state; a fresh agent must be
able to orient from this directory alone.

Durable documentation is the canonical reference for enduring product
contracts and decisions. Create or update
it only when a conclusion must outlive the arc and future implementation,
operation, or maintenance will rely on it.

Prefer updating an existing canonical owner over adding another document.
Working plans, alternative explorations, review reports, inventories,
verification evidence, coordination state, and intermediate acceptance records
remain under `.scratch/` unless a ratified conclusion from them becomes
necessary project knowledge. Promote the conclusion into its canonical owner
and retain the working artifact as transient evidence.

Documentation records intended contracts and decisions; it does not
independently prove that implementation satisfies them. Source, tests, and
executable gates establish implementation reality. Keep coordination of
documents and reviews on the existing board.

Cold orientation means enough current product context, canonical contracts,
decisions, and next action to proceed safely. Link to supporting evidence when
it materially changes how the reader should proceed. Organize durable
documentation around the product and enduring technical boundaries, not
workers, review rounds, dispatch waves, or temporary package status. Temporary
execution state belongs on the board under `.scratch/`.

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

## Closure audit

At a phase boundary or after a material architecture reset, inventory every
active document under the topic directory, excluding `history/`, and classify
it as:

- current canonical owner;
- current narrow reference;
- superseded material to move to `history/`; or
- redundant material to remove.

Then verify the active set as a whole: status and next action agree; each
concept has one owner; active documents contain no stale workflow names,
versions, migration identities, implementation-awaiting claims, or superseded
terminology; all links resolve; and the index lists only current authority.
Complete synchronization across the active owners as well as the index.
