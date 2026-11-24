#!/usr/bin/env bash
# The change-request check (board setup --checks): the agent suites `nix flake check` runs, plus the console mod's check.
# Contract (change-requests.md Settings): one `<file> <code>` line per failing suite on stdout, exit 1 when any failed;
# a suite that cannot start (126, 127) is a broken check and exits 2. Each failure's tail goes to stderr.
# The suites are independent, so they run in parallel: the check takes as long as its slowest suite.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT

suites=(
  "home/patrick/agents/bin/test-agent-configs.py|python3 -B home/patrick/agents/bin/test-agent-configs.py"
  "home/patrick/agents/bin/test-scratch.py|python3 -B home/patrick/agents/bin/test-scratch.py"
  "home/patrick/agents/claude/mods/console/tests/check.sh|sh home/patrick/agents/claude/mods/console/tests/check.sh"
)

pids=()
for i in "${!suites[@]}"; do
  command=${suites[$i]#*|}
  (eval "$command" </dev/null >"$dir/$i.out" 2>&1; echo $? >"$dir/$i.status") &
  pids+=($!)
done
wait "${pids[@]}"

failed=0
for i in "${!suites[@]}"; do
  file=${suites[$i]%%|*}
  # A suite killed before it wrote its status fails, as a killed serial suite did.
  read -r status <"$dir/$i.status" 2>/dev/null || status=137
  if [[ $status -eq 126 || $status -eq 127 ]]; then
    echo "board-checks: cannot run $file (exit $status)" >&2
    cat "$dir/$i.out" >&2
    exit 2
  fi
  if [[ $status -ne 0 ]]; then
    echo "$file failed"
    tail -n 30 "$dir/$i.out" >&2
    failed=1
  fi
done
exit "$failed"
