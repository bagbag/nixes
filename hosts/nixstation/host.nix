{ inputs, ... }:
{
  imports = [
    ./hardware-configuration.nix
    ./disko.nix
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
    hardware.amd.enable = true;

    # Services
    services = {
      librechat = {
        enable = true;
        googleServiceKeyFile = "/var/lib/librechat/google-insolytix-application-service-key.json";
      };
      mongodb.enable = true;
      syncthing = {
        enable = true;
        devices = {
          "pixel10" = {
            name = "Pixel 10 Pro XL";
            id = "LFANBT3-MUYNDTL-LZEBKEE-Y7RLJY6-D3ACPXY-73TVXN2-SARNRPW-CKODLQL";
          };
        };
        folders = {
          "keepass" = {
            id = "dizum-nfezd";
            path = "/home/patrick/syncthing/keepass";
            devices = [ "pixel10" ];
          };
          "keepass-work" = {
            id = "jqqq6-c9zap";
            path = "/home/patrick/syncthing/keepass-work";
            devices = [ "pixel10" ];
          };
        };
      };
    };
  };

  # Secrets rekeying configuration
  age.rekey = {
    hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFALQ9WJhksoUBKzZGwx2xN0Y6sb/1BEX4/j+PsdI3Cx";
    masterIdentities = [ "~/.ssh/id_ed25519" ];
  };
}
