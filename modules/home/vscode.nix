{ pkgs, ... }:
{
  programs.vscode = {
    enable = true;

    profiles.default = {
      extensions = with pkgs.vscode-marketplace; [
        # --- Formatters & Linters ---
        dbaeumer.vscode-eslint
        esbenp.prettier-vscode
        foxundermoon.shell-format
        redhat.vscode-xml
        redhat.vscode-yaml
        sibiraj-s.vscode-scss-formatter
        tyriar.sort-lines
        editorconfig.editorconfig

        # --- Languages & Frameworks ---
        angular.ng-template
        # denoland.vscode-deno
        vitest.explorer
        rust-lang.rust-analyzer
        svelte.svelte-vscode
        tamasfe.even-better-toml
        jnoortheen.nix-ide
        matthewpi.caddyfile-support

        # --- Data & CSV ---
        janisdd.vscode-edit-csv
        mechatroner.rainbow-csv
        ms-ossdata.vscode-pgsql

        # --- Git & Remote ---
        eamodio.gitlens
        github.vscode-pull-request-github
        github.remotehub
        ms-vsliveshare.vsliveshare

        # --- AI & Copilot ---
        github.copilot
        github.copilot-chat
        ms-vscode.copilot-mermaid-diagram
        google.gemini-cli-vscode-ide-companion

        # --- Debuggers ---
        firefox-devtools.vscode-firefox-debug
        probe-rs.probe-rs-debugger

        # --- UI & Themes ---
        vscode-icons-team.vscode-icons
        zhuangtongfa.material-theme
        kamikillerto.vscode-colorize

        # --- Utils ---
        adpyke.codesnap
        barbosshack.crates-io
        bbugh.change-color-format
        bierner.folder-source-actions
        bradlc.vscode-tailwindcss
        dorianmassoulier.repomix-runner
        ms-vscode.hexeditor
        wmaurer.change-case
      ];

      userSettings = {
        "codesnap.containerPadding" = "1em";
        "codesnap.showWindowControls" = false;
        "codesnap.shutterAction" = "copy";
        "css.lint.duplicateProperties" = "warning";
        "css.lint.float" = "warning";
        "css.lint.idSelector" = "warning";
        "css.lint.ieHack" = "warning";
        "css.lint.important" = "warning";
        "css.lint.universalSelector" = "warning";
        "diffEditor.codeLens" = true;
        "editor.cursorBlinking" = "smooth";
        "editor.cursorSmoothCaretAnimation" = "on";
        "editor.find.autoFindInSelection" = "multiline";
        "editor.fontFamily" = "Fira Code";
        "editor.fontLigatures" = "'ss02', 'ss03', 'ss04'";
        "editor.gotoLocation.multipleDeclarations" = "gotoAndPeek";
        "editor.gotoLocation.multipleDefinitions" = "gotoAndPeek";
        "editor.gotoLocation.multipleImplementations" = "gotoAndPeek";
        "editor.gotoLocation.multipleReferences" = "gotoAndPeek";
        "editor.gotoLocation.multipleTypeDefinitions" = "gotoAndPeek";
        "editor.linkedEditing" = true;
        "editor.minimap.showSlider" = "always";
        "editor.renderWhitespace" = "trailing";
        "editor.smoothScrolling" = true;
        "editor.suggest.localityBonus" = true;
        "editor.suggest.matchOnWordStartOnly" = false;
        "editor.suggest.preview" = true;
        "editor.tabSize" = 2;
        "eslint.codeAction.disableRuleComment" = {
          "location" = "sameLine";
        };
        "eslint.lintTask.enable" = true;
        "eslint.onIgnoredFiles" = "warn";
        "explorer.fileNesting.enabled" = true;
        "files.insertFinalNewline" = true;
        "files.trimFinalNewlines" = true;
        "git.confirmSync" = false;
        "gitlens.hovers.currentLine.over" = "line";
        "html.format.maxPreserveNewLines" = 2;
        "html.format.wrapAttributes" = "preserve-aligned";
        "html.format.wrapLineLength" = 0;
        "javascript.inlayHints.parameterNames.enabled" = "all";
        "javascript.inlayHints.variableTypes.enabled" = true;
        "javascript.preferences.quoteStyle" = "single";
        "javascript.referencesCodeLens.enabled" = true;
        "javascript.referencesCodeLens.showOnAllFunctions" = true;
        "javascript.suggest.completeFunctionCalls" = true;
        "prettier.printWidth" = 999;
        "scm.defaultViewMode" = "tree";
        "scss.lint.duplicateProperties" = "warning";
        "scss.lint.float" = "warning";
        "scss.lint.idSelector" = "warning";
        "scss.lint.ieHack" = "warning";
        "scss.lint.important" = "warning";
        "scss.lint.universalSelector" = "warning";
        "scssFormatter.printWidth" = 999;
        "tailwindCSS.emmetCompletions" = true;
        "tailwindCSS.lint.cssConflict" = "error";
        "terminal.integrated.confirmOnExit" = "hasChildProcesses";
        "terminal.integrated.cursorBlinking" = true;
        "terminal.integrated.defaultProfile.windows" = "NixOS (WSL)";
        "terminal.integrated.persistentSessionReviveProcess" = "onExitAndWindowClose";
        "terminal.integrated.scrollback" = 10000;
        "terminal.integrated.splitCwd" = "workspaceRoot";
        "typescript.implementationsCodeLens.enabled" = true;
        "typescript.implementationsCodeLens.showOnInterfaceMethods" = true;
        "typescript.preferences.includePackageJsonAutoImports" = "on";
        "typescript.preferences.preferTypeOnlyAutoImports" = true;
        "typescript.preferences.quoteStyle" = "single";
        "typescript.referencesCodeLens.enabled" = true;
        "typescript.tsserver.experimental.enableProjectDiagnostics" = true;
        "vsicons.presets.angular" = true;
        "window.dialogStyle" = "custom";
        "workbench.colorTheme" = "One Dark Pro Mix";
        "workbench.editor.limit.enabled" = true;
        "workbench.editor.wrapTabs" = true;
        "workbench.iconTheme" = "vscode-icons";
        "workbench.list.smoothScrolling" = true;
        "tailwindCSS.includeLanguages" = {
          "javascript" = "javascript";
          "javascriptreact" = "javascriptreact";
          "typescript" = "typescript";
          "typescriptreact" = "typescriptreact";
        };
        "[css]" = {
          "editor.defaultFormatter" = "sibiraj-s.vscode-scss-formatter";
        };
        "[handlebars]" = {
          "editor.defaultFormatter" = "vscode.html-language-features";
        };
        "[html]" = {
          "editor.defaultFormatter" = "esbenp.prettier-vscode";
        };
        "[javascript]" = {
          "editor.defaultFormatter" = "vscode.typescript-language-features";
        };
        "[json]" = {
          "editor.defaultFormatter" = "vscode.json-language-features";
        };
        "[jsonc]" = {
          "editor.defaultFormatter" = "vscode.json-language-features";
        };
        "[scss]" = {
          "editor.defaultFormatter" = "esbenp.prettier-vscode";
        };
        "[typescript]" = {
          "editor.defaultFormatter" = "vscode.typescript-language-features";
        };
        "[typescriptreact]" = {
          "editor.defaultFormatter" = "vscode.typescript-language-features";
        };
        "[yaml]" = {
          "editor.defaultFormatter" = "redhat.vscode-yaml";
          "diffEditor.ignoreTrimWhitespace" = true;
        };
        "prettier.prettierPath" = "/home/patrick/.node_modules/lib/node_modules/prettier";
        "rust-analyzer.diagnostics.styleLints.enable" = true;
        "rust-analyzer.hover.actions.references.enable" = true;
        "editor.inlayHints.enabled" = "offUnlessPressed";
        "editor.inlayHints.maximumLength" = 0;
        "rust-analyzer.inlayHints.maxLength" = null;
        "gitlens.views.scm.grouped.views" = {
          "commits" = true;
          "branches" = true;
          "remotes" = true;
          "stashes" = true;
          "tags" = true;
          "worktrees" = true;
          "contributors" = true;
          "repositories" = false;
          "searchAndCompare" = true;
          "launchpad" = false;
        };
        "rust-analyzer.check.command" = "clippy";
        "tailwindCSS.classFunctions" = [
          "class"
        ];
        "github.copilot.enable" = {
          "*" = true;
          "plaintext" = false;
          "markdown" = true;
          "scminput" = false;
        };
        "repomix.output.filePath" = "";
        "repomix.output.copyToClipboard" = false;
        "[markdown]" = {
          "editor.defaultFormatter" = "esbenp.prettier-vscode";
        };
        "workbench.experimental.share.enabled" = true;
        "repomix.output.style" = "markdown";
        "svelte.enable-ts-plugin" = true;
        "[svelte]" = {
          "editor.defaultFormatter" = "svelte.svelte-vscode";
        };
        "[dockercompose]" = {
          "editor.insertSpaces" = true;
          "editor.tabSize" = 2;
          "editor.autoIndent" = "advanced";
          "editor.quickSuggestions" = {
            "other" = true;
            "comments" = false;
            "strings" = true;
          };
          "editor.defaultFormatter" = "redhat.vscode-yaml";
        };
        "[github-actions-workflow]" = {
          "editor.defaultFormatter" = "redhat.vscode-yaml";
        };
        "inlineChat.enableV2" = true;
        "chat.customAgentInSubagent.enabled" = true;
        "files.trimTrailingWhitespace" = true;
        "files.defaultLanguage" = "\${activeEditorLanguage}";
        "editor.quickSuggestions" = {
          "comments" = "on";
          "strings" = "on";
        };
        "editor.guides.bracketPairs" = "active";
      };
    };
  };
}
