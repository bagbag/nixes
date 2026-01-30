{
  config,
  lib,
  pkgs,
  ...
}:
{
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
      };

      taps = [
        "homebrew/services"
      ];

      casks = [
        "firefox-developer-edition"
        "spotify"
        "ghostty"
        "bitwarden"
      ];

      masApps = {
        # Add Mac App Store apps here as "AppName" = appID;
      };
    };
  };
}
