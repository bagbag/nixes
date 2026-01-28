{
  imports = [
    ./hardware-configuration.nix
    ./disko.nix

    ../../modules/hardware/amd.nix

    ./services/librechat.nix
    ./services/mongodb.nix
    ./services/syncthing.nix
  ];

  system.stateVersion = "25.11";

  networking.hostName = "nixstation";
  networking.domain = "lan";
  networking.search = [ "lan" ];

  # Workaround for SPDIF audio drops
  boot.kernelParams = [
    "snd_usb_audio.power_save=0"
    "snd_usb_audio.power_save_controller=N"
  ];

  services.pipewire.wireplumber.extraConfig = {
    "10-disable-spdif-suspend" = {
      "monitor.alsa.rules" = [
        {
          matches = [
            {
              "node.name" = "~alsa_output.usb-Generic_USB_Audio.*SPDIF.*";
            }
          ];
          actions = {
            update-props = {
              "session.suspend-timeout-seconds" = 0; # Keep the hardware awake
            };
          };
        }
      ];
    };
  };
}
