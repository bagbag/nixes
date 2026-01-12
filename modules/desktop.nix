{
  config,
  pkgs,
  lib,
  ...
}:
{
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
    # pulse.enable = true; # PulseAudio server emulation
    # jack.enable = true;  # JACK audio server emulation
  };

  # ---------------------------------------------------------
  # Bluetooth
  # ---------------------------------------------------------
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
    settings.General.Experimental = true; # Displays battery % for devices
  };

  services.blueman.enable = true; # GUI for Bluetooth management

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

    # Nerd Fonts (required for Starship prompt and eza icons)
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

  # Add Firefox as a fallback system browser
  programs.firefox = {
    enable = true;
    package = pkgs.firefox-devedition;
  };

  programs.thunderbird.enable = true;

  # Auto-login configuration
  services.displayManager.autoLogin.enable = true;
  services.displayManager.autoLogin.user = "patrick";

  security.pam.services.gdm-password.enableGnomeKeyring = true;

  # ---------------------------------------------------------
  # GNOME Specific Options
  # ---------------------------------------------------------
  services.gnome.core-apps.enable = true;
  services.gnome.core-developer-tools.enable = true;
  services.gnome.games.enable = false;

  environment.systemPackages = with pkgs; [
    gnome-tweaks
    easyeffects

    # GUI Applications
    keepassxc
  ];

  # ---------------------------------------------------------
  # Theming
  # ---------------------------------------------------------
  stylix.base16Scheme = "${pkgs.base16-schemes}/share/themes/gruvbox-dark-hard.yaml";
}
