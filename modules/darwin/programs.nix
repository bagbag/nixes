{
  config,
  lib,
  pkgs,
  ...
}:
{
  imports = [ ../shared/programs.nix ];

  options.modules.programs = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable default programs.";
    };
  };

  config = lib.mkIf config.modules.programs.enable {
    # Homebrew Configuration
    homebrew = {
      enable = true;

      onActivation = {
        autoUpdate = true;
        upgrade = true;
        cleanup = "zap";
        extraFlags = [ "--force-cleanup" ]; # workaround until https://github.com/nix-darwin/nix-darwin/issues/1787 is fixed
      };

      taps = [ ];

      brews = [ ];

      casks = [
        "firefox@developer-edition"
        "spotify"
        "ghostty"
        "rustdesk"
        "keepassxc"
        "libreoffice"
        "whatsapp"
      ];

      masApps = {
        "Bitwarden" = 1352778147;
      };
    };
  };
}
