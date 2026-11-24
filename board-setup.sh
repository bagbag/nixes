#!/usr/bin/env bash
# The board's setup step provisions every prerequisite used by the checks: the console's types, and the tests' dev shell.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
console="$repo/home/patrick/agents/claude/mods/console"
types="$console/.claude-plugin/types"

command -v claude >/dev/null || { echo 'board-setup: claude is required to generate console types' >&2; exit 1; }
command -v tsc >/dev/null || { echo 'board-setup: tsc is required to check the console' >&2; exit 1; }
command -v nix >/dev/null || { echo 'board-setup: nix is required for the agent tests (pytest, pytest-xdist)' >&2; exit 1; }
command -v timeout >/dev/null || { echo 'board-setup: timeout is required to bound Claude type generation' >&2; exit 1; }

nix develop "$repo#agent-tests" --command python3 -c 'import pytest, xdist' ||
  { echo 'board-setup: the agent-tests dev shell (pytest, pytest-xdist) did not build' >&2; exit 1; }

tmp=$(mktemp -d "$console/.claude-plugin/.setup.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
stub="$tmp/stub"

# The empty hook module triggers Claude Code's watched declaration generation
# without loading the console's session hooks or writing user configuration.
mkdir -p "$stub/.claude-plugin" "$stub/hooks"
cat > "$stub/.claude-plugin/plugin.json" <<'EOF'
{"name":"console-types"}
EOF
cat > "$stub/hooks/hooks.json" <<'EOF'
{"modules":["./register.tsx"]}
EOF
cat > "$stub/hooks/register.tsx" <<'EOF'
export const register = () => {}
EOF

if ! (cd "$stub" && timeout 45 env -u CLAUDE_CODE_PLUGIN_DIRS \
  CLAUDE_CODE_PLUGIN_DIR_WATCH=1 claude -p --setting-sources project \
  --no-session-persistence --plugin-dir "$stub" /cost >/dev/null); then
  echo 'board-setup: Claude type generation failed or exceeded 45 seconds' >&2
  exit 1
fi

generated="$stub/.claude-plugin/types"
for declaration in \
  claude-code/index.d.ts \
  claude-code-mcp/index.d.ts \
  claude-code-tools/index.d.ts \
  tsconfig.json; do
  if [[ ! -s "$generated/$declaration" ]]; then
    echo "board-setup: Claude did not generate .claude-plugin/types/$declaration" >&2
    exit 1
  fi
done
rm -rf "$types"
mv "$generated" "$types"
