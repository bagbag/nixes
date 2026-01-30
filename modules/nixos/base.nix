{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.base;
in
{
  options.modules.base = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable base system configuration.";
    };

    timeZone = lib.mkOption {
      type = lib.types.str;
      default = "Europe/Berlin";
      description = "System time zone.";
    };

    defaultLocale = lib.mkOption {
      type = lib.types.str;
      default = "en_US.UTF-8";
      description = "Default system locale.";
    };

    extraLocale = lib.mkOption {
      type = lib.types.str;
      default = "de_DE.UTF-8";
      description = "Extra locale for formatting.";
    };

    consoleKeyMap = lib.mkOption {
      type = lib.types.str;
      default = "de-latin1-nodeadkeys";
      description = "Console key map.";
    };

    xkbLayout = lib.mkOption {
      type = lib.types.str;
      default = "de";
      description = "X11 keyboard layout.";
    };
  };

  config = lib.mkIf cfg.enable {
    # ---------------------------------------------------------
    # Nixpkgs Configuration
    # ---------------------------------------------------------
    nixpkgs.config.allowUnfree = true;

    # ---------------------------------------------------------
    # Boot & Kernel
    # ---------------------------------------------------------
    boot.loader.efi.canTouchEfiVariables = true;

    boot.loader.systemd-boot = {
      enable = true;
      configurationLimit = 10;
      consoleMode = "max";
    };

    boot.kernelPackages = lib.mkDefault pkgs.linuxPackages_latest;

    boot.initrd.systemd.enable = true;

    boot.tmp = {
      useTmpfs = true;
      tmpfsHugeMemoryPages = "within_size";
    };

    # ---------------------------------------------------------
    # Memory Management
    # ---------------------------------------------------------
    zramSwap.enable = true;

    # ---------------------------------------------------------
    # Hardware, Firmware & Graphics
    # ---------------------------------------------------------
    hardware.enableRedistributableFirmware = true;
    hardware.graphics.enable = true;

    # ---------------------------------------------------------
    # Localization
    # ---------------------------------------------------------
    time.timeZone = cfg.timeZone;

    i18n = {
      defaultLocale = cfg.defaultLocale;
      extraLocales = [
        "${cfg.defaultLocale}/UTF-8"
        "${cfg.extraLocale}/UTF-8"
      ];

      extraLocaleSettings = {
        LC_MESSAGES = cfg.defaultLocale;
        LC_ADDRESS = cfg.extraLocale;
        LC_IDENTIFICATION = cfg.extraLocale;
        LC_MEASUREMENT = cfg.extraLocale;
        LC_MONETARY = cfg.extraLocale;
        LC_NAME = cfg.extraLocale;
        LC_NUMERIC = cfg.extraLocale;
        LC_PAPER = cfg.extraLocale;
        LC_TELEPHONE = cfg.extraLocale;
        LC_TIME = cfg.extraLocale;
      };
    };

    console = {
      keyMap = cfg.consoleKeyMap;
      packages = [ pkgs.terminus_font ];
      font = "${pkgs.terminus_font}/share/consolefonts/ter-v24b.psf.gz";
    };

    services.xserver.xkb = {
      layout = cfg.xkbLayout;
      variant = "";
    };

    # ---------------------------------------------------------
    # System Features
    # ---------------------------------------------------------
    nix.settings.experimental-features = [
      "nix-command"
      "flakes"
    ];

    systemd.enableStrictShellChecks = true;
  };
}
