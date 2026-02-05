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
  networking.hostName = "nixbook-air";

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
      static-only = true;
    };

    finder = {
      AppleShowAllExtensions = true;
      ShowPathbar = true;
      FXPreferredViewStyle = "clmv";
    };

    loginwindow.GuestEnabled = false;
    NSGlobalDomain.AppleInterfaceStyle = "Dark";
  };

  security.pam.services.sudo_local = {
    enable = true;
    touchIdAuth = true;
    watchIdAuth = true;
    reattach = true;
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
