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
      font-family = "FiraCode Nerd Font Mono";
      font-size = 12;
      font-thicken = true;
      font-thicken-strength = 128;
      theme = "Atom One Dark";
      window-padding-x = 4;
      window-padding-y = 4;
      mouse-hide-while-typing = true;
      scrollback-limit = 100000000;
      macos-titlebar-style = "tabs";
      background-opacity = 0.95;
      background-blur = true;
      shell-integration-features = [
        "ssh-env"
        "ssh-terminfo"
      ];
    }
    // lib.optionalAttrs pkgs.stdenv.isDarwin {
      # Launch via a login zsh so nix-darwin's PATH hooks (/etc/zshenv ->
      # path_helper, per-user profile) populate the environment. The exec
      # into nushell is handled by zsh's profileExtra below, gated on a
      # real interactive TTY so non-interactive callers stay in zsh.
      command = "/bin/zsh -l";

      # Left Option behaves as Alt so meta+<key> bindings reach TUIs (e.g.
      # cmd+p in Claude Code). Right Option keeps native macOS composition
      # for typing `@`, `|`, `~`, `{}`, etc. on a German layout.
      macos-option-as-alt = "left";

      # Quit Ghostty (and remove its Dock icon) when the last window is
      # closed, instead of macOS's default of leaving the process alive.
      quit-after-last-window-closed = true;
    }
    // lib.optionalAttrs pkgs.stdenv.isLinux {
      # Explicitly launch via a login zsh so /etc/set-environment is sourced
      # (giving npm, etc. their correct config), then exec into nushell.
      # Without this, Ghostty uses $SHELL which may point to a stale path.
      command = "${pkgs.zsh}/bin/zsh --login";

      # Force single-instance mode OFF so each launch spawns a fully
      # independent process. When launched from a GNOME custom keybinding
      # (no TERM_PROGRAM, no CLI args), Ghostty's heuristic enables GTK
      # single-instance mode and routes the new window over D-Bus to the
      # existing instance. On 1.3.x that GNOME + D-Bus activation path is
      # racy (~1 in 9 launches), producing an empty, non-rendering window.
      # See ghostty-org/ghostty discussion #11724 and issue #10219.
      gtk-single-instance = false;
    };
  };

  # ---------------------------------------------------------
  # Shell Integration Defaults
  # ---------------------------------------------------------
  home.shell.enableNushellIntegration = true;

  # ---------------------------------------------------------
  # Nushell
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

    extraEnv = ''
      if ($env.GHOSTTY_RESOURCES_DIR? | is-not-empty) {
        $env.NU_VENDOR_AUTOLOAD_DIRS = (
          $env.NU_VENDOR_AUTOLOAD_DIRS?
            | default []
            | prepend ($env.GHOSTTY_RESOURCES_DIR | path join "shell-integration/nushell/vendor/autoload")
        )
      }
    '';

    extraConfig = ''
      # Lean (350k) is the settings.json default; claude-full raises the
      # compaction window for long supervisor arcs (see zsh alias of the same
      # name). Nushell aliases can't carry env prefixes, hence def --wrapped.
      def --wrapped claude-full [...args] {
        with-env { CLAUDE_CODE_AUTO_COMPACT_WINDOW: "900000" } { claude ...$args }
      }

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
      # Each entry can declare:
      #   modern   — the external tool replacement (e.g. rg for grep)
      #   nu       — the nushell-native way (e.g. `... | where $it =~ ...`)
      #   nuOwns   — when nu's own builtin transparently handles this form:
      #                "piped" → don't hint when used after a `|`
      #                "bare"  → don't hint when typed with no args
      # Display: show whichever of `modern` and `nu` are defined; both are
      # joined with `  |  `. The hint is suppressed entirely when `nuOwns`
      # matches the current context (i.e., nu's own builtin is doing the job).
      # Printed once before execution and once after, for visibility.
      def hints-for-command [line: string] {
        let hints = {
          # nu's builtin handles these natively in the marked context, but
          # we still want a hint when the user invokes the legacy form
          find:     { modern: "fd config.nu",                              nuOwns: "piped" }
          sort:     { nu: "... | sort  (or `sort-by col`)",                nuOwns: "piped" }
          uniq:     { nu: "... | uniq  (or `uniq-by col`)",                nuOwns: "piped" }
          ps:       { nu: "ps | where name =~ 'chromium'",                 nuOwns: "bare" }

          # Both alternatives available
          grep:     { modern: "rg TODO",                                   nu: "... | where $it =~ 'pattern'" }
          cat:      { modern: "bat shell.nix",                             nu: "open file  (structured) or `open --raw file`" }
          sed:      { modern: "sd 'old' 'new' file",                       nu: "... | str replace 'old' 'new'" }

          # nu-native only (no nice external replacement)
          awk:      {                                                      nu: "... | get col  (or `split column ','`)" }
          head:     {                                                      nu: "... | first 10" }
          tail:     {                                                      nu: "... | last 10" }
          wc:       {                                                      nu: "... | length  (rows) or `... | str length` (chars)" }
          cut:      {                                                      nu: "... | get col  or `... | split column ','`" }

          # External-only — no nu equivalent
          du:       { modern: "dust -d 2" }
          df:       { modern: "duf" }
          top:      { modern: "btop" }
          man:      { modern: "tldr tar" }
          time:     { modern: "hyperfine 'cmd a' 'cmd b'" }
          dig:      { modern: "doggo example.com" }
          nslookup: { modern: "doggo example.com MX" }
          diff:     { modern: "difft a.nix b.nix" }
          hexdump:  { modern: "hexyl file.bin" }
          xxd:      { modern: "hexyl file.bin" }
          tree:     { modern: "eza --tree --git-ignore" }
          ping:     { modern: "gping 1.1.1.1" }
          wget:     { modern: "curl <url>  (or nushell: `http get <url>`)" }
        }
        $line
          | str trim
          | split row '|'
          | enumerate
          | each {|it|
              let parts = ($it.item | str trim | split row ' ' | where {|w| $w != ''' })
              # Strip leading `^` (nu's force-external prefix) so `^find` etc. still match
              let cmd = ($parts | first | default ''' | str replace --regex '^\^' ''')
              let entry = ($hints | get --optional $cmd)
              if $entry == null {
                null
              } else {
                let isPiped = $it.index > 0
                let hasArgs = ($parts | length) > 1
                let nuOwns = ($entry | get --optional nuOwns | default ''')
                let skip = ($nuOwns == 'piped' and $isPiped) or ($nuOwns == 'bare' and (not $hasArgs))
                if $skip {
                  null
                } else {
                  let m = ($entry | get --optional modern)
                  let n = ($entry | get --optional nu)
                  let bits = ([
                    (if ($m != null) { $"modern: ($m)" } else { null })
                    (if ($n != null) { $"nu: ($n)" }     else { null })
                  ] | where {|b| $b != null })
                  if ($bits | is-empty) { null } else { $bits | str join '  |  ' }
                }
              }
            }
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
  # Zsh (login shell — sources /etc/set-environment, then execs nushell)
  # ---------------------------------------------------------
  programs.zsh = {
    enable = true;
    # Only upgrade to nushell when this is a real interactive TTY session
    # (Ghostty, console, `ssh -t`). For everything else — Claude Code's
    # $SHELL env-capture, `$SHELL -c "…"` from scripts, piped input — stay
    # in zsh so callers get POSIX semantics. /etc/set-environment has
    # already been sourced by this point, so the exec'd nushell inherits
    # the full system PATH (npm, etc.) the same as before.
    profileExtra = ''
      if [[ -o interactive && -t 0 && -t 1 ]]; then
        exec ${pkgs.nushell}/bin/nu --login
      fi
    '';
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

      # Lean (350k) is the settings.json default for every session. claude-full
      # raises the compaction window for long interactive supervisor arcs —
      # the one case that wants deep context (900k = 10% buffer below 1M).
      claude-full = "CLAUDE_CODE_AUTO_COMPACT_WINDOW=900000 claude";

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
    # Ctrl-R is owned by atuin (see programs.atuin below); disable fzf's
    # conflicting binding explicitly rather than relying on load order.
    historyWidget.command = "";
  };

  # ---------------------------------------------------------
  # External-command completions (git, docker, cargo, ...)
  # ---------------------------------------------------------
  # Nushell has no built-in completions for external CLIs. Carapace ships
  # completions for ~1000 tools and registers itself as nushell's external
  # completer.
  programs.carapace = {
    enable = true;
    enableNushellIntegration = true;
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
