{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.user;
in
{
  options.modules.user = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable user configuration.";
    };

    name = lib.mkOption {
      type = lib.types.str;
      description = "Primary username.";
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.name} = {
      home = "/Users/${cfg.name}";
      shell = pkgs.zsh;
    };

    # Connect Home Manager Configuration
    home-manager.users.${cfg.name} = import ../shared/home/home.nix;
  };
}
