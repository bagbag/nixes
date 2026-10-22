#!/usr/bin/env bash
# Session role registry shared by Codex and Claude Code: one JSON file per
# session id under a persistent state dir, so a resumed session keeps its role.
# activate and actor take the session from the environment; Codex's variables
# win, so a Codex session started from Claude is itself (a Claude session
# started from Codex is not: it inherits CODEX_SESSION_ID). The
# session-register hook keeps workers from registering.
set -euo pipefail

state_dir=${AGENT_SESSION_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-sessions}
pull_order=(plan design implement review)

usage() {
  cat >&2 <<'EOF'
usage: session-lead-mode activate <lead|agent|solo|autopilot> [--pulls plan,design,implement,review]
       session-lead-mode actor
       session-lead-mode get <id>
       session-lead-mode show <id>
       session-lead-mode list
`--pulls` applies only to agent, which needs at least one pull.
EOF
  exit 2
}

fail() {
  echo "session-lead-mode: $1" >&2
  exit 2
}

[[ $# -gt 0 ]] || usage
command=$1
shift
role='' pulls='' session='' tool='' thread=''
while (($#)); do
  case $1 in
    --pulls) (($# >= 2)) || usage; pulls=$2; shift 2 ;;
    --pulls=*) pulls=${1#*=}; shift ;;
    -*) usage ;;
    *)
      [[ -z "$role" ]] || usage
      role=$1
      shift
      ;;
  esac
done

valid_session_id() {
  [[ "$1" =~ ^[A-Za-z0-9._-]{8,}$ ]] || fail "invalid session id '$1'"
}

# The agent session running this command (work-tracking.md#actors-and-holds).
from_environment() {
  if [[ -n ${CODEX_SESSION_ID-} ]]; then
    session=$CODEX_SESSION_ID tool=codex thread=${CODEX_THREAD_ID-}
  elif [[ -n ${CLAUDE_CODE_SESSION_ID-} ]]; then
    session=$CLAUDE_CODE_SESSION_ID tool=claude
  else
    fail "no agent session: run inside Claude Code or Codex"
  fi
  valid_session_id "$session"
}

case "$command" in
  activate)
    case "$role" in
      lead | agent | solo | autopilot) ;;
      *) usage ;;
    esac
    from_environment

    selected=()
    if [[ "$role" == agent ]]; then
      [[ -n "$pulls" ]] || fail "agent needs --pulls with at least one of: ${pull_order[*]}"
      IFS=',' read -r -a requested <<<"$pulls"
      for pull in "${requested[@]}"; do
        [[ " ${pull_order[*]} " == *" $pull "* ]] || fail "unknown pull '$pull'; choose from: ${pull_order[*]}"
      done
      for pull in "${pull_order[@]}"; do
        [[ ",$pulls," == *",$pull,"* ]] && selected+=("$pull")
      done
    elif [[ -n "$pulls" ]]; then
      fail "--pulls applies only to agent"
    fi

    umask 077
    mkdir -p "$state_dir"
    target="$state_dir/$session.json"
    temporary=$(mktemp "$state_dir/.$session.XXXXXX")
    jq -n \
      --arg session "$session" \
      --arg role "$role" \
      --arg actor "${session: -8}" \
      --arg tool "$tool" \
      --arg registered_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --args \
      '{session: $session, role: $role, pulls: $ARGS.positional, actor: $actor,
        tool: $tool, registered_at: $registered_at}' \
      "${selected[@]}" >"$temporary"
    mv -f "$temporary" "$target"
    ;;
  actor)
    [[ -z "$role$pulls" ]] || usage
    from_environment
    actor=${session: -8}
    [[ -z "$thread" || "$thread" == "$session" ]] || actor+="/${thread: -8}"
    printf '%s\n' "$actor"
    ;;
  get | show)
    [[ -z "$role" || -z "$session" ]] || usage
    session=${session:-$role}
    [[ -n "$session" ]] || fail "$command needs a session id"
    valid_session_id "$session"

    registration="$state_dir/$session.json"
    if [[ -f "$registration" ]]; then
      if [[ "$command" == get ]]; then
        jq -r '.role' "$registration"
      else
        jq -c '{role, pulls, actor, tool, session, registered_at}' "$registration"
      fi
      exit 0
    fi
    [[ "$command" == get ]] ||
      jq -nc --arg actor "${session: -8}" --arg session "$session" \
        '{role: null, pulls: [], actor: $actor, tool: null, session: $session, registered_at: null}'
    ;;
  list)
    [[ -z "$role$session$pulls$tool" ]] || usage
    [[ -d "$state_dir" ]] || exit 0
    shopt -s nullglob
    files=("$state_dir"/*.json)
    ((${#files[@]} == 0)) || jq -c '{role, pulls, actor, tool, session, registered_at}' "${files[@]}"
    ;;
  *) usage ;;
esac
