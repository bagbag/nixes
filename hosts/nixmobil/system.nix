{ config, ... }:
{
  nstdl.accounts.users.patrick.hashedPasswordFile = config.age.secrets.patrick-password-hash.path;

  services.displayManager.autoLogin = {
    enable = true;
    user = "patrick";
  };
  security.pam.services.gdm-password.enableGnomeKeyring = true;

  home-manager.users.patrick.services.syncthing = {
    enable = true;
    overrideDevices = true;
    overrideFolders = true;
    settings = {
      devices = {
        nixstation = {
          name = "nixstation";
          id = "E26C5UM-W5QYAS6-PCZXTN6-CDBNUNO-QMGH3AM-4CB2JQE-OYCH4WH-3MHNQQS";
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
          devices = [
            "nixstation"
            "nixbook-air"
            "iphone-17-pro-max"
          ];
        };
        keepass-work = {
          id = "jqqq6-c9zap";
          path = "/home/patrick/syncthing/keepass-work";
          devices = [
            "nixstation"
            "nixbook-air"
            "iphone-17-pro-max"
          ];
        };
      };
    };
  };
}
