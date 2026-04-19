{ inputs, ... }:
{
  imports = [
    ./hardware-configuration.nix
    ./disko.nix
    inputs.nixos-hardware.nixosModules.common-cpu-intel
    inputs.nixos-hardware.nixosModules.common-pc-laptop
    inputs.nixos-hardware.nixosModules.common-pc-laptop-ssd
  ];

  system.stateVersion = "25.11";

  # Host identification
  networking.hostName = "nixmobil";

  # Use the module library
  modules = {
    system.type = "desktop";
    system.installMode = true;
    common.enable = true;

    # User configuration
    user = {
      enable = true;
      name = "p0v0";
      authorizedKeys = [
      ];
    };

    # Networking
    network = {
      hostName = "nixmobil";
      domain = "lan";
    };

    # Hardware specific optimizations
    hardware = {
      intel.enable = true;
      laptop.enable = true;
    };

    # Services
    services = {
      activitywatch.enable = true;

      syncthing = {
        enable = true;
        devices = {
          "pixel10" = {
            name = "Pixel 10 Pro XL";
            id = "ABC";
          };
          "nixstation" = {
            name = "nixstation";
            id = "ABC";
          };
          "nixbook-air" = {
            name = "nixbook-air";
            id = "ABC";
          };
          "iphone-17-pro-max" = {
            name = "iPhone 17 Pro Max";
            id = "ABC";
          };
        };
        folders = {
          "keepass" = {
            id = "ABC";
            path = "/home/p0v0/syncthing/keepass";
            devices = [
              "pixel10"
              "nixstation"
              "nixbook-air"
              "iphone-17-pro-max"
            ];
          };
        };
      };
    };
  };

  # age.rekey = {
  #   storageMode = "local";
  #   hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHBJaMs/1fLo7FOQD5xTHc7Pox4rHN5G6hX96P81DO4e";
  #   masterIdentities = [ "~/.ssh/id_ed25519" ];
  #   localStorageDir = ../../. + "/secrets/rekeyed/nixmobil";
  # };
}
