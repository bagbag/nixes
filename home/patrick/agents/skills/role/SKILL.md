---
name: role
description: >-
  Enter a workflow role: lead, agent, solo or autopilot.
argument-hint: "[role] [pulls]"
disable-model-invocation: true
---

# Role — session entry

## Roles

| Role | Work | Protocols |
|---|---|---|
| lead | Decides with the user, releases rulings, writes rule owners, accepts designs and user-judged outcomes with the user. Never combined with pulls; several leads may run; the user coordinates them. | decide |
| agent | Pulls any of plan, design, implement and review. | per claimed item (below) |
| solo | Decides with the user and plans; one worker per item does design, implementation and review. | decide, plan |
| autopilot | Solo while the user is away, with unattended authority. | decide, plan, unattended |

A **deciding session** is one registered as `lead` or `solo`.

Protocol files:

- decide: `$HOME/.agents/skills/role/protocols/decide.md`
- plan: `$HOME/.agents/skills/role/protocols/plan.md`
- work: `$HOME/.agents/skills/role/protocols/work.md`
- review: `$HOME/.agents/skills/role/protocols/review.md`
- unattended: `$HOME/.agents/skills/role/protocols/unattended.md`

Pulls: **plan**, **design**, **implement**, **review**; each claims the kinds
in work-tracking [Routing](../shared/work-tracking.md#routing)
(`$HOME/.agents/skills/shared/work-tracking.md`).

An agent session runs each claimed item under the protocol for its kind:

| Claimed item | Protocol |
|---|---|
| `released` decision | plan, its Released rulings section |
| `design`, `task`, `bug`, `spike` (open) | work |
| `in_review` task, bug, spike | review |

## Entry

The user invokes `/role`, optionally naming a role and, for agent, its pulls;
or a session-recovery message asks to reload this skill.

## Steps

Give each step's output as one line.

1. **Known role.** When this conversation already registered a role, or a
   session-recovery message names one, and the invocation names no other
   role, keep it and go to step 4.
   Output: `role: <role> (known)`.
2. **Ask.** Ask for what neither the argument nor step 1 gives, under
   [Question format](#question-format): the role among the four; for agent,
   the pulls as a multiple choice.
   Output: the question.
3. **Register.**

   ```sh
   bash $HOME/.agents/bin/session-lead-mode activate <role> [--pulls <pull>,<pull>]
   ```

   Pass `--pulls` only for agent.
   Output: `registered <role> [pulls]`.
4. **Load.** Read the role's protocol files fully, and the shared files each
   one names. An agent reads those of its pulls: plan → plan, design and
   implement → work, review → review.
   Output: `loaded <protocols>`.
5. **Holds.** Where the repository has `.beads/`, run `board mine`.
   Output: held ids, or `none held`.
6. **Continue** under the loaded protocols within the current task. As an
   agent, loop: with the `plan` pull, run the plan protocol through its
   Exit; then `board claim`, run the claimed item's
   protocol from the table above through its Exit, skipping its Claim step,
   and claim again. When the claim returns no item, report the session's
   results and stop.
   Output per item: `<id> → <protocol>: <exit result>`.

## Stop

- Lead requested together with pulls: lead stands alone; ask again.
- Registration fails: report the error and stop.

## Exit

The role is registered, its protocols are loaded and the session's holds are
listed.

<!-- @include shared/question-format.md -->
