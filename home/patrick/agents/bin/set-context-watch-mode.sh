#!/usr/bin/env bash
# Portable entry point for skills that benefit from a context monitor.
# Claude Code exposes its session ID to Bash subprocesses; other tools safely
# no-op until they provide a compatible monitor.
set -euo pipefail

mode=${1:-}
case "$mode" in
  autopilot | supervisor) ;;
  *)
    echo "usage: set-context-watch-mode <autopilot|supervisor>" >&2
    exit 2
    ;;
esac

session_id=${CLAUDE_CODE_SESSION_ID:-}
[[ -n "$session_id" ]] || exit 0

state_dir=/tmp/claude-context-watch
mkdir -p "$state_dir"
printf '%s\n' "$mode" >"$state_dir/$session_id.mode"
