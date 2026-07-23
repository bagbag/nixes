# Shared agent definitions

`definitions/` is the source of truth for custom agent roles. Its Markdown
files use Claude Code-compatible agent frontmatter as a practical superset;
the prompt body and canonical lowercase role name are shared by both tools.

Nix generates the Claude Code and Codex representations into the store, and
Home Manager links them at activation; generated files do not live in Git.

To inspect generated output manually:

```sh
output_dir=$(mktemp -d)
python3 modules/shared/home/agents/bin/generate-agent-configs.py \
  --target codex \
  --output "$output_dir"
```

To validate every shared skill, both generated formats, aliases, sandboxes, and
multiline fields:

```sh
python3 modules/shared/home/agents/bin/test-agent-configs.py \
  modules/shared/home/agents
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
