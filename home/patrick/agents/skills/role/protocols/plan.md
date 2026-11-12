# Plan protocol

Read
`$HOME/.agents/skills/shared/board-core.md`,
`$HOME/.agents/skills/shared/change-requests.md`,
`$HOME/.agents/skills/shared/board-coordination.md`,
`$HOME/.agents/skills/shared/decision-protocol.md`,
`$HOME/.agents/skills/shared/project-memory.md` and
`$HOME/.agents/skills/shared/acceptance.md` before step 1.

## Entry

Your session pulls `plan`, or its role is solo or autopilot. Only these
sessions plan; others record gaps and remainders as new items or questions.

## Steps

Give each step's output as one line when it passes; add detail only for
findings or stops.

1. **Position.** Run `board queue` and
   `board position`; read the checkpoint file
   ([Arc state](../../shared/project-memory.md#arc-state)).
   Output: ready CRs and items, rulings to plan, idle holds, questions holding work.
2. **Released rulings.** Plan each under [Released rulings](#released-rulings).
   Output per ruling: `<id> → related <ids>, created <ids>, closed`.
3. **Frame.** Frame new or reframed outcome work under [Frame](#frame).
   Output: one line per frame field; open premises as question ids.
4. **Cut.** Cut and order items under [Cut work](#cut-work) and
   [Queue](#queue); run `board bd dep cycles`.
   Output: created ids, edge changes, `no cycles`.
5. **Dispatch.** When your session runs CRs through workers (solo and
   autopilot always do), dispatch under [Dispatch](#dispatch).
   Output: one line per worker: CR id, agent type, protocol.
6. **Integrate.** After each wave, run [Integrate](#integrate).
   Output: one line per integration gate: command, result.
7. **Reassess.** Run [Reassess](#reassess) at its triggers.
   Output: findings, or `no change`.
8. **Report.** Report under [Report](#report) and replace the checkpoint file.
   Output: the report.

## Stop

- A ruling conflicts with source or another ruling: raise a question
  discovered from it, block only the affected work, plan the rest. Return
  evidence undermining a consequential ruling to its owner as a proposed
  revision; pause dependent work.
- Scope or authority would expand, or an irreversible or outward-facing action
  needs confirmation: bring it to the decider; continue independent work.
- Nothing seems ready: before declaring the goal blocked, cross-check every
  open item across its branches with full ready, list and dependency views;
  name each candidate's next action, authority and exact blocker. Establish
  exhaustion from action-specific blockers, not from unchanged queue ids or
  counts.
- Accepted work or a reversed decision proves wrong: run
  [Containment](#containment).
- The next authorized work recorded in the checkpoint file is done, or no
  useful authorized work remains: report and stop. "Continue" follows that
  record.

## Exit

No released ruling waits unplanned except on what its planning needs
([board-core.md](../../shared/board-core.md) released row); `board check`
reports no deviation on the items this pass touched; ready work is
dispatched or claimable; the checkpoint file is current; the report is given.

## Released rulings

1. Claim it: `board claim` when pulling `plan`,
   `board claim <id>` otherwise. Read the record and its
   rule owner section. A ruling settles only its stated choice; linked reports
   are evidence and hints are planning input; a supersession is an authorized
   revision. Act on each `fix:` line the claim prints, or state why it does
   not apply.
2. Block each open item the ruling changes on it
   (`board block <item>… --on <ruling> --reason "<what changes>"`); relate
   items it only informs (`board bd dep relate <ruling> <item>`). Add the
   ruling id and owner anchor to each item's `--design`.
   Create missing work items; when cutting them needs a design or spike first,
   create it, block the ruling on it and stop: the ruling returns to planning
   when it closes, and the design never waits on the ruling.
   Add changelog and upgrade duties to affected
   items' acceptance.
3. For a revision, update every consumer of the changed decision: related
   items, briefs, dependencies and active workers whose premise changed. Refresh questions written against
   the superseded state. Repoint duplicate dependents to the keeper before
   `board bd duplicate <duplicate> --of <keeper>`.
4. Undefer items the ruling resolves; clear superseded authority and resolve
   the gates it covers.
5. Close: `board bd close <id> --reason "planned in <ids>"`.

## Frame

Orient from goal owners, the goal epic and current design before asking.
Establish the outcome's contribution to its milestone:

| Field | Content |
|---|---|
| Identity | Topic and arc slugs. |
| Outcome | Value path and material hypotheses. |
| Contract | Scope, exclusions, done criteria and evidence, constraints, compatibility, the user's quality criterion. |
| Product path | Product boundary and smallest executable walking skeleton when architecture or flow changes. |
| Open premises | Decisions, unknowns, empirical assumptions. |

- Create or resume the outcome epic (readable title stating the outcome, label
  `topic:<topic-slug>`) under
  [Epics](../../shared/board-coordination.md#epics) and
  `$HOME/.agents/skills/shared/project-memory.md`.
- Use `define-goal` when the milestone is unclear, purpose shifts, success is
  contested or scope grows without value-path progress.
- A slice is architecture-opening when it opens boundaries, public contracts,
  data flow, mechanisms or the clean end state.
- Commission an `architect` before cutting work for an architecture-opening
  slice, or when cutting would invent architecture. Use ratified design or a
  strong pattern when it settles the work. Cut work only after load-bearing architecture is ratified
  or authorized by the role. Architect results grant no authority.
- Create a `design` item that blocks a slice's items when the slice is
  architecture-opening or its reversal would be costly. Continue other slices
  on settled items.
- Use `explore-options` for a broader choice set or when options share a
  consequential untested assumption. Use `second-opinion` for decision
  challenges and a fresh architect in REVIEW for architecture assessment.
  Keep authors and reviewers separate.

## Cut work

- Cut items under [Work items](../../shared/board-core.md#work-items) and
  group them into [change requests](../../shared/change-requests.md#change-requests)
  (CRs): one CR per topic of a request, split only where the user would
  plausibly accept one part and reject another; five small cleanups are one
  CR. Every item gets `--parent <cr>`; a CR sits under its topic epic. Split,
  merge or reorder items for a cleaner end state.
- Designed work is one CR that starts with only its design items and a
  `checkpoint`: `user` in a `look` `before` project, else `agent`. When the
  checkpoint passes, the CR returns to you: add the implementation items to
  it. Dependent CRs wait under
  [Waiting and stacks](../../shared/change-requests.md#change-requests);
  design-only dependents read the accepted design on its branch.
- Group items that sit in no CR into CRs per topic when they become due
  (items waiting on an open decision or design stay ungrouped until it is
  answered).
- Set each CR's `look` and `view` only to override the project defaults;
  name the reason on the CR. Order CRs by
  dependencies: independent CRs run in parallel, overlapping work gets a
  dependency edge (the later CR stacks on, or waits for, the earlier).
- Write each item's expected behavior as short examples (input → result) in
  its `--design`, and the tests worth writing (global instructions' Tests) in
  its `--acceptance`.
- State each agent checkpoint the CR needs in the CR.
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
  contract; defer orthogonal capabilities. Return ceremony and speculative
  scope for explicit decisions.
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
  in one comment on the planned epic or released ruling (without a board, in
  the plan file). Check other planning (added items or acceptance lines,
  regroupings) yourself.

## Queue

- Order work under [Milestones](../../shared/board-coordination.md#milestones);
  rank by per-item [Priority](../../shared/board-core.md#priority),
  including committed nonblocking consumers (`board holders`).
- Scope a user's stop to the exact action, file, decision or effect it names;
  continue authorized work outside it. Distinguish source authoring,
  execution, review and final acceptance. A proposal grants no approval.
- Track every remainder as an item, a `blocks` edge or a deferral with its
  revisit condition; re-check remainders after planning rulings.
- Commission a plan or inventory only for a named executable result and the
  missing fact it establishes.

## Dispatch

- Dispatch CRs that advance the approved checkpoint, remove demonstrated
  blockers or serve authorized parallel tracks, within authority and
  priority. Among equally ready CRs, prefer needed patterns, then smaller
  ones. Repairs name the work they unblock; return there at closure.
- Keep a worker on every independent ready CR up to the session's worker cap
  (`board position`: `workers <active>/<cap>`).
  When a worker ends, finish the bookkeeping the next dispatch depends on (its
  hand-over, the board state a new worker relies on), integrate its result
  under [Integrate](#integrate), then refill before other bookkeeping.
- Give each worker one CR. Brief: the CR id, the protocol path for its kind
  (`$HOME/.agents/skills/role/SKILL.md`, claimed-item table) and only the
  deltas under [Brief](#brief).
- Dispatch CR work only to artifact-writing agent types (global
  Orchestration).
- Send review to a session pulling `review` when one is active; otherwise
  dispatch a fresh-context worker that did not author the CR: `review`, or
  `deep-review` for an item a review escalated.
- Work inline under the global instructions' Orchestration.
- Dispatch dependency-ready waves of CRs; shared contracts are sequenced by
  dependency edges. Use native liveness, wait
  and resume. Run [Reassess](#reassess) before large fan-out.
- Interpret control messages by their target: you, one change or workers.
  "Keep workers running" leaves them running until revoked.
- Continue warm workers under the global Warm reuse. To re-dispatch a CR an
  ended worker holds, brief a new worker with its id; its claim takes it
  over.
- Run destructive actions under the global Filesystem rule and its
  Confirm-before-the-irreversible principle; relay that confirmation to a
  worker only when orchestration preserves it as trusted. Inspect each CR's
  worktree status after waves; attribute unexplained changes, possibly the
  user's, and leave them in place.
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
- Give the goal epic id. Link a `.scratch/` file for a substantial brief.
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
and blockers. Close each finished epic `board position`
lists under board-coordination [Epics](../../shared/board-coordination.md#epics);
list in the report the ones left open for the user's acceptance. Bring
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
