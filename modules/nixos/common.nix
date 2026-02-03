{
  config,
  lib,
  inputs,
  ...
}:
let
  cfg = config.modules.common;
in
{
  imports = [
    inputs.disko.nixosModules.disko

    ./administration.nix
    ./base.nix
    ./firewall.nix
    ./home-manager.nix
    ./network.nix
    ./nix.nix
    ./podman.nix
    ./programs.nix
    ../shared/system.nix
    ../shared/system-packages.nix
    ./system-packages.nix

    ./services/librechat.nix
    ./services/mongodb.nix
    ../shared/services/syncthing-options.nix
  ];

  options.modules.common = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable common system modules.";
    };
  };

  config = lib.mkIf cfg.enable {
    modules.base.enable = lib.mkDefault true;
  };
}
