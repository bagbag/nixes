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

7. At a terminal, asks for your name for shared boards when `git config --global agents.person`
   is unset. Leave it blank to skip; set it per repository with `git config agents.person <name>`.

Nothing else in `settings.json` or `config.toml` is touched. Models, plugins, permissions and
`env` stay yours. The `settings/` folder holds the unmerged hook templates for reference.

## Boards

Inside a project repository, with your go:

    ~/.agents/bin/board setup                # creates the board, or updates an existing one's settings
    ~/.agents/bin/board setup --server       # a new board you mean to share later

Safe to rerun: it never re-creates a board, prints every setting it changes with its old and new
value, and names `.git/info/exclude` lines that match tracked project files. Rerun it after an
upgrade to bring existing boards to the current settings; on a shared board each person reruns it
for the settings that stay on their machine.

## Shared boards

To share a beads board between people, inside the project repository:

    ~/.agents/bin/board share [url]          # first person: says what goes out, changes nothing
    ~/.agents/bin/board share [url] --yes    # then shares, on an existing server-mode board
    ~/.agents/bin/board join [url]           # everyone else

The url defaults to the project's own repository, which needs at least one commit. `share` without
`--yes` says what goes out (the whole board, git emails included) and stops. Both are safe to
repeat; a failed join cleans up after itself. Afterwards `board` syncs by itself and each person's
sessions work their own queue. A Dolt remote added by hand shares nothing. Upgrade bd and Dolt
together: one person migrates and pushes. When the board grows large, `board move <url>` moves it to
a fresh repository and the others rejoin with `board join <url>`.

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
