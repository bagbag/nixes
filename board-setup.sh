#!/usr/bin/env bash
# The board's setup step provisions every prerequisite used by the console check.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
console="$repo/home/patrick/agents/claude/mods/console"
types="$console/.claude-plugin/types"
typescript_version=6.0.3
tmp=$(mktemp -d "$console/.claude-plugin/.setup.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
stage="$tmp/types"
stub="$tmp/stub"
cache="$tmp/npm-cache"

command -v claude >/dev/null || { echo 'board-setup: claude is required to generate console types' >&2; exit 1; }
command -v npm >/dev/null || { echo 'board-setup: npm is required to provision TypeScript' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'board-setup: python3 is required to bound the Claude probe' >&2; exit 1; }

# The empty hook module triggers Claude Code's watched declaration generation
# without loading the console's session hooks or writing user configuration.
mkdir -p "$stage" "$stub/.claude-plugin" "$stub/hooks"
cat > "$stub/.claude-plugin/plugin.json" <<'EOF'
{"name":"console-types"}
EOF
cat > "$stub/hooks/hooks.json" <<'EOF'
{"modules":["./register.tsx"]}
EOF
cat > "$stub/hooks/register.tsx" <<'EOF'
export const register = () => {}
EOF

python3 - "$stub" <<'PY'
import subprocess
import sys

stub = sys.argv[1]
cmd = [
    "env", "-u", "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CODE_PLUGIN_DIR_WATCH=1",
    "claude", "-p", "--setting-sources", "project", "--no-session-persistence",
    "--plugin-dir", stub, "/cost",
]
try:
    subprocess.run(cmd, cwd=stub, check=True, timeout=45)
except subprocess.TimeoutExpired as error:
    print("board-setup: Claude type generation exceeded 45 seconds", file=sys.stderr)
    raise SystemExit(1) from error
except subprocess.CalledProcessError as error:
    print(f"board-setup: Claude type generation exited {error.returncode}", file=sys.stderr)
    raise SystemExit(1) from error
PY

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
cp -R "$generated/." "$stage/"

# Reuse this checkout's verified installation on repeated setup runs. A cold
# checkout installs the exact version; checks themselves never contact npm.
if [[ -x "$types/node_modules/.bin/tsc" ]] && \
  [[ "$("$types/node_modules/.bin/tsc" --version 2>/dev/null || true)" == "Version $typescript_version" ]]; then
  if ! tarball=$(npm pack --silent --ignore-scripts --cache "$cache" \
    --pack-destination "$tmp" "$types/node_modules/typescript"); then
    echo "board-setup: could not package the existing TypeScript $typescript_version install" >&2
    exit 1
  fi
  if ! npm install --prefix "$stage" --cache "$cache" --no-save \
    --package-lock=false --ignore-scripts --no-audit --no-fund --offline "$tmp/$tarball"; then
    echo "board-setup: could not reuse the existing TypeScript $typescript_version install" >&2
    exit 1
  fi
else
  if ! npm install --prefix "$stage" --cache "$cache" --no-save \
    --package-lock=false --ignore-scripts --no-audit --no-fund --fetch-retries=0 \
    --fetch-timeout=30000 "typescript@$typescript_version"; then
    echo "board-setup: could not provision pinned TypeScript $typescript_version" >&2
    exit 1
  fi
fi
if [[ ! -x "$stage/node_modules/.bin/tsc" ]]; then
  echo 'board-setup: npm completed without installing the TypeScript compiler' >&2
  exit 1
fi
if [[ "$("$stage/node_modules/.bin/tsc" --version 2>/dev/null || true)" != "Version $typescript_version" ]]; then
  echo "board-setup: installed compiler does not report TypeScript $typescript_version" >&2
  exit 1
fi

rm -rf "$types"
mv "$stage" "$types"
