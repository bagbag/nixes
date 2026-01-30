{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.desktop;
in
{
  options.modules.desktop = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = config.modules.system.type == "desktop";
      description = "Enable desktop environment.";
    };

    autoLoginUser = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = if config.modules.user.enable then config.modules.user.name else null;
      description = "User to auto-login.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.displayManager.gdm.enable = true;
    services.desktopManager.gnome.enable = true;

    # ---------------------------------------------------------
    # Audio (PipeWire)
    # ---------------------------------------------------------
    services.pulseaudio.enable = false;
    security.rtkit.enable = true;

    services.pipewire = {
      enable = true;
      alsa.enable = true;
      alsa.support32Bit = true;
    };

    # ---------------------------------------------------------
    # Bluetooth
    # ---------------------------------------------------------
    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
      settings.General.Experimental = true;
    };

    services.blueman.enable = true;

    # ---------------------------------------------------------
    # Firmware Updates
    # ---------------------------------------------------------
    services.fwupd.enable = true;

    # ---------------------------------------------------------
    # Fonts
    # ---------------------------------------------------------
    fonts.packages = with pkgs; [
      noto-fonts
      noto-fonts-color-emoji
      liberation_ttf
      fira-code
      fira-code-symbols
      nerd-fonts.fira-code
      nerd-fonts.droid-sans-mono
    ];

    # ---------------------------------------------------------
    # Software Infrastructure
    # ---------------------------------------------------------
    services.flatpak.enable = true;
    programs.dconf.enable = true;

    xdg.portal = {
      enable = true;
      extraPortals = [ pkgs.xdg-desktop-portal-gnome ];
    };

    programs.firefox = {
      enable = true;
      package = pkgs.firefox-devedition;
    };

    programs.thunderbird.enable = true;

    # Auto-login configuration
    services.displayManager.autoLogin = lib.mkIf (cfg.autoLoginUser != null) {
      enable = true;
      user = cfg.autoLoginUser;
    };

    security.pam.services.gdm-password.enableGnomeKeyring = true;

    # ---------------------------------------------------------
    # GNOME Specific Options
    # ---------------------------------------------------------
    services.gnome.core-apps.enable = true;
    services.gnome.core-developer-tools.enable = true;
    services.gnome.games.enable = false;

    environment.systemPackages =
      with pkgs;
      [
        gnome-disk-utility
      ]
      ++ (lib.optionals (!config.modules.system.installMode) [
        gnome-tweaks
        easyeffects
        keepassxc
      ]);

    # ---------------------------------------------------------
    # Theming
    # ---------------------------------------------------------
    stylix.base16Scheme = "${pkgs.base16-schemes}/share/themes/onedark.yaml";
    stylix.image = pkgs.fetchurl {
      url = "https://getwallpapers.com/wallpaper/full/1/4/3/523784.jpg";
      hash = "sha256-S/6kgloXiIYI0NblT6YVXfqELApbdHGsuYe6S4JoQwQ=";
    };
  };
}
