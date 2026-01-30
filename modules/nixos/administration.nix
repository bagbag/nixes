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
      description = "Enable administration tools (SSH, sudo, etc.).";
    };
  };

  config = lib.mkIf cfg.enable {
    services.openssh = {
      enable = true;
      openFirewall = true;
      settings = {
        PasswordAuthentication = lib.mkDefault false;
        KbdInteractiveAuthentication = lib.mkDefault true;
        PermitRootLogin = lib.mkDefault "prohibit-password";
      };
    };

    security.doas.enable = true;
    security.sudo.enable = true;
  };
}
