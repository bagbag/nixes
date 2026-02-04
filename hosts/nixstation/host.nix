{ inputs, ... }:
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
      name = "patrick";
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
      mongodb.enable = true;
      activitywatch.enable = true;

      librechat = {
        enable = true;
        googleServiceKeyFile = "/var/lib/librechat/google-insolytix-application-service-key.json";
      };

      syncthing = {
        enable = true;
        devices = {
          "pixel10" = {
            name = "Pixel 10 Pro XL";
            id = "LFANBT3-MUYNDTL-LZEBKEE-Y7RLJY6-D3ACPXY-73TVXN2-SARNRPW-CKODLQL";
          };
          "nixmobil" = {
            name = "nixmobil";
            id = "BPCWIO6-XR3XFSG-AAGT5Q6-SEZLTGD-3YQZJAQ-3ATSTJY-HT6ALN6-KSPN2AL";
          };
          "nixbook-air" = {
            name = "nixbook-air";
            id = "SMDDMZM-643ZB7Y-GUTT7KF-A6PRWK3-RINATYN-OPSRTDW-RD5UVRL-6QV6QQZ";
          };
          "iphone-17-pro-max" = {
            name = "iPhone 17 Pro Max";
            id = "PVHXECA-YFONWHV-ZDXESDB-6QOVLKL-YCBFXUO-C4FZPSY-5D46XCT-VWV6DAG";
          };
        };
        folders = {
          "keepass" = {
            id = "dizum-nfezd";
            path = "/home/patrick/syncthing/keepass";
            devices = [
              "pixel10"
              "nixmobil"
              "nixbook-air"
              "iphone-17-pro-max"
            ];
          };
          "keepass-work" = {
            id = "jqqq6-c9zap";
            path = "/home/patrick/syncthing/keepass-work";
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

  fileSystems."/home/patrick/mnt/nixbook" = {
    device = "patrick@nixbook-air.lan:/Users/patrick";
    fsType = "fuse.sshfs";
    options = [
      "nodev"
      "noatime"
      "allow_other"
      "IdentityFile=/home/patrick/.ssh/id_ed25519"
      "x-systemd.automount"
      "x-systemd.idle-timeout=600"
      "_netdev"
      "noauto"
      "reconnect"
    ];
  };

  # Secrets rekeying configuration
  age.rekey = {
    hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFALQ9WJhksoUBKzZGwx2xN0Y6sb/1BEX4/j+PsdI3Cx";
    masterIdentities = [ "~/.ssh/id_ed25519" ];
  };
}
