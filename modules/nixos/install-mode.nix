{
  config,
  lib,
  pkgs,
  ...
}:
{
  config = lib.mkIf config.modules.system.installMode {
    # ---------------------------------------------------------
    # System Level Overrides
    # ---------------------------------------------------------
    programs.firefox.enable = lib.mkForce false;
    programs.thunderbird.enable = lib.mkForce false;

    # ---------------------------------------------------------
    # Home Manager Overrides
    # ---------------------------------------------------------
    home-manager.users.${config.modules.user.name} = {
      programs.chromium.enable = lib.mkForce false;
      programs.vscode.enable = lib.mkForce false;
    };
  };
}
