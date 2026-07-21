{ config, lib, pkgs, ... }:
let
  # Out-of-store symlinks point at the live working tree, so edits (by hand,
  # /remember, or skill-creator) apply immediately without a rebuild.
  flakeRoot = if pkgs.stdenv.isDarwin then "/etc/nix-darwin" else "/etc/nixos";
  src = "${flakeRoot}/modules/shared/home/claude";
in
{
  home.file.".claude/CLAUDE.md".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/CLAUDE.md";

  # settings.json is written by Claude Code itself (atomic write: temp file
  # + rename, one readlink deep). home.file's mkOutOfStoreSymlink goes
  # through home-manager's per-generation store symlink farm, so the
  # resolved path is a multi-hop chain whose first hop still lands in the
  # (read-only) Nix store -> EROFS. Link directly, single-hop, instead.
  #
  # Guarded: only (re)link when the path is missing or already exactly this
  # symlink, so a stray regular file or unrelated symlink there is never
  # clobbered.
  home.activation.linkClaudeSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    target="$HOME/.claude/settings.json"
    wanted=${lib.escapeShellArg "${src}/settings.json"}
    if [ -e "$target" ] || [ -L "$target" ]; then
      current=$(readlink "$target" 2>/dev/null || true)
      if [ "$current" != "$wanted" ]; then
        echo "claude.nix: $target exists and is not the expected symlink -> $wanted; leaving it untouched" >&2
      fi
    else
      ln -s "$wanted" "$target"
    fi
  '';

  home.file.".claude/statusline-command.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/statusline-command.sh";

  # Individual links, not the directory: ~/.claude/hooks/ also holds files
  # from other plugins like context-mode plugin that home-manager must not clobber.
  home.file.".claude/hooks/context-watch.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/hooks/context-watch.sh";

  home.file.".claude/hooks/fable-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/hooks/fable-guard.sh";

  home.file.".claude/hooks/readonly-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/hooks/readonly-guard.sh";

  home.file.".claude/hooks/git-stash-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/hooks/git-stash-guard.sh";

  # Whole directories: new entries dropped in land in the repo automatically.
  home.file.".claude/skills".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/skills";

  home.file.".claude/agents".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/agents";

  home.file.".claude/commands".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/commands";
}
