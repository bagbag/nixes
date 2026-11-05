# Claude Code + Codex agent setup

Shared skills, agent roles, hooks and global instructions for Claude Code and Codex, plus the
Claude Code console mod (round and board pane) and the `board` / `protocol` command-line tools.
`VERSION` names this bundle.

## Install or upgrade

    tar -xzf claude-codex-setup-<version>.tar.gz
    cd claude-codex-setup-<version>
    ./install.sh --dry-run     # shows what would change
    ./install.sh               # add --no-mod to skip the console mod

Requires `bash`, `python3` 3.11 or newer, `jq` and `bd` (beads, tested with 1.3.1). The installer
stops before changing anything when one is missing, or when a target is a symlink or a settings
file isn't valid JSON. Then restart Claude Code and Codex. Codex asks you to trust the changed hooks.

The installer:
1. Backs up everything it replaces or removes to `~/.agent-config-backup/<timestamp>/`.
2. Copies the skills, agents, hooks, `~/.agents/bin/*` and the console mod. Your own files next to
   them stay untouched.
3. **Replaces your global instructions** (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`). Your old
   ones are in the backup; merge what you want to keep back by hand. An upgrade replaces them again.
4. Removes files the previous install shipped and this one doesn't, using
   `~/.agents/setup-state.json`.
5. Merges the hook registrations into `~/.claude/settings.json` and `~/.codex/hooks.json`, keeping
   your other hooks and settings. It creates either file when missing.
6. Sets `env.CLAUDE_CODE_PLUGIN_DIRS` to the console mod. If it already holds a value, the installer
   prints a note and you add the mod path yourself.

Nothing else in `settings.json` or `config.toml` is touched. Models, plugins, permissions and
`env` stay yours. The `settings/` folder holds the unmerged hook templates for reference.

## Uninstall

    ./install.sh --uninstall

Removes everything the install recorded and its hook registrations. Your earlier instructions stay
in the backup folder; restore them by hand.

## Console mod

`~/.claude/mods/console` is a Claude Code mod. It registers the `protocol` tool, the Console pane
(`/console`) and the dialog gate for decision rounds. It needs a Claude Code build with mod support.
If yours has none, use `--no-mod`. Claude Code lays the mod's API types into
`.claude-plugin/types/` on first load. The Claude flows for decision rounds expect the mod; Codex
works without it.
