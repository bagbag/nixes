#!/usr/bin/env bash
# The change-request check (board setup --checks): the agent suites `nix flake check` runs, plus the shared-board suite and the console mod's check.
# The shared-board suite needs real bd and Dolt, which the nix sandbox lacks, so the gate is its one runner.
# Contract (change-requests.md Settings): one `<file> <code>` line per failing suite on stdout, exit 1 when any failed;
# a suite that cannot start (126, 127) is a broken check and exits 2. A failed suite's full output is kept in a file outside the run's folder,
# named on stderr (nixes-2aetg: a tail loses the failing test's name).
# The suites share no state, so they run in parallel; the agent configuration suite spreads its own tests over xdist workers
# (pytest and xdist come from the flake's agent-tests dev shell, which board-setup.sh checks).
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "${BASH_SOURCE[0]}")"
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT

suites=(
  "home/patrick/agents/bin/test-agent-configs.py|nix develop .#agent-tests --command python3 -B -m pytest -q -n auto home/patrick/agents/bin/test-agent-configs.py"
  "home/patrick/agents/bin/test-scratch.py|python3 -B home/patrick/agents/bin/test-scratch.py"
  # The default groups; --shared (sharing, sync), --migrate (board-migrate, stored forms) and --upgrade (a bd upgrade) run on request: see its docstring.
  "home/patrick/agents/bin/test-shared-board.py|python3 -B home/patrick/agents/bin/test-shared-board.py"
  "home/patrick/agents/claude/mods/console/tests/check.sh|sh home/patrick/agents/claude/mods/console/tests/check.sh"
)

# Background jobs of a non-interactive shell ignore SIGINT (POSIX 2.11), so each suite gets its own process group and an
# interrupt stops every group: SIGINT for the suites' own cleanup, SIGTERM after a grace for what ignores it.
set -m
pids=()
stop() {
  kill -INT -- "${pids[@]/#/-}" 2>/dev/null
  for _ in {1..20}; do
    alive=0
    for pid in "${pids[@]}"; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    ((alive)) || break
    sleep 0.25
  done
  kill -TERM -- "${pids[@]/#/-}" 2>/dev/null
  wait
  exit "$1"
}
trap 'stop 130' INT
trap 'stop 143' TERM
trap 'stop 129' HUP
for i in "${!suites[@]}"; do
  command=${suites[$i]#*|}
  (eval "$command" </dev/null >"$dir/$i.out" 2>&1; echo $? >"$dir/$i.status") &
  pids+=($!)
done
wait "${pids[@]}"

failed=0
for i in "${!suites[@]}"; do
  file=${suites[$i]%%|*}
  # A suite killed before writing its status counts as failed.
  read -r status <"$dir/$i.status" 2>/dev/null || status=137
  if [[ $status -eq 126 || $status -eq 127 ]]; then
    echo "board-checks: cannot run $file (exit $status)" >&2
    cat "$dir/$i.out" >&2
    exit 2
  fi
  if [[ $status -ne 0 ]]; then
    echo "$file failed"
    tmp=${TMPDIR:-/tmp}
    if kept=$(mktemp "${tmp%/}/board-checks.${file##*/}.XXXXXX") && cp "$dir/$i.out" "$kept"; then
      echo "board-checks: $file failed (exit $status); its full output: $kept" >&2
    else
      echo "board-checks: $file failed (exit $status); its output follows (no file could be kept)" >&2
      cat "$dir/$i.out" >&2
    fi
    failed=1
  fi
done
exit "$failed"
