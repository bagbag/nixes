{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.common;
in
{
  imports = [
    ./home-manager.nix
    ./user.nix
    ./programs.nix
    ./system-packages.nix
    ../shared/services/syncthing-options.nix
    ../shared/system.nix
    ../shared/system-packages.nix
    ../shared/secrets.nix
    ../shared/services/openssh.nix
  ];

  options.modules.common = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable common system modules.";
    };
  };

  config = lib.mkIf cfg.enable {
    nixpkgs.config.allowUnfree = true;

    nix.settings.experimental-features = [
      "nix-command"
      "flakes"
    ];

    # Darwin specific settings
    system.primaryUser = config.modules.user.name;

    # Font Management
    fonts.packages = with pkgs; [
      noto-fonts
      noto-fonts-color-emoji
      liberation_ttf
      fira-code
      fira-code-symbols
      nerd-fonts.fira-code
      nerd-fonts.droid-sans-mono
    ];
  };
}
