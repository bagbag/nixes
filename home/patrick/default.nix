{
  config,
  lib,
  pkgs,
  ...
}:
{
  imports = [
    ./agents.nix
    ./awscli.nix
    ./vscode.nix
  ];

  home = {
    sessionPath = [ "${config.home.homeDirectory}/.local/share/pnpm/bin" ];
    file.".config/pnpm/config.yaml".text = ''
      minimumReleaseAge: 2880
      trustPolicy: no-downgrade
      pmOnFail: warn
    '';
  };

  programs = {
    npm = {
      enable = true;
      package = pkgs.nodejs_26;
      settings = {
        min-release-age = 2;
        "@tstdl:registry" = "https://forge.cloudful.de/api/packages/patrick/npm/";
      };
    };
    ssh = {
      enable = true;
      enableDefaultConfig = false;
      settings = {
        "Host *" = {
          HashKnownHosts = false;
          ControlMaster = "auto";
          ControlPath = "~/.ssh/control-master-%r@%h:%p";
          ControlPersist = "30";
        };
        "Host nl01" = {
          HostName = "10.98.0.100";
          User = "root";
          ProxyJump = "root@pve01.nightlines.eu";
        };
        "Host s01.k-fin.de" = {
          HostName = "10.38.7.100";
          User = "root";
          ProxyJump = "root@pve02.cloud.kledig.de";
        };
        "Host s01.cloud.kledig.de" = {
          HostName = "10.38.7.101";
          User = "root";
          ProxyJump = "root@pve02.cloud.kledig.de";
        };
        "Host gateway01.nightlines.eu" = {
          HostName = "217.160.18.89";
          User = "root";
        };
      };
    };
    git = {
      enable = true;
      package = pkgs.gitFull;
      settings = {
        user.name = "Patrick Hein";
        user.email = "bagbag98@googlemail.com";
        credential.helper =
          if pkgs.stdenv.isDarwin then
            "osxkeychain"
          else
            "${config.programs.git.package}/bin/git-credential-libsecret";
      };
    };

    zsh.shellAliases.claude-full = "CLAUDE_CODE_AUTO_COMPACT_WINDOW=900000 claude";

    nushell.extraConfig = ''
      def --wrapped claude-full [...args] {
        with-env { CLAUDE_CODE_AUTO_COMPACT_WINDOW: "900000" } { claude ...$args }
      }
    '';
  };

  dconf.settings = lib.mkIf pkgs.stdenv.isLinux {
    "org/gnome/TextEditor" = {
      restore-session = true;
      show-line-numbers = true;
      highlight-current-line = true;
    };
    "org/gnome/settings-daemon/plugins/power" = {
      sleep-inactive-ac-type = "nothing";
      power-button-action = "interactive";
    };
    "org/gnome/mutter" = {
      center-new-windows = true;
      dynamic-workspaces = true;
      attach-modal-dialogs = false;
      experimental-features = [ "scale-monitor-framebuffer" ];
    };
    "org/gnome/shell" = {
      disable-user-extensions = false;
      enabled-extensions = with pkgs.gnomeExtensions; [
        appindicator.extensionUuid
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
    "org/gnome/desktop/background" = {
      picture-uri = "file:///run/current-system/sw/share/backgrounds/gnome/blobs-l.svg";
      picture-uri-dark = "file:///run/current-system/sw/share/backgrounds/gnome/blobs-d.svg";
      primary-color = "#241f31";
    };
    "org/gnome/desktop/screensaver" = {
      picture-uri = "file:///run/current-system/sw/share/backgrounds/gnome/blobs-l.svg";
      primary-color = "#241f31";
    };
    "org/gnome/settings-daemon/plugins/media-keys".custom-keybindings = [
      "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal/"
    ];
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
}
