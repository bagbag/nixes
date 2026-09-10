---
name: handover
description: >-
  Write or consume a session handover note so work continues losslessly in a
  fresh session. Use when the user invokes the handover skill, says "write a handover",
  "continue this in a new session", before compaction with meaningful state —
  and at session start when the active arc has a board.md or handover.md under .scratch/.
---

# Handover

## Location

Use `.scratch/<topic-slug>/<arc-slug>/handover.md` beside the arc's board. The
user or active lead supplies the slugs. Ask for missing paths and keep
`.scratch/` gitignored. WRITE may create the assigned arc directory; ORIENT uses
the existing board or note.

## WRITE

Synchronize affected boards and canonical owners. With a board, keep the note
focused on recovery anchors and caveats; link live state rather than duplicating
it. Retain former notes as labeled snapshots only when needed. Record:

- **Anchor:** date/time, branch, HEAD, and the JSON fingerprint from
  `python3 "$HOME/.agents/bin/worktree-fingerprint" .` in the active workspace.
- **Orientation:** current-only board and applicable goal/checkpoint owners.
- **Recovery caveats:** environment constraints, non-obvious resumption hazards
  and evidence-validity limits; link details already on the board.
- **Checks:** pointers to commands, expected results and authorized effects;
  copy commands only when needed for cold recovery.

Keep live state on the board. With no board, record verified outcomes and
evidence, attributed claims, blockers, deferrals, next actions, permissions and
active ownership in the note. Capture the fingerprint with writers idle;
retry reported concurrent changes and disclose capture failures to the lead.
It covers Git-visible file state, including index flags, symlinks and initialized
submodules; ignored files and Git configuration are excluded.

## ORIENT

1. Identify the current authorized task, preserving newer user direction. Recover
   its current approved checkpoint, next action, deferrals and authority from the
   board (or note if no board exists). Consult linked goals and constraints;
   reconcile the plan with the approved sequence. Follow further decisions and
   evidence when they govern that action.
2. Compare the recorded fingerprint before artifact-producing checks. If absent,
   inspect current workspace state and treat prior file-state continuity as
   unverified. Investigate differences and preserve user changes. A match
   establishes file state within the helper's scope, not correctness of claims.
3. Run relevant authorized checks, distinguishing their outputs from arrival
   changes. Continue while the next action's authority, assumptions and priority
   hold. Return material scope, evidence or priority changes to the user/lead;
   unattended work follows its parking policy.
4. Refresh the note when recovery anchors or caveats materially change; update
   live execution state in the board, or the note when it is the sole owner.
