{
  config,
  lib,
  osConfig,
  ...
}:
let
  cfg = osConfig.modules.services.syncthing;
in
{
  services.syncthing = {
    enable = cfg.enable;
    settings = {
      devices = cfg.devices;
      folders = cfg.folders;
    };
  };
}