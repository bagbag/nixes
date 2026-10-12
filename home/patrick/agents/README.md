# Shared agent definitions

`definitions/` is the source of truth for custom agent roles. Its Markdown
files use Claude Code-compatible agent frontmatter as a practical superset;
the prompt body and canonical lowercase role name are shared by both tools.
Keep prompt wording provider-neutral; tool-specific settings belong in
frontmatter adapter fields.

`skills/` is the source and template tree for shared skills. Markdown files may
include another skills-root-relative Markdown file with a marker on its own
line:

```md
<!-- @include shared/decision-protocol.md -->
```

The build expands includes recursively into complete standalone skill files.
Missing targets, escaping paths, cycles, frontmatter markers, and malformed or
unresolved markers fail validation.

Keep role and authority limits before each skill's workflow; place whole-file
shared references after it and link them from the relevant phases. Includes
retain their heading levels; use one H1 and flat reference sections.

Load shared content per reader; every file in `skills/shared/` stays readable
on its own:

- Include content a skill acts on in every run; the rendered skill carries it,
  so reloading the skill after compaction restores it.
- Reference `$HOME/.agents/skills/shared/<file>` by path for readers without
  includes (agent definitions, `AGENTS.md`) and for conditional or
  single-section needs.
- Links only navigate loaded content: in-file anchors for included files,
  `../shared/` links for files the skill reads by path. Validation rejects
  other links and unresolved anchors.

Nix generates the Claude Code and Codex representations into the store, and
Home Manager links them at activation. It also renders the shared skill tree
into the store; generated files do not live in Git. Skill changes therefore
require `darwin-rebuild switch` before they become active.

To inspect generated output manually:

```sh
output_dir=$(mktemp -d)
python3 home/patrick/agents/bin/generate-agent-configs.py \
  --target codex \
  --output "$output_dir"

python3 home/patrick/agents/bin/expand-skills.py \
  --source home/patrick/agents/skills \
  --output "$output_dir/skills"
```

To validate skills, generated formats, policies and hooks, use Python with
PyYAML (the Nix build provides it):

```sh
python3 home/patrick/agents/bin/test-agent-configs.py \
  home/patrick/agents
```

The generator translates portable fields to both formats. Each definition
declares its Codex model and sandbox; Claude-specific models, tools, and hooks
remain optional adapter fields. New roles therefore cannot accidentally
inherit write access or an unintended Codex model.

`effort` is the shared reasoning level; optional `claude-effort` and
`codex-effort` override it for one tool. The resolved value is validated per
tool, since only Codex accepts `ultra`.

Validation covers source instruction/description preservation, per-tool effort
resolution, generated permissions, and local hooks. Live runtime enforcement requires separate checks.

Each role's `codex-model` field owns its model selection; validation requires
an explicit, nonempty model without pinning a particular selection.

Scout and explore return discovery results in their responses. Other specialists
can write assigned artifacts directly. Native configurations provide file-write
tools and workspace access; role instructions confine edits to assigned
artifacts and temporary probes. Implementation changes belong to implementation
roles, except reported fixes an assessor is certain are the only realistic,
clean option. Claude's investigation shell guard is a deny-list; Codex uses its
native sandbox setting. Role instructions define assigned write zones.

Workflow owners:

- [Worker arcs](skills/shared/worker-arcs.md): invariant traceability and evidence.
- [Retro](skills/retro/SKILL.md): rule proposals and regression cases.
- [Goal lead](skills/goal-lead/SKILL.md) and [goal agent](skills/goal-agent/SKILL.md): a decision lead and an implementation coordinator joined by the [goal relay](skills/shared/goal-relay.md).
- [Work tracking](skills/shared/work-tracking.md): beads conventions for all lead modes; [beads-migrate](skills/beads-migrate/SKILL.md) moves a Markdown-tracked arc onto them.

Work tracking owns ruling destinations and the ruling-record format. The goal
relay owns the cross-role landing contract; goal-agent owns its execution steps.

The `explore-options` skill coordinates `option-explorer` to develop a broad
solution space into realistic alternatives. It progressively screens and deepens
approaches, reports material exclusions, and leaves decisions to the invoker.
Worker arcs name when leads use it; the skill owns how its result is reused.

The `architect` skill coordinates the architecture specialist without requiring
supervisor. The agent owns design and review; `second-opinion` independently
challenges decisions. The lead selects each for a concrete question. `plan`
decomposes an agreed design into implementation work when decomposition or
integration needs specialist judgment; leads can write pattern-determined plans
and continuation deltas directly.

The [worker-arc contract](skills/shared/worker-arcs.md) owns review gates and
acceptance evidence. The [decision protocol](skills/shared/decision-protocol.md)
owns default decision authority, end-state criteria and concern classes; agent
definitions read it at runtime. Lead-only shared files:
[reviewers](skills/shared/reviewers.md) (selection, briefing, independence,
disagreement) and [asking](skills/shared/asking.md) (how leads question the
user).

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.
