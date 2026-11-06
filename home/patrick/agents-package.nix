# The agent config's build, shared by this machine's home-manager (agents.nix) and the bundle for
# people without this nix config (modules/flake-parts/agent-setup.nix, agents/setup/).
{
  runCommand,
  ps,
  git,
  jq,
  python3,
  version ? "local",
}:
let
  src = ./agents;

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
    "session-lead-mode"
    "board"
    "protocol"
    "protocol_engine"
    "worker-last-use"
    "round-report"
  ];

  artifacts =
    runCommand "agent-artifacts"
      {
        nativeBuildInputs = [
          # The build sandbox refuses the setuid /bin/ps; the registry liveness tests need a ps.
          ps
          # The protocol owner-path tests run git init and git check-ignore.
          git
          jq
          (python3.withPackages (p: [ p.pyyaml ]))
        ];
      }
      ''
        python3 ${src}/bin/test-agent-configs.py ${src}
        mkdir -p "$out/claude" "$out/codex" "$out/skills"
        python3 ${src}/bin/generate-agent-configs.py \
          --source ${src}/definitions \
          --target claude \
          --output "$out/claude"
        python3 ${src}/bin/generate-agent-configs.py \
          --source ${src}/definitions \
          --target codex \
          --output "$out/codex"
        python3 ${src}/bin/expand-skills.py \
          --source ${src}/skills \
          --output "$out/skills"
      '';

  # A tarball, since artifacts already ran the validator: a failing tree builds no bundle.
  setup = runCommand "agent-setup-${version}" { nativeBuildInputs = [ jq ]; } ''
    name=claude-codex-setup-${version}
    files=$name/files
    mkdir -p "$files/.claude/hooks" "$files/.claude/mods" "$files/.codex/hooks" "$files/.agents/bin" "$name/settings"

    cp ${src}/setup/install.sh ${src}/setup/README.md "$name/"
    echo ${version} > "$name/VERSION"
    jq '{hooks}' ${./claude/settings.json} > "$name/settings/claude-hooks.json"
    jq '{hooks}' ${./codex/hooks.json} > "$name/settings/codex-hooks.json"

    cp ${src}/AGENTS.md "$files/.claude/CLAUDE.md"
    cp ${src}/AGENTS.md "$files/.codex/AGENTS.md"
    cp -r ${artifacts}/skills "$files/.claude/skills"
    cp -r ${artifacts}/skills "$files/.agents/skills"
    cp -r ${artifacts}/claude "$files/.claude/agents"
    cp -r ${artifacts}/codex "$files/.codex/agents"
    for f in ${toString claudeHooks}; do cp ${src}/hooks/"$f" "$files/.claude/hooks/"; done
    for f in ${toString claudeOwnHooks}; do cp ${./claude/hooks}/"$f" "$files/.claude/hooks/"; done
    for f in ${toString codexHooks}; do cp ${src}/hooks/"$f" "$files/.codex/hooks/"; done
    for f in ${toString tools}; do cp -r ${src}/bin/"$f" "$files/.agents/bin/"; done
    cp -r ${src}/claude/mods/console "$files/.claude/mods/console"

    # Store copies are read-only, which would stick to the installed files.
    chmod -R u+w "$name"
    rm -rf "$files/.claude/mods/console/tests" "$files/.claude/mods/console/.claude-plugin/types"

    mkdir -p "$out"
    tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -czf "$out/$name.tar.gz" "$name"
  '';
in
{
  inherit
    artifacts
    setup
    claudeHooks
    claudeOwnHooks
    codexHooks
    tools
    ;
}
