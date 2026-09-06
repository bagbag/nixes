---
name: handover
description: >-
  Write or consume a session handover note so work continues losslessly in a
  fresh session. Use when the user invokes the handover skill, says "write a handover",
  "continue this in a new session", before compaction with meaningful state —
  and at session start when the active arc has a handover.md note under .scratch/.
---

# Handover

Write or consume the state needed to continue in a fresh session.

## Location and ownership

Use `.scratch/<topic-slug>/<arc-slug>/handover.md` beside the arc's board. The
user or active lead supplies the slugs. Ask for missing paths and keep
`.scratch/` gitignored. WRITE may create the assigned arc directory; ORIENT uses
the supplied note and existing arc.

## WRITE

Synchronize the existing board, decision records, and project owners affected by
the work. Keep transient decisions on the board and enduring decisions in their
canonical owner. Then record:

- **Anchor:** date/time, branch, HEAD, and the JSON fingerprint from
  `python3 "$HOME/.agents/bin/worktree-fingerprint" .` in the active workspace.
  It covers staged entries, assume-unchanged/skip-worktree flags, Git status,
  and tracked/nonignored untracked contents, including symlinks and initialized
  submodules. Ignored files and Git configuration are outside its scope.
  Capture it with workspace writers idle and retry any reported concurrent
  change. If the helper cannot capture the workspace, record that limitation
  explicitly and return the issue to the lead.
- **State:** verified work and its evidence, in-progress work, remaining work,
  and claims still taken on a worker's word.
- **Decisions:** pointers to the current board or enduring decision owner.
- **Next actions:** priority order and enough context to begin each cold.
- **Open questions:** parked decisions and recommendations.
- **Gotchas:** relevant environment constraints and intentional oddities.
- **Checks:** verification commands, expected results, and authorized effects.

Use source and artifact pointers for reusable context. Keep session-specific
worker identifiers in the live board; describe continuation work by its task and
owned paths in the handover. If there is no board, the note may carry transient
state itself. Create further records only when the work needs them.

## ORIENT

Read the note and compare its fingerprint with current workspace state before
running checks that may create artifacts. Investigate differences and preserve
user changes. A matching fingerprint establishes file state within the helper's
scope; it does not establish that the recorded claims are correct. Read linked
decision or evidence records when their details govern the next action.

Run the relevant verification commands within current authorization. Account for
declared output artifacts separately from changes present at arrival. Continue
the recorded authorized next action when its assumptions and priority still
hold. Return material changes in scope, evidence, or priority to the user or
active lead; unattended work follows its existing parking policy.

Update the note in WRITE mode when handover state materially changes.
