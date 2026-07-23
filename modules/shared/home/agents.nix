{
  config,
  lib,
  pkgs,
  ...
}:
let
  # Out-of-store symlinks point at the live working tree, so edits (by hand,
  # /remember, or skill-creator) apply immediately without a rebuild.
  flakeRoot = if pkgs.stdenv.isDarwin then "/etc/nix-darwin" else "/etc/nixos";
  claudeSrc = "${flakeRoot}/modules/shared/home/claude";
  codexSrc = "${flakeRoot}/modules/shared/home/codex";
  agentsSrc = "${flakeRoot}/modules/shared/home/agents";
  agentsStoreSrc = ./agents;
  agentConfigs =
    pkgs.runCommand "custom-agent-configs"
      {
        nativeBuildInputs = [
          pkgs.jq
          pkgs.python3
        ];
      }
      ''
        python3 ${agentsStoreSrc}/bin/test-agent-configs.py ${agentsStoreSrc}
        mkdir -p "$out/claude" "$out/codex"
        python3 ${agentsStoreSrc}/bin/generate-agent-configs.py \
          --source ${agentsStoreSrc}/definitions \
          --target claude \
          --output "$out/claude"
        python3 ${agentsStoreSrc}/bin/generate-agent-configs.py \
          --source ${agentsStoreSrc}/definitions \
          --target codex \
          --output "$out/codex"
      '';
in
{
  home.file.".claude/CLAUDE.md".source = config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/AGENTS.md";

  # Codex and Claude Code deliberately use different filenames for their
  # global guidance. Both links point at the shared AGENTS.md source.
  home.file.".codex/AGENTS.md".source = config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/AGENTS.md";
  home.file.".codex/hooks.json".source = config.lib.file.mkOutOfStoreSymlink "${codexSrc}/hooks.json";
  home.file.".codex/agents".source = "${agentConfigs}/codex";

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
    wanted=${lib.escapeShellArg "${claudeSrc}/settings.json"}
    if [ -e "$target" ] || [ -L "$target" ]; then
      current=$(readlink "$target" 2>/dev/null || true)
      if [ "$current" != "$wanted" ]; then
        echo "agents.nix: $target exists and is not the expected symlink -> $wanted; leaving it untouched" >&2
      fi
    else
      ln -s "$wanted" "$target"
    fi
  '';

  home.file.".claude/statusline-command.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${claudeSrc}/statusline-command.sh";

  # Individual links, not the directory: ~/.claude/hooks/ also holds files
  # from other plugins like context-mode plugin that home-manager must not clobber.
  home.file.".claude/hooks/context-watch.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${claudeSrc}/hooks/context-watch.sh";

  home.file.".claude/hooks/fable-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${claudeSrc}/hooks/fable-guard.sh";

  home.file.".claude/hooks/compact-reorient.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/hooks/compact-reorient.sh";

  home.file.".claude/hooks/readonly-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/hooks/readonly-guard.sh";

  home.file.".claude/hooks/git-stash-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/hooks/git-stash-guard.sh";

  home.file.".codex/hooks/compact-reorient.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/hooks/compact-reorient.sh";

  home.file.".codex/hooks/git-stash-guard.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/hooks/git-stash-guard.sh";

  # Stable, tool-neutral path used by shared skills. It currently activates
  # Claude Code's context watcher and safely no-ops under other tools.
  home.file.".agents/bin/set-context-watch-mode".source =
    config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/bin/set-context-watch-mode.sh";

  # Whole directories: new entries dropped in land in the repo automatically.
  home.file.".claude/skills".source = config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/skills";

  # Codex discovers personal skills in ~/.agents/skills (not ~/.codex/skills).
  # It follows this symlink, so both tools use the same SKILL.md files.
  home.file.".agents/skills".source = config.lib.file.mkOutOfStoreSymlink "${agentsSrc}/skills";

  home.file.".claude/agents".source = "${agentConfigs}/claude";

  home.file.".claude/commands".source = config.lib.file.mkOutOfStoreSymlink "${claudeSrc}/commands";
}
