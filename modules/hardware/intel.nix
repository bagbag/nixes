{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.hardware.intel;
in
{
  options.modules.hardware.intel = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable Intel CPU optimizations.";
    };
  };

  config = lib.mkIf cfg.enable {
    hardware.cpu.intel.updateMicrocode = lib.mkDefault config.hardware.enableRedistributableFirmware;

    # VA-API
    hardware.graphics = {
      enable = true;
      extraPackages = with pkgs; [
        intel-media-driver
        libvdpau-va-gl
        intel-compute-runtime
        intel-npu-driver
      ];
    };
    environment.sessionVariables = {
      LIBVA_DRIVER_NAME = "iHD";
    };

    # P-State
    boot.kernelParams = [ "intel_pstate=active" ];
  };
}
