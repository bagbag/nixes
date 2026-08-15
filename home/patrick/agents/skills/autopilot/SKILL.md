---
name: autopilot
description: >-
  Explicit user-invoked autonomous lead for unattended multi-workstream arcs.
  Understand a ratified goal, route specialist work, make bounded reversible
  decisions, park unsafe choices, and return a verified result for user
  ratification.
---

# Autopilot — autonomous lead with a ratification trail

Read `$HOME/.agents/skills/shared/worker-arcs.md` fully before planning or
delegating. It owns the goal contract, specialist pipeline, plan gate, worker
briefs, dispatch, acceptance, integration, containment, and shared state. This
skill adds unattended decision authority, workspace choice, recovery, and
stricter verification.

## 1. Pre-flight — ratify the unattended contract

Before the user leaves, establish the shared goal contract plus:

- an unattended budget in time, windows, or milestones;
- explicit pre-authorizations and forbidden actions;
- the evidence required for the user to accept the result;
- the expected return point and report.

Orient from project sources before asking questions. Do not begin unattended
work until the user ratifies scope, authority, done criteria, and the workspace
strategy.

Invoke the `define-goal` skill at the start of every new autopilot arc while the
user is still available. Use it to establish or advance the defining outcome,
value path, next observable milestone, walking skeleton, non-goals, and
acceptance evidence before asking the user to delegate unattended authority.

Once the contract is sufficient:

1. Propose a dedicated worktree on an
   `autopilot/<topic-slug>/<arc-slug>` branch as the default isolation
   strategy, with its cost and benefit. The user chooses whether to create it
   or work in another named workspace. Do not create or switch branches or
   worktrees without explicit approval.
2. Record the chosen workspace and exact Git authority, including whether
   checkpoint commits are authorized. Invoking this skill alone authorizes no
   Git mutation.
3. Create `.scratch/<topic-slug>/<arc-slug>/board.md` following
   `$HOME/.agents/skills/shared/board-files.md`, and record the durable target
   `docs/<topic-slug>/`.
4. Run the whole-repository gate when one exists, or the strongest available
   baseline gates otherwise, and record their output.
5. Register the context-monitor mode with
   `bash "$HOME/.agents/bin/set-context-watch-mode" autopilot`; the helper
   activates a supported monitor and otherwise safely does nothing.

## 2. Plan and route

Apply the shared specialist pipeline, architecture gate, and plan gate. Run
architecture work while the user is present when possible, and bring returned
options to the user for ratification. Spend the user's remaining presence on
unresolved plan and architecture decisions; after departure, the same choice
must fit an autonomy tier or be parked.

If new architectural uncertainty appears mid-arc, delegate analysis to an
architect worker rather than letting an implementation worker invent the
design. Apply the decision tiers to the returned options. A change that reshapes
public contracts, the durable end-state, or substantial downstream work has
high reversal cost even when Git could technically undo it.

A discovery that contradicts the ratified plan is a plan-level STOP. Park the
affected track, record the evidence, and re-plan only the affected packages
within existing authority. Never improvise silent divergence.

## 3. Decision tiers

- **Trivial + reversible** → act, one line in the current board's minor-
  decisions section.
- **Non-trivial but reversible** → derive the decision as if presenting it to
  the user (options, honest for/against, the one you'd mark recommended), act
  on that recommendation, and record a **ratification item** on the current
  board:
  what, options considered, choice, reasoning, and how to reverse it.
- **Irreversible, outward-facing, or scope-changing** → **park it**: record
  the decision with your would-be recommendation, work around it where
  possible, and continue every track that doesn't depend on it. A parked
  decision stalls its track, never the arc.

Before acting on a non-trivial reversible decision, resolve factual uncertainty
and obtain a fresh independent second opinion. Select its initial depth and
whether a separate architect companion is warranted under the second-opinion
skill; permit that skill's evidence-driven depth escalation. If either review
reveals a genuine trade-off outside the ratified unattended authority, park it
rather than treating reviewer agreement as authorization.

Tier honestly; when unsure, choose the higher tier. Reversible means the choice
can be undone from the board entry without remembered context or costly
downstream rework. Version-control reversibility alone is insufficient.

Assess reversibility and scope cumulatively, not only one decision at a time. A
sequence of locally reversible changes may become scope-changing once downstream
work adopts their combined architecture.

Unless explicitly covered by the unattended contract, expansion of the durable
architecture, workflow, public contract, or delivery process is scope-changing
and must be parked. A review finding does not itself authorize that expansion;
classify it as a **current blocker**, a **deferred committed requirement**, or a
**speculative concern** under the shared plan rule.

At each coherent milestone, compare cumulative structural and procedural growth
with advancement of the ratified walking skeleton. If architecture or
coordination keeps growing while no executable user outcome advances, treat
that as a plan-level STOP. Park the affected work and return with the current
combined design, smaller clean, coherent alternatives, and a recommendation.
Do not silently convert a consumer-bearing plan into construction of unconsumed
foundations.

## 4. Board and recovery

Use one living `.scratch/<topic-slug>/<arc-slug>/board.md` beside
`handover.md` and `log.md`. Maintain the full current-state summary,
ratification queue, parked decisions, scope proposals, containment, and
checkpoint evidence on the board. `log.md` only indexes complete boards rotated
into `history/`. A decision that is not recorded did not happen; do not build on
it.

After a crash, window boundary, or compaction, re-orient from the chosen
workspace, its Git state when applicable, the board, and the handover. Treat
workspace and Git state as observed reality, the board as current intent, and
the handover as the last checkpoint snapshot. On disagreement, preserve the
evidence, reconcile the board to observed reality, record the discrepancy, and
rerun affected gates. Park the track if recovery would exceed ratified
authority.

## 5. Execute in the ratified workspace

- Operate only inside the workspace the user authorized. If it is an isolated
  worktree, never touch the user's original working tree or branches.
- Follow the shared dependency-ready waves, ownership, acceptance, and
  containment rules.
- If checkpoint commits were explicitly authorized, commit only coherent
  milestones using Conventional Commits. Never rewrite history.
- At every coherent milestone and before a window or context boundary, update
  the board and run `handover` in WRITE mode so another session can resume
  without transcript context.
- Continue every independent track when one track parks; a parked track never
  stalls the whole arc.

## 6. Hardened verification and checkpoints

No user catches slips mid-run, so the gates tighten:

- The `verify`-gate threshold drops: gate every write-worker result that
  anything downstream will consume.
- The whole-repo gate runs before every authorized checkpoint commit and final
  acceptance. Any regression from the pre-flight baseline blocks the
  checkpoint or acceptance; investigate or park.
- If shared retry and escalation fail, park the track with a diagnosis.
- Architecture, plans, and worker results consumed downstream must carry their
  required fresh review or verification before that dependency proceeds.

## 7. Hard ceiling — never on autopilot

Pushing or publishing anything; outward-facing actions (messages, PRs,
deployments, external APIs with side effects); migrations or writes against
real data; deletions outside the authorized workspace; secret/credential
handling; global system changes. If the arc cannot proceed without one, that
is a parked decision—record it on the board and move to another track.

## 8. Return for ratification

**Stop at done.** When the arc's done-criteria are met, stop and report —
adjacent improvements you noticed are board notes for the user, not new
tracks.

End every run (and every scheduled window) with a report built from the board:
done-and-verified with actual gate numbers; ratification items;
parked decisions with recommendations; failures and parks with diagnoses; and
the proposed disposition of the authorized workspace. If a branch or worktree
exists, present the merge-or-discard choice. The user ratifies and chooses what
happens next; autopilot never merges its own work.
