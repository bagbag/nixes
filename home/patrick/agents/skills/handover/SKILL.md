---
name: handover
description: >-
  Write or consume a session handover note so work continues losslessly in a
  fresh session. Use when the user invokes the handover skill, says "write a handover",
  "continue this in a new session", before compaction with meaningful state —
  and at session start when the active arc has a handover.md note under .scratch/.
---

# Handover

## Location

Use `.scratch/<topic-slug>/<arc-slug>/handover.md` beside the arc's board. The
user or active lead supplies the slugs. Ask for missing paths and keep
`.scratch/` gitignored. WRITE may create the assigned arc directory; ORIENT uses
the supplied note and existing arc.

## WRITE

Synchronize affected boards and canonical owners. Write one current recovery
note with concise context and links; retain former notes as labeled snapshots
when needed. Record:

- **Anchor:** date/time, branch, HEAD, and the JSON fingerprint from
  `python3 "$HOME/.agents/bin/worktree-fingerprint" .` in the active workspace.
- **Goal and decisions:** applicable project/topic owners, milestone and board.
- **State:** verified outcomes with evidence, attributed claims, and remaining work.
- **Next actions:** priority, authority and context to start cold, including owned paths.
- **Blockers and gotchas:** parked choices, recommendations and environment constraints.
- **Checks:** commands, expected results and authorized effects.

Keep execution detail and worker identifiers on the board; the note carries
transient state itself when no board exists. Capture the fingerprint with writers
idle; retry reported concurrent changes and disclose capture failures to the lead.
It covers Git-visible file state, including index flags, symlinks and initialized
submodules; ignored files and Git configuration are excluded.

## ORIENT

1. Identify the current authorized task, preserving newer user direction. Read
   its linked goals/milestone, board and note; reconcile the plan and next action.
   Follow further decisions and evidence when they govern that action.
2. Compare the fingerprint before artifact-producing checks. Investigate
   differences and preserve user changes. A match establishes file state within
   the helper's scope, not correctness of recorded claims.
3. Run relevant authorized checks, distinguishing their outputs from arrival
   changes. Continue while the next action's authority, assumptions and priority
   hold. Return material scope, evidence or priority changes to the user/lead;
   unattended work follows its parking policy.
4. Refresh the note in WRITE mode when handover state materially changes.
