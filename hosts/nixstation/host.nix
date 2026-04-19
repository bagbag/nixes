{ config, inputs, ... }:
{
  imports = [
    ./hardware-configuration.nix
    ./disko.nix
    inputs.nixos-hardware.nixosModules.common-cpu-amd
    inputs.nixos-hardware.nixosModules.common-cpu-amd-pstate
    inputs.nixos-hardware.nixosModules.common-pc-ssd
  ];

  system.stateVersion = "25.11";

  # Host identification
  networking.hostName = "nixstation";

  # Use the module library
  modules = {
    system.type = "desktop";
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
      hostName = "nixstation";
      domain = "lan";
    };

    # Hardware specific workarounds
    hardware.spdif-workaround.enable = true;

    # Services
    services = {
      mongodb.enable = false;
      activitywatch.enable = true;
      qui.enable = false;

      librechat = {
        enable = false;
        googleServiceKeyFile = "/var/lib/librechat/google-insolytix-application-service-key.json";
      };

      syncthing = {
        enable = true;
        devices = {
          "pixel10" = {
            name = "Pixel 10 Pro XL";
            id = "ABC";
          };
          "nixmobil" = {
            name = "nixmobil";
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
              "nixmobil"
              "nixbook-air"
              "iphone-17-pro-max"
            ];
          };
        };
      };
    };
  };

  fileSystems."/home/p0v0/mnt/nixbook" = {
    device = "p0v0@nixbook-air.lan:/Users/p0v0";
    fsType = "fuse.sshfs";
    options = [
      "user"
      "noauto"
      "nodev"
      "noatime"
      "nosuid"
      "IdentityFile=/home/p0v0/.ssh/id_ed25519"
      "x-systemd.automount"
      "x-systemd.idle-timeout=600"
      "x-systemd.mount-timeout=5s"
      "x-systemd.after=network-online.target"
      "ConnectTimeout=5"
      "_netdev"
      "reconnect"
      "ServerAliveInterval=15"
    ];
  };

  # age.rekey = {
  #   storageMode = "local";
  #   hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFALQ9WJhksoUBKzZGwx2xN0Y6sb/1BEX4/j+PsdI3Cx";
  #   masterIdentities = [ "~/.ssh/id_ed25519" ];
  #   localStorageDir = ../../. + "/secrets/rekeyed/nixstation";
  # };
}
