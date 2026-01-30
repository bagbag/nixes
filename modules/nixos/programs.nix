{ pkgs, ... }:
{
  programs.nix-ld.enable = true;

  programs.zsh.enable = true;

  programs.npm = {
    enable = true;
    package = pkgs.nodePackages_latest.npm;
    npmrc = ''
      prefix = ''${HOME}/.node_modules
    '';
  };
}
