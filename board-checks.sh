#!/usr/bin/env bash
# The change-request check (board setup --checks): the agent suites `nix flake check` runs, plus the console mod's check.
# Contract (change-requests.md Settings): one `<file> <code>` line per failing suite on stdout, exit 1 when any failed;
# a suite that cannot start (126, 127) is a broken check and exits 2. Each failure's tail goes to stderr.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
out=$(mktemp)
trap 'rm -f "$out"' EXIT
failed=0

run() {
  local file=$1 status
  shift
  "$@" </dev/null >"$out" 2>&1
  status=$?
  if [[ $status -eq 126 || $status -eq 127 ]]; then
    echo "board-checks: cannot run $file (exit $status)" >&2
    cat "$out" >&2
    exit 2
  fi
  if [[ $status -ne 0 ]]; then
    echo "$file failed"
    tail -n 30 "$out" >&2
    failed=1
  fi
}

run home/patrick/agents/bin/test-agent-configs.py python3 -B home/patrick/agents/bin/test-agent-configs.py
run home/patrick/agents/bin/test-scratch.py python3 -B home/patrick/agents/bin/test-scratch.py
run home/patrick/agents/claude/mods/console/tests/check.sh sh home/patrick/agents/claude/mods/console/tests/check.sh
exit "$failed"
