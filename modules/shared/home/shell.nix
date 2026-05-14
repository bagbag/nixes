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
  # Shell Integration Defaults
  # ---------------------------------------------------------
  home.shell.enableNushellIntegration = true;

  # ---------------------------------------------------------
  # Nushell (login shell)
  # ---------------------------------------------------------
  programs.nushell = {
    enable = true;

    shellAliases = {
      cat = "bat";
      lg = "lazygit";
    };

    environmentVariables = {
      EDITOR = "micro";
    };

    extraConfig = ''
      $env.config = ($env.config? | default {} | merge {
        show_banner: false
        edit_mode: emacs
        footer_mode: "auto"
        history: {
          max_size: 100000
          file_format: "sqlite"
          isolation: false
        }
        completions: {
          case_sensitive: false
          quick: true
          partial: true
          algorithm: "fuzzy"
        }
        cursor_shape: {
          emacs: line
        }
        table: {
          trim: {
            methodology: "wrapping"
            wrapping_try_keep_words: true
          }
        }
      })

      # Hint legacy commands toward modern alternatives.
      # Triggers when the command is the first word on the line — so the
      # nushell `find` filter used in pipelines (`ls | find ...`) is unaffected.
      # Printed once before execution and once after, for visibility.
      def hints-for-command [line: string] {
        let hints = {
          find: "fd — friendlier syntax, .gitignore-aware. example: `fd config.nu`"
          grep: "rg — recursive by default. in pipes use nu: `... | where $it =~ TODO`"
          cat: "bat — syntax-highlighted cat. example: `bat shell.nix`"
          du: "dust — visual disk usage tree. example: `dust -d 2`"
          df: "duf — colorful disk free overview. example: `duf`"
          ps: "use nushell builtin: `ps | where name =~ chromium`"
          top: "btop — richer process viewer. example: `btop`"
          sed: "sd 'old' 'new' file. in pipes use nu: `... | str replace 'old' 'new'`"
          awk: "use nushell pipelines: `... | get col | uniq`"
          man: "tldr — practical examples. example: `tldr tar`"
          time: "hyperfine — proper benchmarking. example: `hyperfine 'cmd a' 'cmd b'`"
          dig: "doggo — readable DNS lookups. example: `doggo example.com`"
          nslookup: "doggo — readable DNS lookups. example: `doggo example.com MX`"
          diff: "difft — syntax-aware diff. example: `difft a.nix b.nix`"
          hexdump: "hexyl — colorful hex viewer. example: `hexyl file.bin`"
          xxd: "hexyl — colorful hex viewer. example: `hexyl file.bin`"
          tree: "use eza: `eza --tree --git-ignore`"
          ping: "gping — live latency graph. example: `gping 1.1.1.1`"
          wget: "use curl or `http get <url>` (nushell builtin)"
          sort: "use nushell: `... | sort` or `sort-by col`"
          uniq: "use nushell: `... | uniq` or `uniq-by col`"
          head: "use nushell: `... | first 10` (also slices `... | range 0..9`)"
          tail: "use nushell: `... | last 10`"
          wc: "use nushell: `... | length` (rows) or `... | str length` (chars)"
          cut: "use nushell: `... | get col` or `... | split column ','`"
        }
        # Inspect first word of every pipeline segment, dedup hints, return list.
        $line
          | str trim
          | split row '|'
          | each { |seg| $seg | str trim | split row ' ' | first | default ''' | str replace '^' ''' }
          | each { |w| $hints | get --optional $w }
          | where {|h| $h != null }
          | uniq
      }

      $env.LAST_HINTS = []

      # Hooks must be defined as strings (not closures) so $env mutations
      # propagate between pre_execution and pre_prompt.
      $env.config.hooks.pre_execution = ($env.config.hooks.pre_execution? | default [] | append [
        '
          let hints = (hints-for-command (commandline))
          $env.LAST_HINTS = $hints
          for h in $hints {
            print --stderr $"\e[2m💡 ($h)\e[0m"
          }
        '
      ])

      $env.config.hooks.pre_prompt = ($env.config.hooks.pre_prompt? | default [] | append [
        '
          for h in ($env.LAST_HINTS? | default []) {
            print --stderr $"\e[2m💡 ($h)\e[0m"
          }
          $env.LAST_HINTS = []
        '
      ])

      # fzf keybindings (ctrl-r is owned by atuin)
      $env.config.keybindings = ($env.config.keybindings? | default [] | append [
        {
          name: fzf_insert_file
          modifier: control
          keycode: char_t
          mode: [emacs vi_normal vi_insert]
          event: {
            send: executehostcommand
            cmd: "commandline edit --insert (^fd --type f --hidden --exclude .git | ^fzf --height 40% --reverse --preview 'bat --style=numbers --color=always {}' | str trim)"
          }
        }
        {
          name: fzf_cd
          modifier: alt
          keycode: char_c
          mode: [emacs vi_normal vi_insert]
          event: {
            send: executehostcommand
            cmd: "let dir = (^fd --type d --hidden --exclude .git | ^fzf --height 40% --reverse | str trim); if ($dir | is-not-empty) { cd $dir }"
          }
        }
      ])
    '';
  };

  # ---------------------------------------------------------
  # Zsh (fallback / non-login interactive)
  # ---------------------------------------------------------
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;

    initContent = ''
      WORDCHARS=''${WORDCHARS//[-.\/=]/}

      setopt autocd extendedglob nomatch

      autoload -U up-line-or-beginning-search
      autoload -U down-line-or-beginning-search

      zle -N up-line-or-beginning-search
      zle -N down-line-or-beginning-search

      bindkey "^[[1;5C" forward-word
      bindkey "^[[1;5D" backward-word

      bindkey "^[[A" up-line-or-beginning-search
      bindkey "^[[B" down-line-or-beginning-search
    '';

    shellAliases = {
      cat = "bat";
      lg = "lazygit";
      grep = "grep --color=auto";

      ".." = "cd ..";
      "..." = "cd ../..";
      "...." = "cd ../../..";
    };

    history = {
      size = 100000;
      path = "$HOME/.zsh_history";
    };
  };

  # ---------------------------------------------------------
  # Modern Coreutils (managed by home-manager)
  # ---------------------------------------------------------
  programs.bat.enable = true;

  programs.eza = {
    enable = true;
    icons = "auto";
    git = true;
    extraOptions = [ "--smart-group" ];
  };

  programs.fd.enable = true;
  programs.ripgrep.enable = true;

  # ---------------------------------------------------------
  # Prompt & Navigation
  # ---------------------------------------------------------
  programs.starship.enable = true;
  programs.zoxide.enable = true;

  programs.fzf = {
    enable = true;
    enableZshIntegration = true;
  };

  # ---------------------------------------------------------
  # History (atuin, local-only)
  # ---------------------------------------------------------
  programs.atuin = {
    enable = true;
    enableZshIntegration = true;
    flags = [ "--disable-up-arrow" ];
    settings = {
      auto_sync = false;
      update_check = false;
      # Try "daemon-fuzzy" later: same fzf syntax, in-memory index (faster on
      # large histories), tunable frecency. Requires programs.atuin.daemon.enable.
      search_mode = "fuzzy";
      filter_mode = "global";
      style = "compact";
      inline_height = 20;
    };
  };

  # ---------------------------------------------------------
  # Git TUI
  # ---------------------------------------------------------
  programs.lazygit.enable = true;

  # ---------------------------------------------------------
  # Misc
  # ---------------------------------------------------------
  programs.nix-index.enable = true;
  programs.nix-index-database.comma.enable = true;

  home.packages = with pkgs; [
    # Development Tools
    oxlint
    oxfmt

    # Modern coreutils alternatives (hinted by pre_execution hook)
    dust # du
    duf # df
    sd # sed
    hyperfine # time benchmarking
    doggo # dig / nslookup
    difftastic # diff (provides `difft`)
    hexyl # hexdump / xxd
    procs # ps (also nushell builtin)
    gping # ping with graph

    # Utilities
    tealdeer
    tmux
  ];
}
