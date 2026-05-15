{ inputs, ... }:
{
  system.stateVersion = 6;

  # Use the module library
  modules = {
    system.type = "desktop";
    common.enable = true;

    # User configuration
    user = {
      enable = true;
      name = "patrick";
      authorizedKeys = [
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMM/o1cLFjnD1m41DE41yWySYzOjvN7MizVJLIpbhbXN patrick@nixstation"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICvnCyc7hK0Tb5bXujzcjF+FjpmGi4FnfD9y84RtU6ZQ patrick@nixmobil"
      ];
    };

    # Services
    services.syncthing.enable = true;
  };

  # Networking
  networking = {
    hostName = "nixbook-air";
    applicationFirewall = {
      enable = true;
      enableStealthMode = false;
    };
  };

  # Nix configuration
  nix.settings.trusted-users = [
    "root"
    "patrick"
  ];

  # System Defaults
  system.defaults = {
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

  system.startup.chime = false;

  security.pam.services.sudo_local = {
    enable = true;
    reattach = true;
    touchIdAuth = true;
  };

  age.rekey = {
    storageMode = "local";
    hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPpPhXfy+OmQXWkjhFxn68tDs+++MTXzpSgMS3iM5gwN";
    masterIdentities = [ "~/.ssh/id_ed25519" ];
    localStorageDir = ../../. + "/secrets/rekeyed/nixbook-air";
  };

  # Set Git commit hash for darwin-version.
  system.configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;
}
