{ pkgs, ... }:
{
  imports = [ ../shared/programs.nix ];

  programs.nix-ld.enable = true;

  programs.npm = {
    enable = true;
    package = pkgs.nodePackages_latest.npm;
    npmrc = ''
      prefix = ''${HOME}/.node_modules
    '';
  };
}
