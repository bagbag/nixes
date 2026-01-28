{
  disko.devices = {
    disk = {
      main = {
        type = "disk";
        content = {
          type = "gpt";
          partitions = {
            "esp" = {
              size = "1G";
              type = "EF00";
              content = {
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot";
                mountOptions = [ "umask=0077" ];
              };
            };
            "main" = {
              size = "100%";
              content = {
                type = "luks";
                name = "luks-main";
                settings.allowDiscards = true;
                content = {
                  type = "btrfs";
                  mountpoint = "/mnt/btrfs-roots/main";
                  mountOptions = [ "compress=zstd" ];
                  subvolumes = {
                    "/@root" = {
                      mountpoint = "/";
                      mountOptions = [ "compress=zstd" ];
                    };
                    "/@home" = {
                      mountpoint = "/home";
                      mountOptions = [ "compress=zstd" ];
                    };
                    "/@nix" = {
                      mountpoint = "/nix";
                      mountOptions = [
                        "compress=zstd"
                        "noatime"
                      ];
                    };
                    "/@var" = {
                      mountpoint = "/var";
                      mountOptions = [ "compress=zstd" ];
                    };
                    "/@snapshots" = { };
                  };
                };
              };
            };
          };
        };
      };
    };
  };

  services.btrbk.instances.system = {
    onCalendar = "*:0/15";

    settings = {
      incremental = "no";
      snapshot_create = "always";
      snapshot_preserve = "14d";
      snapshot_preserve_min = "2d";

      volume = {
        "/mnt/btrfs-roots/main" = {
          snapshot_dir = "@snapshots";
          subvolume = {
            "@root" = { };
            "@home" = { };
            "@var" = { };
          };
        };
      };
    };
  };
}
