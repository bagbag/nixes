{ pkgs, ... }:
{
  programs.zsh.enable = true;

  programs.npm = {
    enable = true;
    package = pkgs.nodePackages_latest.npm;
    npmrc = ''
      prefix = ''${HOME}/.npm
    '';
  };
}
