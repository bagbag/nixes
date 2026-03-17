{
  pkgs,
  lib,
  ...
}:
{
  # ---------------------------------------------------------
  # Terminal Configuration
  # ---------------------------------------------------------

  programs.ghostty = {
    enable = true;
    package = if pkgs.stdenv.isLinux then pkgs.ghostty else null;
    enableBashIntegration = true;
    enableZshIntegration = true;

    settings = {
      window-width = 165;
      window-height = 40;
      font-family = "Noto Sans Mono";
      font-size = 12;
      window-padding-x = 4;
      window-padding-y = 4;
      mouse-hide-while-typing = true;
      scrollback-limit = 100000000;
      shell-integration-features = [
        "ssh-env"
        "ssh-terminfo"
      ];
    };
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
      WORDCHARS=''${WORDCHARS//[-.\/=]/}

      setopt autocd extendedglob nomatch

      # Load the functions from Zsh's library
      autoload -U up-line-or-beginning-search
      autoload -U down-line-or-beginning-search

      # Register them as widgets so 'bindkey' can see them
      zle -N up-line-or-beginning-search
      zle -N down-line-or-beginning-search

      # Better word navigation
      bindkey "^[[1;5C" forward-word
      bindkey "^[[1;5D" backward-word

      # Better history navigation
      bindkey "^[[A" up-line-or-beginning-search
      bindkey "^[[B" down-line-or-beginning-search
    '';

    shellAliases = {
      ls = "eza --smart-group --icons";
      la = "eza --smart-group -a --icons";
      ll = "eza --smart-group -l --icons";
      cat = "bat";
      grep = "grep --color=auto";

      # Navigation
      ".." = "cd ..";
      "..." = "cd ../..";
      "...." = "cd ../../..";
    };

    history = {
      size = 100000;
      path = "$HOME/.zsh_history";
    };
  };

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
  };

  programs.nix-index.enable = true;
  programs.nix-index-database.comma.enable = true;
  programs.starship.enable = true;
  programs.zoxide.enable = true;

  home.packages = with pkgs; [
    # Modern Coreutils
    bat
    eza
    fd
    ripgrep

    # Utilities
    tealdeer
    tmux
  ];
}
