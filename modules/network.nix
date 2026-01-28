{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.network;
  sys = config.modules.system;
  userCfg = config.modules.user;
in
{
  options.modules.network = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable networking configuration.";
    };

    hostName = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "System hostname.";
    };

    domain = lib.mkOption {
      type = lib.types.str;
      default = "local";
      description = "System domain.";
    };

    manager = lib.mkOption {
      type = lib.types.enum [
        "networkmanager"
        "networkd"
      ];
      default = if sys.type == "desktop" then "networkmanager" else "networkd";
      description = "Networking backend to use.";
    };
  };

  config = lib.mkIf cfg.enable {
    networking.hostName = cfg.hostName;
    networking.domain = cfg.domain;

    networking.networkmanager = lib.mkIf (cfg.manager == "networkmanager") {
      enable = true;
      plugins = with pkgs; [
        networkmanager-openvpn
      ];
    };

    # Enable systemd-networkd if selected
    systemd.network.enable = lib.mkIf (cfg.manager == "networkd") true;

    # Add user to networkmanager group if enabled and user module is active
    users.users.${userCfg.name}.extraGroups = lib.mkIf (
      cfg.manager == "networkmanager" && userCfg.enable
    ) [ "networkmanager" ];
  };
}
