{ config, lib, ... }:
{
  services.openssh = {
    openFirewall = true;
    settings = {
      PasswordAuthentication = lib.mkDefault false;
      KbdInteractiveAuthentication = lib.mkDefault true;
      PermitRootLogin = lib.mkDefault "prohibit-password";
      AllowUsers = lib.mkIf (config.modules.user.enable or false) [ config.modules.user.name ];
    };
  };
}
