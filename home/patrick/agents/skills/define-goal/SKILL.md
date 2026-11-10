---
name: define-goal
description: >-
  Pin down what success means before building: establish, advance or repair
  the goal contract (outcome, milestone, value path). Use when starting a
  project or phase, defining the next milestone, or when the goal or value
  path is unclear, architecture and reviews disagree about success, scope
  grows without progress, or a valid plan may bypass why the work exists;
  not for architecture or implementation plans.
---

# Define Goal

The goal belongs to the user. Align it before architecture and planning:
explicit, testable, sized for the next coherent milestone. A goal authorizes no
execution.

## 1. Mode

- **Establish:** a new project or substantial arc.
- **Advance:** the next milestone or wave from a ratified direction.
- **Refocus:** recover from drift by implementation, reviews or accumulated
  scope.

Output: the mode.

## 2. Build the contract

- Orient from the user's framing and current owners. Read
  `$HOME/.agents/skills/shared/project-memory.md`; follow its
  [Durable owners](../shared/project-memory.md#durable-owners) for contract
  ownership and [Arc state](../shared/project-memory.md#arc-state) for
  checkpoints and board. Refine the owning contract without duplicating its
  parent.
- Fields:
  - intended user and defining outcome;
  - problem or burden reduced;
  - value path and load-bearing hypotheses;
  - next observable milestone and why it matters; for a release checkpoint,
    the criterion its work meets;
  - smallest coherent walking skeleton proving it;
  - non-goals and safe deferrals;
  - constraints and quality criterion;
  - acceptance evidence;
  - unresolved empirical assumptions with the cheapest useful test.
- For a narrow path-validation checkpoint, state what it delivers or teaches,
  which capabilities wait and when the user assesses expansion.
- Interview in rounds: user and outcome first, then value path, milestone,
  walking skeleton, non-goals and acceptance. Keep the contract open while a
  field is unresolved. Ratify the complete contract before architecture.

Output: the contract fields, unresolved ones marked open.

## 3. Challenge acceptance

- Check what success delivers or teaches about why the work exists.
- Count a safe fallback, no-op, placeholder or universally fail-closed path
  that bypasses the value path as infrastructure evidence; keep product
  acceptance open and name the missing contract, input, capability or
  validation. Change success criteria only through the user.
- When structure or process grows without executable value, Refocus: derive a
  smaller coherent milestone and revise the contract.

Output: acceptance findings; a Refocus where structure outgrew value.

## 4. Ratify and record

- Reuse a ratified contract while premise and scope hold; present new or
  materially changed commitments for user ratification.
- Record ratified commitments in their durable owner before dependent planning
  or dispatch. Boards link goal owners under
  `$HOME/.agents/skills/shared/board-core.md`. A deciding session releases a contract
  revision like any ruling, under Release in
  `$HOME/.agents/skills/role/protocols/decide.md`.
- In a proposal-only or read-only task, return the contract and proposed owner
  instead of writing files.

Output: the ratified contract and its owner path, or the proposed contract and owner.
