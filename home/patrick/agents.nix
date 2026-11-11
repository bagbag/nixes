{
  config,
  lib,
  pkgs,
  ...
}:
let
  # bin/, hooks, the console mod, AGENTS.md and the skills link from the store-built artifacts, so they go
  # live together in one tested generation (nh darwin switch), Codex's hooks.json with them. settings.json
  # and the statusline script stay out of store.
  flakeRoot = if pkgs.stdenv.hostPlatform.isDarwin then "/etc/nix-darwin" else "/etc/nixos";
  claudeSrc = "${flakeRoot}/home/patrick/claude";
  agentPackage = pkgs.callPackage ./agents-package.nix { };
  agentArtifacts = agentPackage.artifacts;

  # One store link per file named in the package, from the artifacts subfolder `from`.
  storeLinks =
    target: from: names:
    lib.listToAttrs (
      map (name: lib.nameValuePair "${target}/${name}" { source = "${agentArtifacts}/${from}/${name}"; }) names
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
        storeLinks ".claude/hooks" "hooks/claude" (agentPackage.claudeHooks ++ agentPackage.claudeOwnHooks)
        // storeLinks ".codex/hooks" "hooks/codex" agentPackage.codexHooks
        // storeLinks ".agents/bin" "bin" agentPackage.tools;
    }
  ];

  # The same python3 with pyyaml the build runs the suite on, so `python3 bin/test-...` works in any session.
  home.packages = [ (lib.hiPrio agentPackage.python) ];

  home.file.".claude/CLAUDE.md".source = "${agentArtifacts}/AGENTS.md";

  # Codex and Claude Code deliberately use different filenames for their
  # global guidance. Both links point at the shared AGENTS.md.
  home.file.".codex/AGENTS.md".source = "${agentArtifacts}/AGENTS.md";
  # Hook wiring ships with the hook scripts it calls, so both change in the same switch.
  home.file.".codex/hooks.json".source = "${agentArtifacts}/codex-hooks.json";
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

  # Console mod, loaded through CLAUDE_CODE_PLUGIN_DIRS. The store folder is read-only (probed: a session
  # loads it fine); develop it with `claude --plugin-dir` on the repo folder.
  home.file.".claude/mods/console".source = "${agentArtifacts}/mods/console";

  # Skills are rendered from the shared source tree so included instructions
  # remain single-sourced while each deployed SKILL.md is self-contained.
  home.file.".claude/skills".source = "${agentArtifacts}/skills";

  # Codex discovers personal skills in ~/.agents/skills (not ~/.codex/skills).
  # Both tools use the same rendered SKILL.md files.
  home.file.".agents/skills".source = "${agentArtifacts}/skills";

  home.file.".claude/agents".source = "${agentArtifacts}/claude";
}
