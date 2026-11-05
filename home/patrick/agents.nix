{
  config,
  lib,
  pkgs,
  ...
}:
let
  # Out-of-store symlinks point at the live working tree, so edits (by hand,
  # /remember, or skill-creator) apply immediately without a rebuild.
  flakeRoot = if pkgs.stdenv.hostPlatform.isDarwin then "/etc/nix-darwin" else "/etc/nixos";
  claudeSrc = "${flakeRoot}/home/patrick/claude";
  codexSrc = "${flakeRoot}/home/patrick/codex";
  agentsSrc = "${flakeRoot}/home/patrick/agents";
  agentPackage = pkgs.callPackage ./agents-package.nix { };
  agentArtifacts = agentPackage.artifacts;

  # Out-of-store links for files named in the package, which the bundle ships too.
  outOfStoreLinks =
    target: source: names:
    lib.listToAttrs (
      map (
        name:
        lib.nameValuePair "${target}/${name}" {
          source = config.lib.file.mkOutOfStoreSymlink "${source}/${name}";
        }
      ) names
    );
in
{
  imports = [
    {
      # Individual links, not the directories: ~/.claude/hooks/ also holds files
      # from other plugins like context-mode plugin that home-manager must not clobber.
      # ~/.agents/bin holds the stable, tool-neutral session role registry shared by
      # Codex and Claude Code, and the protocol engine the console mod and Codex
      # compact-reorient call.
      home.file =
        outOfStoreLinks ".claude/hooks" "${claudeSrc}/hooks" agentPackage.claudeOwnHooks
        // outOfStoreLinks ".claude/hooks" "${agentsSrc}/hooks" agentPackage.claudeHooks
        // outOfStoreLinks ".codex/hooks" "${agentsSrc}/hooks" agentPackage.codexHooks
        // outOfStoreLinks ".agents/bin" "${agentsSrc}/bin" agentPackage.tools;
    }
  ];

  home.file.".claude/CLAUDE.md".source = config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/AGENTS.md";

  # Codex and Claude Code deliberately use different filenames for their
  # global guidance. Both links point at the shared AGENTS.md source.
  home.file.".codex/AGENTS.md".source = config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/AGENTS.md";
  home.file.".codex/hooks.json".source = config.lib.file.mkOutOfStoreSymlink "${codexSrc}/hooks.json";
  home.file.".codex/agents".source = "${agentArtifacts}/codex";

  # settings.json is written by Claude Code itself (atomic write: temp file
  # + rename, one readlink deep). home.file's mkOutOfStoreSymlink goes
  # through home-manager's per-generation store symlink farm, so the
  # resolved path is a multi-hop chain whose first hop still lands in the
  # (read-only) Nix store -> EROFS. Link directly, single-hop, instead.
  #
  # The declared setting owns a symlink at this path. A regular file remains
  # user-owned and is never overwritten.
  home.activation.linkClaudeSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    target="$HOME/.claude/settings.json"
    wanted=${lib.escapeShellArg "${claudeSrc}/settings.json"}
    if [ -L "$target" ]; then
      ln -sfn "$wanted" "$target"
    elif [ -e "$target" ]; then
      echo "agents.nix: $target exists and is not the expected symlink -> $wanted; leaving it untouched" >&2
    else
      ln -s "$wanted" "$target"
    fi
  '';

  home.file.".claude/statusline-command.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${claudeSrc}/statusline-command.sh";

  # Console mod, loaded through CLAUDE_CODE_PLUGIN_DIRS; out of store so edits hot-reload and Claude can lay its
  # API types into .claude-plugin/types/ (Git-ignored).
  home.file.".claude/mods/console".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/claude/mods/console";

  # Skills are rendered from the shared source tree so included instructions
  # remain single-sourced while each deployed SKILL.md is self-contained.
  home.file.".claude/skills".source = "${agentArtifacts}/skills";

  # Codex discovers personal skills in ~/.agents/skills (not ~/.codex/skills).
  # Both tools use the same rendered SKILL.md files.
  home.file.".agents/skills".source = "${agentArtifacts}/skills";

  home.file.".claude/agents".source = "${agentArtifacts}/claude";

  home.file.".claude/commands".source = config.lib.file.mkOutOfStoreSymlink "${claudeSrc}/commands";
}
