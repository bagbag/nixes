{ pkgs, ... }:
{
  imports = [ ../shared/programs.nix ];

  programs.nix-ld.enable = true;
}
