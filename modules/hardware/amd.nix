{ config, lib, ... }:
let
  cfg = config.modules.hardware.amd;
in
{
  options.modules.hardware.amd = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable AMD CPU optimizations.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.kernelParams = [ "amd_pstate=active" ];
  };
}
