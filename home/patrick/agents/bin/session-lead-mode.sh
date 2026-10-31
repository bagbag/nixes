#!/usr/bin/env bash
# Session role registry shared by Codex and Claude Code: one JSON file per
# session id under a persistent state dir, so a resumed session keeps its role.
# activate and actor take the session from the environment; Codex's variables
# win, so a Codex session started from Claude is itself (a Claude session
# started from Codex is not: it inherits CODEX_SESSION_ID). The
# session-register hook keeps workers from registering.
# activate and alive record the Claude Code process (pid, pid_started) so
# board position can tell a gone session. The session-activity hook records
# activity as file mtimes: session-active touches <session>.active for the
# session's own tool calls; worker-started and worker-active create or touch
# one marker file per running worker in <session>.workers/ and worker-ended
# deletes it, so a stopped worker has none (one file per worker: workers
# stopping together would overwrite each other's marks in one shared file). Codex records no process: the nearest `codex`
# ancestor can be an app-server daemon shared by many sessions or a
# per-command `codex sandbox` helper, so Codex holds keep the idle hint.
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
       session-lead-mode alive
       session-lead-mode session-active
       session-lead-mode worker-started <agent-id>
       session-lead-mode worker-active <agent-id>
       session-lead-mode worker-ended <agent-id>
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

# The agent session running this command (board-core.md#actors-and-holds).
environment_session() {
  if [[ -n ${CODEX_SESSION_ID-} ]]; then
    session=$CODEX_SESSION_ID tool=codex thread=${CODEX_THREAD_ID-}
  elif [[ -n ${CLAUDE_CODE_SESSION_ID-} ]]; then
    session=$CLAUDE_CODE_SESSION_ID tool=claude
  else
    return 1
  fi
}

from_environment() {
  environment_session || fail "no agent session: run inside Claude Code or Codex"
  valid_session_id "$session"
}

# Hook-run commands (alive, session-active, worker-*) end silently without a registered
# session: a failing SubagentStop hook would keep the worker running.
registered_session() {
  environment_session && [[ "$session" =~ ^[A-Za-z0-9._-]{8,}$ ]] || exit 0
  target="$state_dir/$session.json"
  [[ -f "$target" ]] || exit 0
}

# The legacy <session>.ended/ folder marked stopped workers, which a missing
# marker now expresses; readers and writers drop it.
drop_legacy_markers() {
  rm -rf -- "${1%.json}.ended" 2>/dev/null || true
}

# A file's mtime as UTC ISO time, or failure when it is missing (date -r
# reads a file's mtime on BSD and GNU).
modified_at() {
  date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null
}

# A registry entry as show and list print it. active_at: the session's last
# own tool call; workers: running workers (agent ids' last 8 characters) and
# their last tool call. board judges what counts as recent.
entry_json() {
  local times=() marker modified active_at=''
  drop_legacy_markers "$1"
  if modified=$(modified_at "${1%.json}.active"); then
    active_at=$modified
  fi
  for marker in "${1%.json}.workers"/*; do
    modified=$(modified_at "$marker") || continue  # none, or removed meanwhile
    times+=("${marker##*/}" "$modified")
  done
  jq -c --arg active_at "$active_at" --args \
    '{role, pulls, actor, tool, session, registered_at, pid, pid_started,
      active_at: (if $active_at == "" then null else $active_at end),
      workers: ([range(0; $ARGS.positional | length; 2) as $i | {($ARGS.positional[$i]): $ARGS.positional[$i + 1]}] | add // {})}' \
    "${times[@]}" <"$1"
}

ps_command=$(command -v ps || echo /bin/ps)

# "<pid>\n<UTC start time>" of the Claude Code process running this command, or
# nothing (Codex, no agent ancestor, ps unavailable).
process_identity() {
  local pid=$$ name started
  while [[ "$pid" =~ ^[0-9]+$ ]] && ((pid > 1)); do
    name=$(LC_ALL=C "$ps_command" -o comm= -p "$pid" 2>/dev/null) || return 0
    case ${name##*/} in
      claude)
        # UTC, as board.py compares it: a time-zone change must not read as a new process.
        started=$(LC_ALL=C TZ=UTC0 "$ps_command" -o lstart= -p "$pid" 2>/dev/null) || return 0
        [[ -n "$started" ]] || return 0
        read -r -a started <<<"$started"
        printf '%s\n%s\n' "$pid" "${started[*]}"
        return 0
        ;;
      codex) return 0 ;;
    esac
    pid=$(LC_ALL=C "$ps_command" -o ppid= -p "$pid" 2>/dev/null) || return 0
    pid=${pid//[[:space:]]/}
  done
}

# Sets pid and pid_started from process_identity; both empty without one.
# jq callers bind them and merge `identity` (pid fields, or none).
identity_filter='def identity: if $pid == "" then {} else {pid: ($pid | tonumber), pid_started: $pid_started} end;'
read_identity() {
  local identity=''
  [[ "$tool" != claude ]] || identity=$(process_identity)
  pid='' pid_started=''
  [[ -z "$identity" ]] || pid=${identity%%$'\n'*} pid_started=${identity#*$'\n'}
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
    read_identity
    temporary=$(mktemp "$state_dir/.$session.XXXXXX")
    jq -n \
      --arg session "$session" \
      --arg role "$role" \
      --arg actor "${session: -8}" \
      --arg tool "$tool" \
      --arg registered_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg pid "$pid" \
      --arg pid_started "$pid_started" \
      --args \
      "$identity_filter"'{session: $session, role: $role, pulls: $ARGS.positional, actor: $actor,
        tool: $tool, registered_at: $registered_at} + identity' \
      "${selected[@]}" >"$temporary"
    mv -f "$temporary" "$target"
    ;;
  alive)
    [[ -z "$role$pulls" ]] || usage
    registered_session
    read_identity
    umask 077
    temporary=$(mktemp "$state_dir/.$session.XXXXXX")
    jq --arg pid "$pid" --arg pid_started "$pid_started" \
      "$identity_filter"'del(.pid, .pid_started, .ended_workers) + identity' "$target" >"$temporary"
    mv -f "$temporary" "$target"
    ;;
  session-active)
    [[ -z "$role$pulls" ]] || usage
    registered_session
    umask 077
    touch "$state_dir/$session.active"
    ;;
  worker-started | worker-active | worker-ended)
    [[ -z "$pulls" && "$role" =~ ^[A-Za-z0-9._-]{8,}$ ]] || usage
    registered_session
    drop_legacy_markers "$target"
    marker="$state_dir/$session.workers/${role: -8}"
    if [[ "$command" == worker-ended ]]; then
      rm -f "$marker"
    else
      # A stopped worker makes no tool calls, so a heartbeat may create the
      # marker: it covers a worker whose SubagentStart was missed.
      umask 077
      mkdir -p "${marker%/*}"
      touch "$marker"
    fi
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
        entry_json "$registration"
      fi
      exit 0
    fi
    [[ "$command" == get ]] ||
      jq -nc --arg actor "${session: -8}" --arg session "$session" \
        '{role: null, pulls: [], actor: $actor, tool: null, session: $session, registered_at: null,
          pid: null, pid_started: null, active_at: null, workers: {}}'
    ;;
  list)
    [[ -z "$role$session$pulls$tool" ]] || usage
    [[ -d "$state_dir" ]] || exit 0
    shopt -s nullglob
    files=("$state_dir"/*.json)
    for registration in "${files[@]}"; do
      entry_json "$registration"
    done
    ;;
  *) usage ;;
esac
