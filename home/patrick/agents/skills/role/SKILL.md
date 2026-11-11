---
name: role
description: >-
  Enter a workflow role: lead, agent, solo or autopilot.
argument-hint: "[role] [pulls] [workers]"
disable-model-invocation: true
---

# Role — session entry

## Roles

A session registers a role (`lead`, `agent`, `solo`, `autopilot`) and pulls.
The **decide set** (questions, ratification, acceptance with the user,
milestones) comes with `lead` and `solo`; pulls come with the role's preset
(agent has none) or `--pulls`. A session executes only what its role and pulls
include.

| Role | Pulls | Protocols |
|---|---|---|
| lead | The decide set: decides with the user, releases rulings, writes rule owners, accepts change requests (CRs) and user-judged outcomes with the user. May add pulls; several leads may run, the user coordinates them. | decide |
| agent | Any of plan, design, implement and review, as chosen. | per claimed CR or item (below) |
| solo | Decide plus plan, implement and review: decides with the user and plans; workers design and implement each CR, and a different worker reviews it. | decide, plan |
| autopilot | Solo while the user is away, with unattended authority. | decide, plan, unattended |

A **deciding session** is one registered as `lead`, `solo` or `autopilot`;
`unattended.md` limits autopilot's authority.

Protocol files:

- decide: `$HOME/.agents/skills/role/protocols/decide.md`
- plan: `$HOME/.agents/skills/role/protocols/plan.md`
- work: `$HOME/.agents/skills/role/protocols/work.md`
- review: `$HOME/.agents/skills/role/protocols/review.md`
- unattended: `$HOME/.agents/skills/role/protocols/unattended.md`

Pulls: **plan**, **design**, **implement**, **review**; `board claim` takes
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

## Entry

The user invokes `/role`, optionally naming a role, pulls and a worker count; or a session-recovery message asks to reload this skill.

## Steps

Give each step's output as one line.

1. **Known role.** When this conversation already registered a role, or a
   session-recovery message names one, and the invocation names no other
   role or worker count, keep it and go to step 4.
   Output: `role: <role> (known)`.
2. **Ask.** Ask for what neither the argument nor step 1 gives, under
   [Question format](../shared/question-format.md)
   (`$HOME/.agents/skills/shared/question-format.md`): the role among the four; for agent,
   the pulls as a multiple choice; for lead, whether to add pulls.
   Output: the question.
3. **Register.**

   ```sh
   bash $HOME/.agents/bin/session-lead-mode activate <role> [--pulls <pull>,<pull>] [--workers <n>]
   ```

   Pass `--pulls` for agent and for any pulls added to lead, and `--workers`
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
5. **Holds.** Where the repository has `.beads/`, run `board mine`.
   Output: held ids, or `none held`.
6. **Continue** under the loaded protocols within the current task. With
   pulls beyond the decide set, loop: dispatch ready CRs of your pulls, in
   `board claim` order, to workers in parallel under the plan protocol's
   [Dispatch](protocols/plan.md#dispatch), each running
   its protocol from the table above through its Exit, and refill as it says.
   Without workers in the runtime, `board claim` one CR, run its protocol through its Exit,
   skipping its Claim step, and claim again. When nothing is claimable and no
   worker runs, report the session's results and stop.
   Output per CR or item: `<id> → <protocol>: <exit result>`.

## Stop

- Registration fails: report the error and stop.

## Exit

The role is registered, its protocols are loaded and the session's holds are
listed.
