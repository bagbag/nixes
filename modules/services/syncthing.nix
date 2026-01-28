{
  config,
  lib,
  ...
}:
let
  cfg = config.modules.services.syncthing;
in
{
  options.modules.services.syncthing = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable Syncthing service.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = if config.modules.user.enable then config.modules.user.name else "syncthing";
      description = "User to run Syncthing as.";
    };

    devices = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            name = lib.mkOption { type = lib.types.str; };
            id = lib.mkOption { type = lib.types.str; };
          };
        }
      );
      default = { };
      description = "Syncthing devices.";
    };

    folders = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            id = lib.mkOption { type = lib.types.str; };
            path = lib.mkOption { type = lib.types.path; };
            devices = lib.mkOption { type = lib.types.listOf lib.types.str; };
          };
        }
      );
      default = { };
      description = "Syncthing folders.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.syncthing = {
      enable = true;
      openDefaultPorts = true;
      user = cfg.user;
      settings = {
        devices = cfg.devices;
        folders = cfg.folders;
      };
    };
  };
}
