# Claude Code + Codex agent setup

Shared skills, agent roles, hooks and global instructions for Claude Code and Codex, plus the
Claude Code console mod (round and board pane) and the `board` / `protocol` command-line tools.
`VERSION` names this bundle.

## Install or upgrade

    tar -xzf claude-codex-setup-<version>.tar.gz
    cd claude-codex-setup-<version>
    ./install.py --dry-run     # shows what would change
    ./install.py               # add --no-mod to skip the console mod

Requires `python3` 3.11 or newer and `bd` (beads, tested with 1.3.1). Under an older `python3`
(macOS ships 3.9) the installer continues with the newest `python3.N` on `PATH` that starts, else stops. It stops
before changing anything when `bd` is missing, when a target is a symlink, or when a settings file
isn't valid JSON or `config.toml` isn't valid TOML. Then restart Claude Code and Codex. Codex asks you to trust the changed hooks.

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
7. Pins the Python tools in `~/.agents/bin` (`board`, `protocol`, `scratch`, ...) to the `python3` on
   `PATH` that runs the installer (an unversioned `python3` is preferred to a `python3.N`, which gets a
   note), so a session started with a different `PATH` (Dock, IDE) does not pick macOS's 3.9. Rerun
   the installer after switching or removing that Python; it prints the pinned path.
8. Grants the agents their write folders outside repositories (`agents/scratch` under
   `$XDG_STATE_HOME` or `~/.local/state`, `agents/decisions` under `$XDG_DATA_HOME` or
   `~/.local/share`): an `Edit(<folder>/**)` rule each in Claude's `permissions.allow`, and a marked
   `[sandbox_workspace_write]` block in `~/.codex/config.toml`. If that file already has the table, or is a symlink, the installer
   prints the folders to add to `writable_roots` and leaves it alone. A rule you had before the
   first install stays yours on upgrade and uninstall.
9. At a terminal, asks for your name for shared boards when `git config --global agents.person`
   is unset. Leave it blank to skip; set it per repository with `git config agents.person <name>`.

Nothing else in `settings.json` or `config.toml` is touched. Models, plugins, your other
permissions and `env` stay yours. The `settings/` folder holds the unmerged hook templates for reference.

## Boards

Inside a project repository, with your go:

    ~/.agents/bin/board setup                # creates the board, or updates an existing one's settings
    ~/.agents/bin/board setup --server       # converts an existing embedded board to server mode

A new board runs in server mode, so several sessions can write at once; `--embedded` makes a
single-writer board instead. Pause the sessions writing to a board before converting it. Safe to
rerun: it never re-creates a board, prints every setting it changes with its old and new
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

    ./install.py --uninstall

Removes everything the install recorded, its hook registrations, the permission rules it added and
its `config.toml` block (a block you edited, or in a symlinked file, is left with a note; a `config.toml` the
installer created is deleted when nothing else is in it). Your earlier instructions stay
in the backup folder; restore them by hand.

## Console mod

`~/.claude/mods/console` is a Claude Code mod. It registers the `protocol` tool, the Console pane
(`/console`) and the dialog gate for decision rounds. It needs a Claude Code build with mod support.
If yours has none, use `--no-mod`. Claude Code lays the mod's API types into
`.claude-plugin/types/` on first load. The Claude flows for decision rounds expect the mod; Codex
works without it.
