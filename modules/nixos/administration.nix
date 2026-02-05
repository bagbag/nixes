{
  config,
  lib,
  ...
}:
let
  cfg = config.modules.administration;
in
{
  options.modules.administration = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable administration tools (sudo, etc.).";
    };
  };

  config = lib.mkIf cfg.enable {
    security.doas.enable = true;
    security.sudo.enable = true;
  };
}
