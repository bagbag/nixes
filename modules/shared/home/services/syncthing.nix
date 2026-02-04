{
  lib,
  osConfig,
  ...
}:
let
  cfg = osConfig.modules.services.syncthing;
in
{
  config = lib.mkIf cfg.enable {
    services.syncthing = {
      enable = true;

      overrideDevices = true;
      overrideFolders = true;

      settings = {
        devices = cfg.devices;
        folders = cfg.folders;
      };
    };
  };
}
