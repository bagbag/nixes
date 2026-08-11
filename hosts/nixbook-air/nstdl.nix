{ ... }:
{
  homebrew = {
    masApps.Bitwarden = 1352778147;
  };

  networking.applicationFirewall = {
    enable = true;
    enableStealthMode = false;
  };

  nix.settings.trusted-users = [ "patrick" ];

  system = {
    startup.chime = false;
    defaults = {
      dock = {
        autohide = true;
        show-recents = false;
        static-only = false;
        mru-spaces = false;
        persistent-apps = [
          "/Applications/Ghostty.app"
          "/Applications/Firefox Developer Edition.app"
        ];
      };
      finder = {
        AppleShowAllExtensions = true;
        ShowPathbar = true;
        ShowStatusBar = true;
        FXPreferredViewStyle = "clmv";
        FXEnableExtensionChangeWarning = false;
        _FXShowPosixPathInTitle = true;
        CreateDesktop = false;
      };
      trackpad = {
        Clicking = true;
        TrackpadThreeFingerDrag = true;
      };
      loginwindow.GuestEnabled = false;
      screensaver.askForPasswordDelay = 5;
      screencapture = {
        location = "~/Pictures/Screenshots";
        disable-shadow = true;
      };
      NSGlobalDomain = {
        AppleInterfaceStyle = "Dark";
        KeyRepeat = 2;
        InitialKeyRepeat = 15;
        ApplePressAndHoldEnabled = false;
        AppleShowAllExtensions = true;
        AppleICUForce24HourTime = true;
        NSDocumentSaveNewDocumentsToCloud = false;
      };
      controlcenter.BatteryShowPercentage = true;
      CustomUserPreferences."com.apple.desktopservices" = {
        DSDontWriteNetworkStores = true;
        DSDontWriteUSBStores = true;
      };
    };
  };

  security.pam.services.sudo_local = {
    enable = true;
    reattach = true;
    touchIdAuth = true;
  };
}
