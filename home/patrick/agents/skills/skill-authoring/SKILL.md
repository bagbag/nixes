---
name: skill-authoring
description: >-
  Use when creating, editing or reviewing a skill (SKILL.md), agent definition
  or agent instruction file (AGENTS.md, CLAUDE.md): invocation policy, trigger
  description, portable frontmatter, layout and style. User-invoked: review the
  text changed in this session.
---

# Skill authoring

On user mention, re-read this file and review the skill and instruction text
changed in this session, otherwise the focus the argument names; show the
changed lines; then carry out the argument's other instructions. Project rules
for skills (inventory, layout, validators) add to these.

## Invocation

- Decide auto-loaded or manual-only first.
- Manual-only: `disable-model-invocation: true` in the frontmatter (Claude)
  and `policy: allow_implicit_invocation: false` in `agents/openai.yaml`
  (Codex). Claude also hides the description from the model; Codex only stops
  implicit invocation.
- Claude runs one skill per message and passes the rest of the message as its
  argument; Codex loads every mentioned `$skill`.

## Description

- The routing model sees only `name` and `description`: lead with when to use,
  in the user's words (symbols, verbs, phrases); state the boundary to a close
  sibling and any skip condition. Maximum 1,024 characters (Agent Skills spec).
- Change a description only to fix a trigger miss, never in a style pass.
- Manual-only: write it as menu help.

## Frontmatter and layout

- Portable fields: `name`, `description`. Claude-only: `disable-model-invocation`,
  `user-invocable`, `context`, `agent`, `paths`, `argument-hint`, `$ARGUMENTS`
  substitution; `allowed-tools` grants Claude permissions and restricts
  nothing. Document the Codex behavior when using one.
- One `SKILL.md` per kebab-case folder named like the skill; supporting files
  inside it (`assets/`, `scripts/`, `references/`).

## Style

Guidelines; apply only where they don't weaken a rule:

- Address the acting model: imperative, present tense.
- Information dense: rules, lists and tables over prose; keep definitions of
  terms.
- Positive wording ("do X") where it says the same as the prohibition; keep
  prohibitions that guard a safety boundary (destructive, irreversible,
  outward-facing, permission).
- Omit reasoning and explanations of the obvious: a rule that needs its reason
  to be followed is unclear; sharpen it, or keep the reason as a short clause.
