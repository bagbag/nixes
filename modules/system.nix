{
  config,
  lib,
  ...
}:
let
  cfg = config.modules.system;
in
{
  options.modules.system = {
    type = lib.mkOption {
      type = lib.types.enum [
        "desktop"
        "server"
      ];
      default = "server";
      description = "The type of system (desktop or server), used to set sensible defaults.";
    };
  };
}
