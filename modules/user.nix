{
  pkgs,
  inputs,
  ...
}:
{
  services.userborn.enable = true;
  users.mutableUsers = false;

  users.users.patrick = {
    isNormalUser = true;
    shell = pkgs.zsh;
    initialPassword = "changeMeNow";
    extraGroups = [
      "wheel"
      "networkmanager"
      "video"
      "audio"
    ];
  };

  services.openssh.settings.AllowUsers = [ "patrick" ];

  security.doas.extraRules = [
    {
      users = [ "patrick" ];
      noPass = true;
    }
  ];

  security.sudo.extraRules = [
    {
      users = [ "patrick" ];
      commands = [
        {
          command = "ALL";
          options = [ "NOPASSWD" ];
        }
      ];
    }
  ];

  # Workaround for https://github.com/nix-community/home-manager/issues/322
  systemd.services.home-manager-patrick = {
    preStart = ''
      rm -f "$HOME/.ssh/config"
    '';

    postStart = ''
      cp --remove-destination "$(readlink -f "$HOME/.ssh/config")" "$HOME/.ssh/config"
    '';
  };

  # Connect Home Manager Configuration
  home-manager.users.patrick = import ./home.nix;
}
