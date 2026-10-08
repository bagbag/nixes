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
<!-- @include shared/decision-discipline.md -->
```

The build expands includes recursively into complete standalone skill files.
Missing targets, escaping paths, cycles, frontmatter markers, and malformed or
unresolved markers fail validation.

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

The `explore-options` skill coordinates `option-explorer` to develop a broad
solution space into realistic alternatives. It progressively screens and deepens
approaches, reports material exclusions, and leaves decisions to the invoker.
Supervisor and autopilot use it when broader exploration is needed, within their
existing authority and budgets. Its result feeds the next needed task without
adding an automatic architecture or review round.

The `architect` skill coordinates the architecture specialist without requiring
supervisor. The agent owns design and review; `second-opinion` independently
challenges decisions. The lead selects each for a concrete question. `plan`
decomposes an agreed design into implementation work when decomposition or
integration needs specialist judgment; leads can write pattern-determined plans
and continuation deltas directly.

The shared worker-arc contract owns review and acceptance: substantive
implementation is reviewed by someone who did not author it, with focused
repair checks and lead integration verification. Load-bearing runtime claims
require independent reproduction of decisive checks, or suitable independent
evidence for the same relevant code and environment; author logs alone are
insufficient. One qualifying assessment or execution can satisfy overlapping
gates. Reuse it while applicable, and rerun when changes or failures invalidate
it. Explicit requests for a fresh opinion still receive a new reviewer.

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.
