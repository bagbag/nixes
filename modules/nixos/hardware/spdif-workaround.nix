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
    # Workaround for SPDIF audio drops. snd_usb_audio has no power_save
    # param (modinfo confirms); usbcore.autosuspend is the real knob.
    boot.kernelParams = [
      "usbcore.autosuspend=-1"
    ];

    services.pipewire.wireplumber.extraConfig = {
      "10-disable-spdif-suspend" = {
        "monitor.alsa.rules" = [
          {
            matches = [
              {
                # Match any output node from this card -- the SPDIF node's
                # name varies by ACP profile (e.g. HiFi__Speaker__sink,
                # pro-output-2), not just "*SPDIF*".
                "node.name" = "~alsa_output.usb-Generic_USB_Audio.*";
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
