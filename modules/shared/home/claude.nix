{ config, pkgs, ... }:
let
  # Out-of-store symlinks point at the live working tree, so edits (by hand,
  # /remember, or skill-creator) apply immediately without a rebuild.
  flakeRoot = if pkgs.stdenv.isDarwin then "/etc/nix-darwin" else "/etc/nixos";
  src = "${flakeRoot}/modules/shared/home/claude";
in
{
  home.file.".claude/CLAUDE.md".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/CLAUDE.md";

  home.file.".claude/settings.json".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/settings.json";

  home.file.".claude/statusline-command.sh".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/statusline-command.sh";

  # Whole directories: new entries dropped in land in the repo automatically.
  home.file.".claude/skills".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/skills";

  home.file.".claude/agents".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/agents";

  home.file.".claude/commands".source =
    config.lib.file.mkOutOfStoreSymlink "${src}/commands";
}
