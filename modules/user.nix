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

    initialPassword = lib.mkOption {
      type = lib.types.str;
      default = "changeMeNow";
      description = "Initial password for the user.";
    };
  };

  config = lib.mkIf cfg.enable {
    users.mutableUsers = true;

    users.users.${cfg.name} = {
      isNormalUser = true;
      shell = pkgs.zsh;
      initialPassword = cfg.initialPassword;

      extraGroups = [
        "wheel"
        "networkmanager"
        "video"
        "audio"
      ];

      autoSubUidGidRange = true;
    };

    services.openssh.settings.AllowUsers = [ cfg.name ];

    security.doas.extraRules = [
      {
        users = [ cfg.name ];
        noPass = true;
      }
    ];

    security.sudo.extraRules = [
      {
        users = [ cfg.name ];
        commands = [
          {
            command = "ALL";
            options = [ "NOPASSWD" ];
          }
        ];
      }
    ];

    # Workaround for https://github.com/nix-community/home-manager/issues/322
    systemd.services."home-manager-${cfg.name}" = {
      preStart = ''
        rm -f "$HOME/.ssh/config"
      '';

      postStart = ''
        cp --remove-destination "$(readlink -f "$HOME/.ssh/config")" "$HOME/.ssh/config"
      '';
    };

    # Connect Home Manager Configuration
    home-manager.users.${cfg.name} = import ./home/home.nix;
  };
}
