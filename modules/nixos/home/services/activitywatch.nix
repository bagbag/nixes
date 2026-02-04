{
  pkgs,
  lib,
  osConfig,
  ...
}:
let
  cfg = osConfig.modules.services.activitywatch;
in
{
  config = lib.mkIf cfg.enable {
    services.activitywatch = {
      enable = true;
      # Use the high-performance Rust server
      package = pkgs.aw-server-rust;

      watchers = {
        # The AFK watcher: Tracks if you are actually at the computer
        aw-watcher-afk = {
          package = pkgs.activitywatch;
          executable = "aw-watcher-afk";
          settings = {
            timeout = 300;
            poll_time = 2;
          };
        };

        # The GNOME bridge: Required for window tracking on GNOME Wayland
        aw-watcher-gnome = {
          package = pkgs.activitywatch;
          executable = "aw-watcher-gnome";
        };

        # Optional: Input watcher (tracks keypress/mouse click frequency)
        aw-watcher-input = {
          package = pkgs.activitywatch;
          executable = "aw-watcher-input";
        };
      };
    };

    # Crucial: Install and enable the GNOME Extension
    home.packages = [ pkgs.gnomeExtensions.activitywatch-status ];
  };
}
