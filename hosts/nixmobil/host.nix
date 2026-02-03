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
    common.enable = true;

    # User configuration
    user = {
      enable = true;
      name = "patrick";
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
      syncthing = {
        enable = true;
        devices = {
          "pixel10" = {
            name = "Pixel 10 Pro XL";
            id = "LFANBT3-MUYNDTL-LZEBKEE-Y7RLJY6-D3ACPXY-73TVXN2-SARNRPW-CKODLQL";
          };
          "nixstation" = {
            name = "nixstation";
            id = "E26C5UM-W5QYAS6-PCZXTN6-CDBNUNO-QMGH3AM-4CB2JQE-OYCH4WH-3MHNQQS";
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
              "nixstation"
              "nixbook-air"
              "iphone-17-pro-max"
            ];
          };
          "keepass-work" = {
            id = "jqqq6-c9zap";
            path = "/home/patrick/syncthing/keepass-work";
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

  # Secrets rekeying configuration
  # hostPubkey should be added here once the system is installed and keys are generated
  # age.rekey.hostPubkey = "...";
  age.rekey.masterIdentities = [ "~/.ssh/id_ed25519" ];
}
