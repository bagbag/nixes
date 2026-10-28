---
name: skill-authoring
description: >-
  Write and review skills, agent definitions and instruction files:
  invocation policy, trigger descriptions, frontmatter, layout and style. Use
  when creating, editing or reviewing a SKILL.md, agent definition, AGENTS.md
  or CLAUDE.md; invoked by the user, it reviews this session's changed text.
  Not for trigger evals (skill-creator).
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
- Claude passes the text after a skill's name as its argument: the terminal
  runs up to six skills stacked at the start of a message, each with the
  trailing text; the SDK and `claude -p` load only the first. Codex loads
  every mentioned `$skill`.

## Description

- The routing model sees only `name` and `description`. Model-invocable: one
  clause of purpose, then "Use when" with the moments and the user's words
  (symbols, verbs, phrases), then "not for" a close sibling or skip
  condition where one exists; the procedure stays in the body, since the
  description loads into every session.
- Manual-only: one sentence of menu help from the user's view; put argument
  hints in `argument-hint` (Claude; Codex ignores it).
- Reword a description only to sharpen its trigger or purpose without losing
  a trigger. Maximum 1,024 characters (Agent Skills spec).

## Frontmatter and layout

- Portable fields: `name`, `description`. Claude-only: `disable-model-invocation`,
  `user-invocable`, `context`, `agent`, `paths`, `argument-hint`, argument
  substitution (name the dollar-sign ARGUMENTS placeholder in words; Claude
  substitutes it anywhere); `allowed-tools` (a space- or
  comma-separated string or a YAML list) grants Claude permissions for the
  invoking turn and restricts nothing. Document the Codex behavior when using
  one.
- One `SKILL.md` per kebab-case folder named like the skill; supporting files
  inside it (`assets/`, `scripts/`, `references/`).

## Style

Guidelines; apply only where they don't weaken a rule:

- Address the acting model: imperative, present tense.
- Information dense: rules, lists and tables over prose; keep definitions of
  terms.
- Write an ordered process as numbered steps, each with its output; keep
  standing constraints as lists.
- Positive wording ("do X") where it says the same as the prohibition; keep
  prohibitions that guard a safety boundary (destructive, irreversible,
  outward-facing, permission).
- Omit reasoning and explanations of the obvious: a rule that needs its reason
  to be followed is unclear; sharpen it, or keep the reason as a short clause.
- Shorten for density, never for count: keep every rule, and before removing
  text name where each rule it carried lives.
