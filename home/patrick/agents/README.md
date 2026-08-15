# Shared agent definitions

`definitions/` is the source of truth for custom agent roles. Its Markdown
files use Claude Code-compatible agent frontmatter as a practical superset;
the prompt body and canonical lowercase role name are shared by both tools.

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

To validate every shared skill, both generated formats, aliases, sandboxes, and
multiline fields:

```sh
python3 home/patrick/agents/bin/test-agent-configs.py \
  home/patrick/agents
```

The generator translates portable fields to both formats. Each definition
declares its Codex model and sandbox; Claude-specific models, tools, and hooks
remain optional adapter fields. New roles therefore cannot accidentally
inherit write access or an unintended Codex model.

Codex model tiers follow the installed catalog: Sol for judgment-heavy roles,
Terra for general exploration and implementation, and Luna for narrow or
mechanical work.

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.
