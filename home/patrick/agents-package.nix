# The agent config's build, shared by this machine's home-manager (agents.nix) and the bundle for
# people without this nix config (modules/flake-parts/agent-setup.nix, agents/setup/).
{
  lib,
  runCommand,
  ps,
  git,
  jq,
  python3,
  version ? "local",
}:
let
  src = ./agents;
  claudeSrc = ./claude;
  # The build's input: test-only files leave it, so editing them rebuilds nothing. The core check lives in
  # test-agent-configs.py, so that file stays.
  buildSrc = lib.fileset.toSource {
    root = ./agents;
    fileset = lib.fileset.difference ./agents (
      lib.fileset.unions [
        ./agents/bin/fixtures
        ./agents/bin/test-shared-board.py
        ./agents/bin/test-scratch.py
        ./agents/claude/mods/console/tests
      ]
    );
  };
  testInputs = [
    # The build sandbox refuses the setuid /bin/ps; the registry liveness tests need a ps.
    ps
    # The protocol owner-path tests run git init and git check-ignore.
    git
    jq
    python
  ];

  # The python every agents/bin script and test runs on: the build's, and the user's profile via agents.nix.
  python = python3.withPackages (p: [ p.pyyaml ]);

  # Hook scripts under agents/hooks, per tool, and Claude's own under claude/hooks.
  claudeHooks = [
    "compact-reorient.sh"
    "readonly-guard.sh"
    "git-stash-guard.sh"
    "bd-guard.sh"
    "session-register.sh"
    "session-activity.sh"
  ];
  claudeOwnHooks = [
    "context-watch.sh"
    "fable-guard.sh"
  ];
  codexHooks = [
    "compact-reorient.sh"
    "git-stash-guard.sh"
    "bd-guard.sh"
    "session-register.sh"
    "session-activity.sh"
  ];
  # Installed under ~/.agents/bin; the rest of agents/bin is build and test tooling. protocol_engine is the
  # package bin/protocol imports from beside itself.
  tools = [
    "session"
    "board"
    "protocol"
    "protocol_engine"
    "worker-last-use"
    "round-report"
    "scratch"
  ];

  # The full validator (behavior of board, protocol engine and hooks): `nix flake check`, or the dev-time gate
  # before staging; the switch builds artifacts only.
  checks = runCommand "agent-checks" { nativeBuildInputs = testInputs; } ''
    python3 ${src}/bin/test-agent-configs.py ${src}
    python3 ${src}/bin/test-scratch.py </dev/null
    touch "$out"
  '';

  artifacts =
    runCommand "agent-artifacts"
      {
        nativeBuildInputs = testInputs;
      }
      ''
        # What the build produces: skills, definitions, generators and rendered sizes.
        python3 ${buildSrc}/bin/test-agent-configs.py ${buildSrc} --group core
        mkdir -p "$out/claude" "$out/codex" "$out/skills"
        python3 ${buildSrc}/bin/generate-agent-configs.py \
          --source ${buildSrc}/definitions \
          --target claude \
          --output "$out/claude"
        python3 ${buildSrc}/bin/generate-agent-configs.py \
          --source ${buildSrc}/definitions \
          --target codex \
          --output "$out/codex"
        python3 ${buildSrc}/bin/expand-skills.py \
          --source ${buildSrc}/skills \
          --output "$out/skills"

        # What agents.nix links into the home, built from the tree the suite just passed.
        mkdir -p "$out/bin" "$out/hooks/claude" "$out/hooks/codex" "$out/mods"
        for f in ${toString tools}; do cp -r ${buildSrc}/bin/"$f" "$out/bin/"; done
        for f in ${toString claudeHooks}; do cp ${buildSrc}/hooks/"$f" "$out/hooks/claude/"; done
        for f in ${toString claudeOwnHooks}; do cp ${claudeSrc}/hooks/"$f" "$out/hooks/claude/"; done
        for f in ${toString codexHooks}; do cp ${buildSrc}/hooks/"$f" "$out/hooks/codex/"; done
        cp ${buildSrc}/AGENTS.md "$out/AGENTS.md"
        cp ${./codex/hooks.json} "$out/codex-hooks.json"
        cp -r ${buildSrc}/claude/mods/console "$out/mods/console"
        # Not part of an installed mod: tests, and the API types Claude lays into the working tree.
        chmod -R u+w "$out/mods" "$out/bin"
        rm -rf "$out/mods/console/tests" "$out/mods/console/.claude-plugin/types"
        find "$out/bin" -name __pycache__ -prune -exec rm -rf {} +
      '';

  # The tools as this machine links them: run on the python this generation keeps alive (home.packages), not on whatever
  # python3 a Dock-started session finds first. The bundle keeps the env shebang; install.py pins the user's python3.
  pinnedBin = runCommand "agent-bin" { } ''
    cp -r ${artifacts}/bin "$out"
    chmod -R u+w "$out"
    for f in "$out"/*; do
      if [ -f "$f" ] && [ "$(head -n1 "$f")" = "#!/usr/bin/env python3" ]; then
        sed -i '1s|.*|#!${python}/bin/python3|' "$f"
      fi
    done
  '';

  # A tarball, since artifacts already ran the validator: a failing tree builds no bundle.
  setup = runCommand "agent-setup-${version}" { nativeBuildInputs = [ jq ]; } ''
    name=claude-codex-setup-${version}
    files=$name/files
    mkdir -p "$files/.claude/hooks" "$files/.claude/mods" "$files/.codex/hooks" "$files/.agents/bin" "$name/settings"

    cp ${src}/setup/install.py ${src}/setup/README.md "$name/"
    echo ${version} > "$name/VERSION"
    jq '{hooks}' ${./claude/settings.json} > "$name/settings/claude-hooks.json"
    jq '{hooks}' ${./codex/hooks.json} > "$name/settings/codex-hooks.json"

    cp ${artifacts}/AGENTS.md "$files/.claude/CLAUDE.md"
    cp ${artifacts}/AGENTS.md "$files/.codex/AGENTS.md"
    cp -r ${artifacts}/skills "$files/.claude/skills"
    cp -r ${artifacts}/skills "$files/.agents/skills"
    cp -r ${artifacts}/claude "$files/.claude/agents"
    cp -r ${artifacts}/codex "$files/.codex/agents"
    cp ${artifacts}/hooks/claude/* "$files/.claude/hooks/"
    cp ${artifacts}/hooks/codex/* "$files/.codex/hooks/"
    cp -r ${artifacts}/bin/* "$files/.agents/bin/"
    # install.py pins each user's own python3, so the bundle's tools keep the env shebang.
    if head -qn1 "$files"/.agents/bin/* 2>/dev/null | grep -q '^#!/nix/store'; then
      echo "the bundle's tools point into the nix store" >&2
      exit 1
    fi
    cp -r ${artifacts}/mods/console "$files/.claude/mods/console"

    # Store copies are read-only, which would stick to the installed files.
    chmod -R u+w "$name"

    mkdir -p "$out"
    tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -czf "$out/$name.tar.gz" "$name"
  '';
in
{
  inherit
    python
    artifacts
    pinnedBin
    checks
    setup
    claudeHooks
    claudeOwnHooks
    codexHooks
    tools
    ;
}
