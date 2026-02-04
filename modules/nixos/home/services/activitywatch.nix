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

        # Optional: Input watcher (tracks keypress/mouse click frequency)
        aw-watcher-input = {
          package = pkgs.activitywatch;
          executable = "aw-watcher-input";
        };
      };
    };

    # awatcher handles window tracking on Wayland natively
    home.packages = with pkgs; [
      awatcher
      gnomeExtensions.focused-window-d-bus
    ];

    # Create a simple systemd service to run it in the background
    systemd.user.services.awatcher = {
      Unit = {
        Description = "ActivityWatch Wayland watcher";
        After = [ "graphical-session.target" ];
        PartOf = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = "${pkgs.awatcher}/bin/awatcher";
        Restart = "always";
      };
      Install = {
        WantedBy = [ "graphical-session.target" ];
      };
    };
  };
}
