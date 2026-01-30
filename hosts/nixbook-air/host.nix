{ inputs, ... }:
{
  system.stateVersion = 5;

  # Use the module library
  modules = {
    system.type = "desktop";
    common.enable = true;

    # User configuration
    user = {
      enable = true;
      name = "patrick";
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

  security.pam.services.sudo_local.touchIdAuth = true;

  # Secrets rekeying configuration
  # age.rekey = {
  #   hostPubkey = "ssh-ed25519 <INSERT_MACBOOK_PUBKEY>";
  #   masterIdentities = [ "~/.ssh/id_ed25519" ];
  # };

  # Set Git commit hash for darwin-version.
  system.configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;
}
