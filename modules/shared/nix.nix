{ pkgs, config, ... }:
{
  nix = {
    package = pkgs.lix;

    settings.trusted-users = [
      "root"
      config.modules.user.name
    ];
  };

  programs.nh = {
    enable = true;
    flake = "/etc/nixos";

    clean = {
      enable = true;
      dates = "08:00";
      extraArgs = "--keep 5 --keep-since 7d --optimise";
    };
  };
}
