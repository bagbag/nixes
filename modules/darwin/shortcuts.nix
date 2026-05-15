{
  config,
  lib,
  ...
}:
{
  options.modules.shortcuts = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable global keyboard shortcuts (skhd).";
    };
  };

  config = lib.mkIf config.modules.shortcuts.enable {
    # Global hotkey daemon. Mirrors the GNOME binding in
    # modules/shared/home/home.nix (Shift+Alt+T spawns a new Ghostty window).
    services.skhd = {
      enable = true;
      skhdConfig = ''
        shift + alt - t : open -na Ghostty
      '';
    };
  };
}
