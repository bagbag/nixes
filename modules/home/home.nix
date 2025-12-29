{
  inputs,
  lib,
  pkgs,
  config,
  ...
}:
{
  home.stateVersion = "25.11";

  imports = [
    ./vscode.nix
  ];

  home.sessionPath = [
    "${config.home.homeDirectory}/.node_modules/bin"
  ];

  # ---------------------------------------------------------
  # GNOME Desktop Configuration (Dconf)
  # ---------------------------------------------------------
  dconf.settings = {
    "org/gnome/settings-daemon/plugins/power" = {
      sleep-inactive-ac-type = "nothing";
      power-button-action = "interactive";
    };

    # Interface: Dark Theme & Clock
    "org/gnome/desktop/interface" = {
      color-scheme = "prefer-dark";
      clock-show-weekday = true;
      clock-show-seconds = true;
      show-battery-percentage = true;
      enable-hot-corners = false;
      font-name = "Noto Sans 12";
      monospace-font-name = "Noto Sans Mono 12";
    };

    # Window Management
    "org/gnome/mutter" = {
      center-new-windows = true;
      dynamic-workspaces = true;
      attach-modal-dialogs = false;
      experimental-features = [ "scale-monitor-framebuffer" ];
    };

    "org/gnome/desktop/wm/preferences" = {
      button-layout = "appmenu:minimize,maximize,close"; # Adds min/max buttons
    };

    # Shell: Dock Favorites
    "org/gnome/shell" = {
      disable-user-extensions = false;

      enabled-extensions = with pkgs.gnomeExtensions; [
        launch-new-instance.extensionUuid
        status-icons.extensionUuid
        uptime-kuma-indicator.extensionUuid
      ];

      favorite-apps = [
        "firefox-devedition.desktop"
        "org.gnome.Console.desktop"
        "org.gnome.Nautilus.desktop"
        "org.gnome.Settings.desktop"
      ];
    };

    # Text Editor
    "org/gnome/TextEditor" = {
      restore-session = true;
      show-line-numbers = true;
      highlight-current-line = true;
    };

    "org/gnome/desktop/background" = {
      picture-uri = "file:///run/current-system/sw/share/backgrounds/gnome/blobs-l.svg";
      picture-uri-dark = "file:///run/current-system/sw/share/backgrounds/gnome/blobs-d.svg";
      primary-color = "#241f31";
    };

    "org/gnome/desktop/screensaver" = {
      picture-uri = "file:///run/current-system/sw/share/backgrounds/gnome/blobs-l.svg";
      primary-color = "#241f31";
    };

    "org/gnome/desktop/input-sources" = {
      sources = [
        (lib.gvariant.mkTuple [
          "xkb"
          "de+nodeadkeys"
        ])
      ];
    };

    "org/gnome/settings-daemon/plugins/media-keys" = {
      custom-keybindings = [
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal/"
      ];
    };

    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal" = {
      name = "Terminal";
      binding = "<Shift><Alt>t";
      command = "ghostty";
    };

    "org/gnome/desktop/wm/keybindings" = {
      switch-applications = [ ];
      switch-applications-backward = [ ];
      switch-windows = [ "<Alt>Tab" ];
      switch-windows-backward = [ "<Shift><Alt>Tab" ];
    };

  };

  # ---------------------------------------------------------
  # User Packages
  # ---------------------------------------------------------
  home.packages = with pkgs; [
    # System Helpers
    nh
    nix-du
    nix-tree

    # Modern Coreutils
    bat
    eza
    fd
    ripgrep

    # Core Editors
    micro
    nano

    # Productivity Tools
    fzf
    tealdeer
    tmux

    # Utilities
    bind
    curl
    inetutils
    ipcalc
    tcpdump
    wget
    wl-clipboard-rs

    # System Monitoring
    btop
    htop
    iotop
    nmon

    # Miscellaneous
    git
    nixfmt-rfc-style
    code2prompt
    aria2

    # Gnome Extensions
    gnomeExtensions.launch-new-instance
    gnomeExtensions.status-icons
    gnomeExtensions.uptime-kuma-indicator
  ];

  home.sessionVariables = {
    EDITOR = "micro";
    NH_FLAKE = "/etc/nixos";
    NIXOS_OZONE_WL = "1";
  };

  # ---------------------------------------------------------
  # Terminal Configuration
  # ---------------------------------------------------------

  programs.ghostty = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
  };

  # ---------------------------------------------------------
  # Shell Configuration
  # ---------------------------------------------------------
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;

    initContent = ''
      WORDCHARS=''${WORDCHARS//[\/.-=]/}

      bindkey "^[[1;5C" forward-word
      bindkey "^[[1;5D" backward-word
    '';

    shellAliases = {
      ls = "eza --smart-group --icons";
      la = "eza --smart-group -a --icons";
      ll = "eza --smart-group -l --icons";
      cat = "bat";
      grep = "grep --color=auto";
    };

    history = {
      size = 100000;
      path = "$HOME/.zsh_history";
    };
  };

  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;

    matchBlocks = {
      "*" = {
        hashKnownHosts = false;
        controlMaster = "auto";
        controlPath = "~/.ssh/control-master-%r@%h:%p";
        controlPersist = "30";
      };

      "nl01" = {
        hostname = "10.98.0.100";
        user = "root";
        proxyJump = "root@pve01.nightlines.eu";
      };

      "s01.k-fin.de" = {
        hostname = "10.38.7.100";
        user = "root";
        proxyJump = "root@pve02.cloud.kledig.de";
      };

      "s01.cloud.kledig.de" = {
        hostname = "10.38.7.101";
        user = "root";
        proxyJump = "root@pve02.cloud.kledig.de";
      };

      "gateway01.nightlines.eu" = {
        hostname = "217.160.18.89";
        user = "root";
      };
    };
  };

  # ---------------------------------------------------------
  # Program Modules
  # ---------------------------------------------------------
  programs.home-manager.enable = true;
  programs.nix-index.enable = true;
  programs.nix-index-database.comma.enable = true;
  programs.starship.enable = true;
  programs.zoxide.enable = true;

  programs.git = {
    enable = true;
    settings = {
      user.name = "Patrick Hein";
      user.email = "bagbag98@googlemail.com";
      init.defaultBranch = "main";
    };
  };

  programs.chromium = {
    enable = true;
    package = pkgs.ungoogled-chromium;

    extensions = [
      { id = "cjpalhdlnbpafiamejdnhcphjbkeiagm"; } # uBlock Origin
      { id = "pkehgijcmpdhfbdbbnkijodmdjhbjlgp"; } # Privacy Badger
    ];
  };

  programs.mpv = {
    enable = true;

    package = (
      pkgs.mpv-unwrapped.wrapper {
        scripts = with pkgs.mpvScripts; [
          uosc
        ];

        mpv = pkgs.mpv-unwrapped.override {
          waylandSupport = true;
        };
      }
    );

    config = {
      profile = "high-quality";
      ytdl-format = "bestvideo+bestaudio";
    };
  };
}
