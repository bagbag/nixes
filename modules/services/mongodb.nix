{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.services.mongodb;
in
{
  options.modules.services.mongodb = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable MongoDB service.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.mongodb = {
      enable = true;
      package = pkgs.mongodb-ce;
      dbpath = "/var/lib/mongodb";
    };
  };
}
