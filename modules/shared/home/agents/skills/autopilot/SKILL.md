---
name: autopilot
description: >-
  Unattended work arcs: overnight runs, scheduled routines, long loops with no
  user available to decide. Tiered decision autonomy with a ratification
  journal, isolated worktree with checkpoint commits, hardened verification.
---

# Autopilot — unattended arcs with a ratification trail

Read `$HOME/.agents/skills/shared/worker-arcs.md` fully before planning or
delegating. It owns the common plan gate, worker brief, dispatch, acceptance,
containment, and bounded-retry rules. This skill adds unattended decision
authority, isolation, checkpoints, and stricter verification. Durable docs
follow `$HOME/.agents/skills/shared/durable-docs.md`.

## 0. Pre-flight — the last moment to ask

Before going unattended, the arc needs a contract: goal, scope boundary (in
AND out), done-criteria, and budget (time/windows). If any of these is vague,
ask NOW, while the user is still present. Then set up: create the worktree
and branch, create the journal, and run the whole-repo gate once to record
baseline counts. Register the context-monitor mode with
`bash "$HOME/.agents/bin/set-context-watch-mode" autopilot`; the helper
activates a supported monitor and otherwise safely does nothing.

## 1. Plan first — the whole night builds on it

Apply the shared worker-arc plan gate. The plan gets more scrutiny than
anything else in the arc:

- **Spend the user's remaining presence on the plan's decision points.** While
  they're still there (§0), every open point resolved is a real user decision;
  after they leave, the same point is at best a ratification item, at worst a
  parked track. Surface the plan's decisions at invocation, not at 3am.
- Mid-arc discoveries that contradict the plan are STOPs at plan level: park,
  journal, re-plan only the affected packages — never improvise divergence.

## 2. Decision tiers (replaces ask-the-user)

- **Trivial + reversible** → act, one line in the journal's minor log.
- **Non-trivial but reversible** → derive the decision as if presenting it to
  the user (options, honest for/against, the one you'd mark recommended), act
  on that recommendation, and journal it as a **ratification item**: what,
  options considered, choice, reasoning, and how to reverse it.
- **Irreversible, outward-facing, or scope-changing** → **park it**: journal
  the decision with your would-be recommendation, work around it where
  possible, and continue every track that doesn't depend on it. A parked
  decision stalls its track, never the arc.

Tier honestly: when unsure which tier applies, it's the higher one. And
"reversible" means reversible from the journal entry alone — if undoing it
would need remembered session context, it isn't reversible.

## 3. The journal

One append-only file, `autopilot-journal.md`, next to the handover note in the
project's durable gitignored scratch dir (the handover skill's convention): dated
entries for every ratification item, every parked decision, every contained
failure. It is the audit trail the user ratifies from — a decision that isn't
in the journal didn't happen; don't build on it.

The journal is autopilot's instance of the shared **board-files** convention
(`$HOME/.agents/skills/shared/board-files.md`): read it for the sync discipline and the
subagent mechanic.

## 4. Isolation and checkpoints

- Run the arc in a dedicated worktree on a branch named `autopilot/<arc>`.
  Invoking this skill grants exactly this much git: the worktree/branch setup
  from §0, then checkpoint commits on that branch (Conventional Commits),
  whenever the tree reaches a coherent state.
- NEVER: push, touch the user's branches or working tree, rewrite history,
  operate outside the worktree.
- After a crash or window gap, the branch + journal are the recovery point:
  re-orient from them, verify the tree state, continue.
- **Handover at every milestone.** Whenever a milestone lands (a work package
  accepted, a track closed — the same moments as checkpoint commits), run the
  `handover` skill (WRITE mode, note next to the journal) so the note is
  always current. After a window end, crash, or compaction, ORIENT from the
  note and continue the arc. You cannot end the session yourself; when
  usage runs high, keep the note current and work on until auto-compaction
  fires, then re-ground from the note.

## 5. Hardened verification

No user catches slips mid-run, so the gates tighten:

- The `verify`-gate threshold drops: gate every write-worker result that
  anything downstream will consume.
- The whole-repo gate runs before every checkpoint commit; any regression from
  the §0 baseline blocks the checkpoint — commit only coherent states;
  investigate or park.
- If the shared bounded-retry sequence fails, park the track with a diagnosis
  in the journal.

## 6. Hard ceiling — never on autopilot, no exceptions

Pushing or publishing anything; outward-facing actions (messages, PRs,
deployments, external APIs with side effects); migrations or writes against
real data; deletions outside the worktree; secret/credential handling; global
system changes. If the arc cannot proceed without one, that IS a parked
decision — journal it and move to another track.

## 7. The return: ratification report

**Stop at done.** When the arc's done-criteria are met, stop and report —
adjacent improvements you noticed are journal notes for the user, not new
tracks.

End every run (and every scheduled window) with a report built from the
journal: done-and-verified with actual gate numbers; ratification items;
parked decisions with recommendations; failures and parks with diagnoses; and
the merge-or-discard choice for the `autopilot/<arc>` branch. The user
ratifies; only then does work merge.
