#!/usr/bin/env bash
# Record and query the user-selected lead skill for a Codex or Claude session.
set -euo pipefail

runtime_dir=${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}
state_dir=${AGENT_SESSION_LEAD_STATE_DIR:-$runtime_dir/agent-session-leads}

session_id_from_env() {
  printf '%s' "${CLAUDE_CODE_SESSION_ID:-${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}}"
}

valid_session_id() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

command=${1:-}
case "$command" in
  activate)
    mode=${2:-}
    case "$mode" in
      autopilot | supervisor) ;;
      *)
        echo "usage: session-lead-mode activate <autopilot|supervisor>" >&2
        exit 2
        ;;
    esac

    session_id=$(session_id_from_env)
    [[ -n "$session_id" ]] || exit 0
    valid_session_id "$session_id" || exit 2

    umask 077
    mkdir -p "$state_dir"
    printf '%s\n' "$mode" >"$state_dir/$session_id.mode"
    ;;
  get)
    session_id=${2:-$(session_id_from_env)}
    [[ -n "$session_id" ]] || exit 0
    valid_session_id "$session_id" || exit 2

    state="$state_dir/$session_id.mode"
    [[ -f "$state" ]] || exit 0
    mode=$(<"$state")
    case "$mode" in
      autopilot | supervisor) printf '%s\n' "$mode" ;;
    esac
    ;;
  *)
    echo "usage: session-lead-mode <activate MODE|get [SESSION_ID]>" >&2
    exit 2
    ;;
esac
