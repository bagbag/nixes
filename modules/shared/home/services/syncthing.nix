{
  config,
  lib,
  osConfig,
  pkgs,
  ...
}:
let
  cfg = osConfig.modules.services.syncthing;
in
{
  services.syncthing = {
    enable = cfg.enable;

    overrideDevices = true;
    overrideFolders = true;

    settings = {
      devices = cfg.devices;
      folders = cfg.folders;
    };
  };

  launchd.agents.syncthing-init = lib.mkIf pkgs.stdenv.isDarwin {
    enable = lib.mkForce true;

    config = {
      WatchPaths = lib.mkForce [ ];
      RunAtLoad = true;
    };
  };
}
