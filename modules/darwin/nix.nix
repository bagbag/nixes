{ pkgs, ... }:
{
  imports = [ ../shared/nix.nix ];

  programs.nh = {
    enable = true;
    flake = "/etc/nixos";
  };

  nix.gc = {
    automatic = true;
    interval = {
      Hour = 8;
      Minute = 0;
    };
    options = "--delete-older-than 7d";
  };

  nix.optimise = {
    automatic = true;
    interval = {
      Hour = 8;
      Minute = 0;
    };
  };
}
