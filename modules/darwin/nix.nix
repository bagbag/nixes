{ pkgs, ... }:
{
  imports = [ ../shared/nix.nix ];

  environment = {
    systemPackages = [ pkgs.nh ];
    variables.NH_FLAKE = "/etc/nix-darwin";
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
