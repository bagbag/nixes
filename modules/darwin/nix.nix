{ pkgs, ... }:
{
  imports = [ ../shared/nix.nix ];

  environment = {
    systemPackages = [ pkgs.nh ];
    variables.NH_FLAKE = "/etc/nix-darwin";
  };
}
