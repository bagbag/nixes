{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.hardware.laptop;
in
{
  options.modules.hardware.laptop = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable laptop optimizations.";
    };
  };

  config = lib.mkIf cfg.enable {
    # Power Management
    services.auto-cpufreq.enable = true;
    services.thermald.enable = true;

    # Conflicts with auto-cpufreq
    services.power-profiles-daemon.enable = false;
  };
}
