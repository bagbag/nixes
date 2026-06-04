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
    # Ghostty has no working AppleScript dictionary and no CLI/URL action for
    # "new window", so we drive its `File > New Window` menu item via the
    # Accessibility API. Layout-independent (unlike `keystroke "n"`) and
    # deterministic (unlike `make new window`, which silently fails on a
    # non-scriptable Cocoa app). Requires skhd to have Accessibility access.
    # When Ghostty isn't running yet, `activate` launches it and macOS
    # creates the initial window automatically.
    services.skhd = {
      enable = false;
      skhdConfig = ''
        shift + alt - t : osascript -e 'if application "Ghostty" is running then' -e 'tell application "System Events" to tell process "Ghostty" to click menu item "New Window" of menu "File" of menu bar 1' -e 'else' -e 'tell application "Ghostty" to activate' -e 'end if'
      '';
    };
  };
}
