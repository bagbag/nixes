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
    # modules/shared/home/home.nix (Shift+Alt+T opens a new Ghostty window).
    # Uses AppleScript instead of `open -n` so we get a new window in the
    # existing Ghostty process rather than a new process (which would add a
    # separate Dock icon every time).
    services.skhd = {
      enable = true;
      skhdConfig = ''
        shift + alt - t : osascript -e 'tell application "Ghostty" to activate' -e 'tell application "System Events"' -e 'repeat until frontmost of process "Ghostty" is true' -e 'delay 0.05' -e 'end repeat' -e 'keystroke "n" using command down' -e 'end tell'
      '';
    };
  };
}
