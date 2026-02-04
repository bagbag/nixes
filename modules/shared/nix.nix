{ pkgs, config, ... }:
{
  nix = {
    package = pkgs.lix;

    settings.trusted-users = [
      "root"
      config.modules.user.name
    ];
  };
}
