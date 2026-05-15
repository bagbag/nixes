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

  # Tiny aarch64-linux VM used as a remote builder so this Mac can build
  # Linux derivations (e.g. for deploying NixOS hosts from another repo).
  nix.linux-builder = {
    enable = true;
    ephemeral = true;
    maxJobs = 4;
    systems = [
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
}
