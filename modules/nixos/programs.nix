{ pkgs, ... }:
{
  imports = [ ../shared/programs.nix ];

  programs.nix-ld.enable = true;

  programs.npm = {
    enable = true;
    npmrc = ''
      prefix = ''${HOME}/.node_modules
    '';
  };
}
