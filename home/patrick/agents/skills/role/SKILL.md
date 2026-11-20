---
name: role
description: >-
  Enter a workflow role: lead, agent, solo or autopilot.
argument-hint: "[role] [pulls] [workers]"
disable-model-invocation: true
---

# Role — session entry

## Roles

A session registers a role, which sets its authority (the **decide set**:
questions, ratification, acceptance with the user, milestones), and its pulls,
which set its work, preset by the role. A session executes only what its role
and pulls include.

| Role | Authority | Preset pulls | Protocols |
|---|---|---|---|
| lead | The decide set: decides with the user, releases rulings, writes rule owners, accepts change requests (CRs) and user-judged outcomes with the user. Several leads may run; the user coordinates them. | plan | decide |
| solo | As lead. | all four | decide |
| autopilot | Solo while the user is away, with unattended authority. | all four | decide, unattended |
| agent | None. | none: any of the four, as chosen | per claimed CR or item (below) |

A **deciding session** is one registered as `lead`, `solo` or `autopilot`;
`unattended.md` limits autopilot's authority.

Protocol files:

- decide: `$HOME/.agents/skills/role/protocols/decide.md`
- plan: `$HOME/.agents/skills/role/protocols/plan.md`
- work: `$HOME/.agents/skills/role/protocols/work.md`
- review: `$HOME/.agents/skills/role/protocols/review.md`
- unattended: `$HOME/.agents/skills/role/protocols/unattended.md`

Pulls: **plan**, **design**, **implement**, **review**; `agents board claim` takes
each pull's item kinds, and board-core [Routing](../shared/board-core.md#routing)
(`$HOME/.agents/skills/shared/board-core.md`) keeps the rules a claim does not
enforce.

An agent session runs each claimed CR or item under the protocol for its kind:

| Claimed | Protocol |
|---|---|
| `released` decision | plan, its Released rulings section |
| `open` CR | work (design or implement pull) |
| `in_review` CR (agent review or agent checkpoint); refresh work | review |
| standalone `in_review` task, bug, spike | review |
| `open` no-commit task | plan, its Dispatch |

## Entry

The user invokes `/role`, optionally naming a role, pulls and a worker count; or a session-recovery message asks to reload this skill.

## Steps

Give each step's output as one line.

1. **Known role.** When this conversation already registered a role, or a
   session-recovery message names one, and the invocation names no role,
   pulls or worker count, keep it and go to step 4.
   Output: `role: <role> (known)`.
2. **Ask.** Ask for what neither the argument nor step 1 gives (pulls
   named without a role give no role), under
   [Question format](../shared/question-format.md)
   (`$HOME/.agents/skills/shared/question-format.md`): the role among the four, then
   its pulls as one multiple choice with the role's preset ticked.
   Output: the question.
3. **Register.**

   ```sh
   agents session activate <role> --pulls <pull>,<pull> [--workers <n>]
   ```

   Pass the chosen pulls, and `--workers`
   only when the invocation names a worker count (`/role solo 5`). For autopilot register `solo`: the
   setup registers autopilot on the user's go. Leaving autopilot, give the
   unattended protocol's Return report first.
   Output: `registered <role> [pulls] [workers]`.
4. **Load.** Read the role's protocol files fully (autopilot's included, though
   registered solo), and the shared files each one's opening read list names
   (the others load where a step names them).
   Also read those of the session's pulls: plan → plan, design and implement →
   work, review → review.
   Output: `loaded <protocols>`.
5. **Holds.** Where the repository has `.beads/`, run `agents board mine`.
   Output: held ids, or `none held`.
6. **Continue** the current task under the loaded protocols; with none,
   report and wait. Run the claim loop only when the user asks for it (in
   words, or a loop command such as `/goal`). With
   pulls, loop: dispatch the CRs `agents board queue` lists for your
   pulls, in its order, to workers in parallel under the plan protocol's
   [Dispatch](protocols/plan.md#dispatch), each running
   its protocol from the table above through its Exit, and refill as it says.
   Without workers in the runtime, `agents board claim` one CR, run its protocol through its Exit,
   skipping its Claim step, and claim again. Take readiness from the queue:
   claim what it lists rather than judging it yourself. When `agents board claim` finds nothing and no
   worker runs, report the session's results and stop; when the user asked you to keep watching, run
   `agents board wait` in the background instead (exit 0 names a candidate: claim again; a claim that fails twice on the same
   id is a blocker to report, not to wait out).
   Output per CR or item: `<id> → <protocol>: <exit result>`.

## Stop

- Registration fails: report the error and stop.
- The user tells you to stop: scope the stop to the exact action, file,
  decision or effect it names and continue authorized work outside it; a stop
  on your work (wind down, pause, restart) binds only you: keep it in your
  checkpoint ([Arc state](../shared/project-memory.md#arc-state)). Record a
  stop on the board only when the user aims it at specific items or at every
  session ([Deferrals and environment facts](../shared/board-coordination.md#deferrals-and-environment-facts)).

## Exit

The role is registered, its protocols are loaded and the session's holds are
listed.
