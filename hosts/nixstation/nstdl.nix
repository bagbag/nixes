{ config, pkgs, ... }:
{
  nstdl.accounts.users.patrick.hashedPasswordFile = config.age.secrets.patrick-password-hash.path;

  services.displayManager.autoLogin = {
    enable = true;
    user = "patrick";
  };
  security.pam.services.gdm-password.enableGnomeKeyring = true;

  boot.kernelParams = [ "usbcore.autosuspend=-1" ];
  services.pipewire.wireplumber.extraConfig."10-disable-spdif-suspend" = {
    "monitor.alsa.rules" = [
      {
        matches = [ { "node.name" = "~alsa_output.usb-Generic_USB_Audio.*"; } ];
        actions.update-props."session.suspend-timeout-seconds" = 0;
      }
    ];
  };

  services = {
    ollama = {
      enable = true;
      package = pkgs.ollama-rocm;
    };
    llama-swap = {
      enable = true;
      settings = {
        healthCheckTimeout = 600;
        models = { };
      };
    };
    qui.enable = true;
  };
  systemd.services = {
    ollama.after = [ "systemd-modules-load.service" ];
    llama-swap = {
      after = [ "systemd-modules-load.service" ];
      serviceConfig.StateDirectory = "llama-swap";
      environment.LLAMA_CACHE = "/var/lib/llama-swap";
    };
    qui-secret-generator = {
      description = "Generate session secret for qui";
      wantedBy = [ "multi-user.target" ];
      before = [ "qui.service" ];
      path = [ pkgs.openssl ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        if [ ! -f /var/lib/qui/secret ]; then
          mkdir -p /var/lib/qui
          openssl rand -hex 32 > /var/lib/qui/secret
          chmod 600 /var/lib/qui/secret
        fi
      '';
    };
    qui = {
      after = [ "qui-secret-generator.service" ];
      requires = [ "qui-secret-generator.service" ];
    };
  };
  services.qui.secretFile = "/var/lib/qui/secret";

  home-manager.users.patrick.services.syncthing = {
    enable = true;
    overrideDevices = true;
    overrideFolders = true;
    settings = {
      devices = {
        nixmobil = {
          name = "nixmobil";
          id = "BPCWIO6-XR3XFSG-AAGT5Q6-SEZLTGD-3YQZJAQ-3ATSTJY-HT6ALN6-KSPN2AL";
        };
        nixbook-air = {
          name = "nixbook-air";
          id = "SMDDMZM-643ZB7Y-GUTT7KF-A6PRWK3-RINATYN-OPSRTDW-RD5UVRL-6QV6QQZ";
        };
        iphone-17-pro-max = {
          name = "iPhone 17 Pro Max";
          id = "PVHXECA-YFONWHV-ZDXESDB-6QOVLKL-YCBFXUO-C4FZPSY-5D46XCT-VWV6DAG";
        };
      };
      folders = {
        keepass = {
          id = "dizum-nfezd";
          path = "/home/patrick/syncthing/keepass";
          devices = [ "nixmobil" "nixbook-air" "iphone-17-pro-max" ];
        };
        keepass-work = {
          id = "jqqq6-c9zap";
          path = "/home/patrick/syncthing/keepass-work";
          devices = [ "nixmobil" "nixbook-air" "iphone-17-pro-max" ];
        };
      };
    };
  };

  fileSystems."/home/patrick/mnt/nixbook" = {
    device = "patrick@nixbook-air.lan:/Users/patrick";
    fsType = "fuse.sshfs";
    options = [
      "user"
      "noauto"
      "nodev"
      "noatime"
      "nosuid"
      "IdentityFile=/home/patrick/.ssh/id_ed25519"
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
}
