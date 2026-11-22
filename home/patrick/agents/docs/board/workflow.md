# Risk-tiered board workflow

Design target, released 22.11.2026 (release r2). The board model
(`nixes-r7p7f`) absorbs it; `nixes-cop95` implements it.

## Tiers

- Reversible work proceeds: the agent takes the safe default, records each
  choice that had a realistic alternative, and the user judges it afterwards
  (`nixes-3w9zo`).
- One-way doors and scope changes are asked up front and hold only the
  affected item.
- Landing on the local target is reversible. The user's gate sits on the
  irreversible actions: push, install or rebuild, a migration run on real
  data, messages to outside parties.

## Landing

- `agents board setup` writes `look` `after` when `--look` is not given; an
  existing project keeps its setting (this one stays `before`). A change
  request gets `before` only with a named one-way or scope reason
  (`nixes-xnji7`).
- Handover closes the items still open, with the handover range; closing an
  item mid-work stays (`nixes-rm19q`).

## Filing

Intent verbs replace generic `create` (`nixes-fe4am`):

| Verb | Writes |
|---|---|
| `file "<title>" -t <type>` | new work and its own change request |
| `add <cr> "<title>" -t <type>` | an item in an existing change request |
| `ask` | a question |
| `create --graph <plan>` | a planned item set |

## Designs

Direction choices (scope, one-way doors) are questions asked before the work.
The design text lands with its implementation in the same change request; a
separate design change request is the exception and names its reason
(`nixes-lwf8q`; revises the design-only rule of
[ordinary-design-requests.md](ordinary-design-requests.md)).

## The user's after-the-fact look

- Each two-way choice is one ruling record, in force at once and marked
  unratified: the chosen option, the one not taken, why, and how to reverse
  it (`agents board choice …`). The user ratifies lists of choices
  (`ratify <ids…> yes|no`); a no files a follow-up from the reversal. No
  landing ratification task and no separate confirmation question
  (`nixes-ekkx4`; supersedes that part of `nixes-qrnqo`).
- "Landed since your last look": derived from landed change requests and one
  marker per person; each row shows the outcome and how to see it.
- `agents board cr diff <id>` shows a landed change request's range
  (`check_base_tip`..`landing`; landing is a fast-forward, so the range stays
  intact on the target). `agents board review open <id>` opens a landed one
  with that range as upstream; edits there become a follow-up.

## Waits and links

- One blocking relation, written on the waiting item with what it uses:
  `agents board wait <item> --on <producer> --for "<input>"`; plan nodes
  carry `waits_on: [{on, for}]`. Every write and dry run prints the sentence
  ("X waits on Y for …"); a cycle is refused at the write (`nixes-ikbb4`).
- Waiting items are work items and milestones; a change request's waits
  follow from its items. Objects: items, change requests (their landing),
  gates, decisions.
- Other relations: part of, duplicate of, ruling context, supersedes.
  Found-in is a field on the found item, so bd's one link per pair stays
  free for the real relation.
- `blocks` and bd's other spellings are refused, naming the new form.

## Old data

board-migrate converts every stored old form, closed history included: link
spellings, legacy design waits, checkpoint records. The runtime keeps no
legacy readers; `check` reports an unknown form for board-migrate
(`nixes-z24ge`).
