{ lib, config, ... }:
let
  cfg = config.modules.hardware.spdif-workaround;
in
{
  options.modules.hardware.spdif-workaround = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable workaround for SPDIF audio drops.";
    };
  };

  config = lib.mkIf cfg.enable {
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
  };
}
