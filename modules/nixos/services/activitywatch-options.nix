{ lib, ... }:
{
  options.modules.services.activitywatch = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable ActivityWatch service.";
    };
  };
}
