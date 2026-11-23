# Plan protocol

Read
`$HOME/.agents/skills/shared/board-core.md`,
`$HOME/.agents/skills/shared/change-requests.md`,
`$HOME/.agents/skills/shared/board-coordination.md`,
`$HOME/.agents/skills/shared/decision-protocol.md`,
`$HOME/.agents/skills/shared/project-memory.md` and
`$HOME/.agents/skills/shared/acceptance.md` before step 1.

## Entry

Your session pulls `plan`. Only these sessions plan; others record gaps and remainders as new items or questions.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops.

1. **Position.** Run `agents board queue` and
   `agents board position`; read your session's checkpoint
   ([Arc state](../../shared/project-memory.md#arc-state)).
   Output: ready CRs and items, rulings to plan, idle holds, questions holding work.
2. **Released rulings.** Plan each under [Released rulings](#released-rulings).
   Output per ruling: `<id> → related <ids>, created <ids>, closed`.
3. **Frame.** Frame new or reframed outcome work under [Frame](#frame).
   Output: one line per frame field; open premises as question ids.
4. **Cut.** Cut and order items under [Cut work](#cut-work) and
   [Queue](#queue); run `agents board bd dep cycles`.
   Output: created ids, edge changes, `no cycles`.
5. **Dispatch.** When your session runs CRs through workers, dispatch under
   [Dispatch](#dispatch).
   Output: one line per worker: CR id, agent type, protocol.
6. **Integrate.** After each wave, run [Integrate](#integrate).
   Output: one line per integration gate: command, result.
7. **Reassess.** Run [Reassess](#reassess) at its triggers.
   Output: findings, or `no change`.
8. **Report.** Report under [Report](#report) and replace the checkpoint file.
   Output: the report.

## Stop

- A ruling conflicts with source or another ruling: raise a question
  found in it, hold only the affected work, plan the rest. Return
  evidence undermining a consequential ruling to its owner as a proposed
  revision; pause dependent work.
- Scope or authority would expand, or an irreversible or outward-facing action
  needs confirmation: bring it to the decider; continue independent work.
- Accepted work or a reversed decision proves wrong: run
  [Containment](#containment).
- The next authorized work recorded in the checkpoint file is done, or no
  useful authorized work remains: report and stop. "Continue" follows that
  record.

## Exit

No in-force ruling waits unplanned except on what its planning needs
([board-core.md](../../shared/board-core.md#questions-and-rulings) in-force row); `agents board check`
reports no deviation on the items this pass touched; ready work is
dispatched or claimable; the checkpoint file is current; the report is given.

## Released rulings

Plan a ruling right after its release; give one whose planning creates a new
item set (`agents board create --graph`) to a `plan` worker ([Cut work](#cut-work)).

1. Claim it: `agents board claim` when pulling `plan`,
   `agents board claim <id>` otherwise. Read the record and its
   rule owner section. A ruling settles only its stated choice; linked reports
   are evidence and hints are planning input; a supersession is an authorized
   revision. Act on each `fix:` line the claim prints, or state why it does
   not apply.
2. Make each open item the ruling changes wait on it
   (`agents board wait <item>… --on <ruling> --for "<what changes>"`); relate
   items it only informs (`agents board link <ruling> <item> --type relates-to`).
   Return an unclaimed review the ruling changes with
   `agents board return <cr> "<what changes>" --ruling <ruling>` (its
   consequences become the CR's items); for a held one,
   comment the change on the CR for its reviewer. Add the ruling id and owner
   anchor to each item's design, then drop the wait of each item whose text now
   carries the ruling (`agents board unlink <item> <ruling>`).
   Create missing work items; when cutting needs a design or spike first,
   file it as the first work and make the items that need it wait on it (the
   ruling itself waits only for a live question or a human gate).
   Add changelog and upgrade duties to affected
   items' acceptance.
3. For a revision, update every consumer of the changed decision: related
   items, briefs, dependencies and active workers whose premise changed. Refresh questions written against
   the superseded state. Repoint duplicate dependents to the keeper before
   `agents board bd --raw --yes duplicate <duplicate> --of <keeper>`.
4. Undefer items the ruling resolves; clear superseded authority and resolve
   the gates it covers.
5. Close: `agents board close <id> --reason "planned in <ids>"`.

## Frame

Orient from goal owners, the topic and current design before asking.
Establish the outcome's contribution to its milestone:

| Field | Content |
|---|---|
| Identity | Topic and arc slugs. |
| Outcome | Value path and material hypotheses. |
| Contract | Scope, exclusions, done criteria and evidence, constraints, compatibility, the user's quality criterion. |
| Product path | Product boundary and the next run: the smallest executable walking skeleton (what runs, where, what the user sees). |
| Open premises | Decisions, unknowns, empirical assumptions. |

- Open or resume the outcome's topic (label `topic:<topic-slug>`, carried by
  its CRs) under [Topics](../../shared/board-coordination.md#topics) and
  `$HOME/.agents/skills/shared/project-memory.md`; the user's acceptance of an
  outcome is a milestone.
- A slice is architecture-opening when it opens boundaries, public contracts,
  data flow, mechanisms or the clean end state.
- Commission an `architect` before cutting work for an architecture-opening
  slice, or when cutting would invent architecture. Use ratified design or a
  strong pattern when it settles the work. Cut work only after load-bearing architecture is ratified
  or authorized by the role. Architect results grant no authority.
- File a `kind:design` item first in a slice's CR, the slice's other items
  waiting on it, when the slice is architecture-opening or its reversal would
  be costly. Continue other slices
  on settled items.
- Use `explore-options` for a broader choice set or when options share a
  consequential untested assumption. Use `second-opinion` for decision
  challenges and `review` for architecture assessment.
  Keep authors and reviewers separate.

## Cut work

- Cut items under [Work items](../../shared/board-core.md#work-items) and
  group them into [change requests](../../shared/change-requests.md#change-requests)
  (CRs): one CR per topic of a request, split only where the user would
  plausibly accept one part and reject another; five small cleanups are one
  CR. Every item gets `--parent <cr>`; a CR carries its topic label. Split,
  merge or reorder items for a cleaner end state.
- Designed work: its design items (`kind:design`) commit the design to its
  topic doc under `docs/` in the same CR as the implementation. A separate
  design CR is the exception and names its reason; its `look` is `before` when the design opens a
  [one-way door](../../shared/decision-protocol.md#decision-authority) on the
  next run's path, and dependents wait on it
  ([Waiting and stacks](../../shared/change-requests.md#change-requests)).
- An item that waits differently from its CR moves to its own CR
  (`agents board move <item> --to <cr>`); an item never sits outside a CR.
- Set a CR's `look` or `view` only to override the defaults, naming the reason
  on the CR in a line that mentions the setting. Order CRs by dependencies:
  independent CRs run in parallel, overlapping work gets a dependency edge
  (the later CR stacks on, or waits for, the earlier).
- Write each item's expected behavior as short examples (input → result) in
  its design, and the tests worth writing (global instructions' Writing code) in
  its acceptance.
- Item text states acceptance, not reviewer or review depth
  ([Review policy](../../shared/acceptance.md#review-policy)).
- Place each new CR in or out of the open milestone under
  [Milestones](../../shared/board-coordination.md#milestones).
- Use a separate plan for cross-item reasoning, blast-radius integration
  checkpoints and cheap assumption tests that items cannot hold.
- Distinguish approved checkpoints from later product acceptance using
  `define-goal`'s Challenge acceptance. Name executable results and evidence;
  label infrastructure-only evidence as such.
- Trace shared behavior's input, mapping and execution before dividing
  ownership. Assign one owner per file, shared contract, invariant and
  cross-document concept; merge, extract or sequence overlaps. Link dependent
  items to the invariant owner, decisive checks and consumers.
- Prefer vertical consumer paths. Foundation-only work names its concrete
  dependency, earliest runnable consumer checkpoint and why validation cannot
  happen there sooner.
- Justify and defer additions under the decision protocol's
  [End-state criteria](../../shared/decision-protocol.md#end-state-criteria).
  Implement together changes that would immediately reshape the same public
  contract; defer orthogonal capabilities. Return ceremony for explicit
  decisions; drop speculative scope.
- Before freezing a public API, sketch declarations, registration and runtime
  calls against the strongest analogous API. Challenge brittle literals,
  duplicate names and unnecessary wrappers; freeze on coherent representative
  consumer use.
- Probe novel load-bearing assumptions before dependent work. Plan golden
  examples and hand-verified fixtures for domain-heavy work.
- For material decomposition or integration uncertainty, assign `plan`.
  Before dispatch, have a `review` worker assess each planning pass a `plan`
  worker wrote or that rewrites existing items: coverage, grounding,
  dependencies, integration, verification, silent failures. Put its verdict
  in one comment on the planned CR or in-force ruling (without a board, in
  the plan file). Check other planning (added items or acceptance lines,
  regroupings) yourself.

## Queue

- Order work under [Milestones](../../shared/board-coordination.md#milestones);
  rank by per-item [Priority](../../shared/board-core.md#priority).
- Distinguish source authoring, execution, review and final acceptance. A
  proposal grants no approval.
- Track every remainder as an item, a wait or a deferral (someday, with an
  optional revisit day); re-check remainders after planning rulings.
- Commission a plan or inventory only for a named executable result and the
  missing fact it establishes.

## Dispatch

- Repairs name the work they unblock; return there at closure.
- Keep a worker on every CR `agents board queue` lists for your pulls, up to the session's worker cap
  (`agents board position`: `workers <active>/<cap>`).
  When a worker ends, finish the bookkeeping the next dispatch depends on (its
  hand-over, the board state a new worker relies on), integrate its result
  under [Integrate](#integrate), then refill before other bookkeeping.
- Brief a worker on each no-commit task you claim. A step only the user can
  take is a human gate (`agents board gate create --blocks <item> --reason
  "<why>"`), shown in the user's view.
- Give each worker one CR. Brief: the CR id, the protocol path for its kind
  (`$HOME/.agents/skills/role/SKILL.md`, claimed-item table) and only the
  deltas under [Brief](#brief).
- Send review to a session pulling `review` when one is active; otherwise
  dispatch a fresh-context worker that did not author the CR: `review`, or
  `deep-review` for an item a review escalated.
- Dispatch dependency-ready waves of CRs; shared contracts are sequenced by
  dependency edges. Use native liveness, wait
  and resume. Run [Reassess](#reassess) before large fan-out.
- Interpret control messages by their target: you, one change or workers.
  "Keep workers running" leaves them running until revoked.
- To re-dispatch a CR an ended worker holds, brief a new worker with its id;
  its claim takes it over.
- Relay a destructive action's confirmation to a worker only when
  orchestration preserves it as trusted. Inspect each CR's worktree status
  after waves; attribute unexplained changes, possibly the user's, and leave
  them in place.
- Treat workers' returned choices and disclosed judgment calls as decisions
  under [Decision authority](../../shared/decision-protocol.md#decision-authority);
  repair mistakes with the warm worker. Inspect a contradictory STOP before
  overriding it; the brief may be wrong.

## Brief

- Reference authoritative sources, skills and ruling owner sections by id and
  anchor instead of copying rule text. Keep briefs as deltas to the item.
- Add no-touch paths, assumptions, STOP conditions and checks. Grant writing
  and running tests separately; a stop on running them does not forbid
  writing them.
  Forbid assessor fixes in a review brief while the author is still active in
  the reviewed files.
- When evidence mixes material the brief doesn't grant, including conclusions
  that would anchor an independent assessor, pass only the granted paths and
  fields, preparing a filtered view when needed; never the mixed source with
  instructions to filter it.
- Give the topic label and milestone; put a substantial brief into the item.
- Relay project-specific rules, excluding generic role discipline. Add
  anti-regression STOPs for reversed decisions still encoded in old sources.
- References grant reading, not writing; the item ids grant board writes on
  those items. Prepare directories when worker permissions require it.

## Integrate

- Accept each finished worker result (its CR handed over, checks stored, run
  its integration gate) before dispatching new work. A gate that cannot run
  becomes the next item.
- Follow implementation with tests, review, focused repair closure and an
  integration check. Add planning or opinions only for distinct questions.
- Run cross-item checks through intended interfaces. At each integration
  checkpoint, execute the combined consumer path and cross-boundary
  invariants under [Evidence and gates](../../shared/acceptance.md#evidence-and-gates).
- Out-of-contract work and cleaner out-of-scope repairs stay proposals until
  the role's authority covers them.

## Reassess

Before large fan-out, at milestones, after containment and when evidence or
cumulative changes affect the frame, scope or boundaries: assess the combined
end state for missing general mechanisms, asymmetric cases, duplicate owners,
silent failures, dead weight and doc drift; name the next executable outcome
and blockers. When the next run is set or changes, defer each open CR or task
of the outcome it does not need (a someday: `agents board defer`), undefer the
deferred ones it needs, and list both in the report. List the ready milestones
`agents board position` shows, for the user's acceptance
([Milestones](../../shared/board-coordination.md#milestones)). Bring
material changes to the decider before dependent dispatch. End rethinking
when remaining unknowns are empirical or further
yield is cosmetic.

## Containment

For a reversed decision or accepted work that proves wrong: record the
ruling, stop consumers, map affected code and docs, reopen owners with warm
workers, re-verify dependents and record the error and its containment.

## Report

- At meaningful updates, report **Accepted** (new results and decisive
  evidence), **Moving** (active work and holders; authoring, review, repair and
  gates separately), **Bottleneck** (constraint and action) and **Next
  result** (next executable outcome and needed decision).
- Report failed and unrun gates; test counts support evidence, not progress.
- Before closing an outcome, name what was independently verified, which
  load-bearing claims remain attributed, where failures would leave residue
  and what to check if the result were wrong. Account for workers, decisions,
  partial work, failures and coordination misses with impact and prevention.
